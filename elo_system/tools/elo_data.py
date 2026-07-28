import json

import pandas as pd
import psycopg2

from typing import Any
from pathlib import Path
from rv_pytools.functions import anonymize, deanonymize
from rv_pytools.sqltools import connect

from .basics import (
    DataBase,
    bigint_generator,
    id_generator,
    ANON_COLS,
    ANON_FACT_NAME_COL,
    ANON_MAP_FSTR,
    ANON_MEMBER_DIM,
    DEFAULT_ANON_DIR,
    ELO_DIM_KEYS,
    ELO_DIM_ORDER,
    ELO_DIMS,
    FACT_SPECS,
    LEAGUE_MANAGER_SPEC,
    LOAD_QUERIES
)
from .helpers import (
    fstr_matcher,
    replace_dataframe,
    score_pivot,
    score_unpivot,
    upsert_dataframe,
    uri_to_dict,
    validate_conn_dict
)


class EloCSV(DataBase):
    def __init__(
            self, config: dict
            , working_directory: Path
            , league_dir: str | None = None
    ) -> None:
        super().__init__(
            config
        )

        self.dynasty_fstr = config.get('dynasty_fstr', 'dynasty_elo{ext}')
        self.elo_fstr = config.get('elo_fstr', '{num}_season_elo{ext}')
        self.roto_fstr = config.get('roto_fstr', '{num}_roto_elo{ext}')

        self.write_loc = config['write_loc']
        self.read_loc = config.get('read_loc', self.write_loc)
        self.extension = config.get('extension', '.csv')
        self.wd = working_directory
        # One CSV config serves every league, so each gets its own directory
        # under it -- the frames are named by season alone, and two leagues
        # sharing a directory would overwrite each other.
        self.league_dir = league_dir
        # Ensure the ratings (output) directory exists before any publish.
        self.out_dir = self._scoped(self.write_loc)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        # Input directory for load_frames (defaults to the output directory).
        self.in_dir = self._scoped(self.read_loc)

    def _scoped(self, location: str) -> Path:
        parts = [self.wd, location]
        if self.league_dir:
            parts.append(self.league_dir)
        return Path(*parts)

    def _publish_dynasty_elo(self, frame: pd.DataFrame) -> None:
        file_path = Path(self.out_dir, self.dynasty_fstr.format(ext=self.extension))
        frame.to_csv(file_path, index=True)

    def _publish_indexed_frame(self, destination: str, num: int, frame: pd.DataFrame) -> None:
        if destination == 'seasonal_elo':
            final_destination = self.elo_fstr.format(ext=self.extension, num=num)
        elif destination == 'roto_history':
            final_destination = self.roto_fstr.format(ext=self.extension, num=num)
        else:
            raise KeyError('Unknown destination: {}'.format(destination))
        file_path = Path(self.out_dir, final_destination)
        frame.to_csv(file_path, index=True)

    def _read_csv(self, file_path: Path) -> pd.DataFrame:
        # index=True on publish writes the member id index; restore it here.
        # round_trip parsing costs a little speed and buys back the last bit of
        # every rating: the default parser is up to an ulp out, which is enough
        # to make a frame read from here differ from the same one read from the
        # SQL backend, where float8 is exact.
        frame = pd.read_csv(file_path, index_col=0, float_precision='round_trip')
        # The index is the member id, an opaque identifier that happens to be
        # all digits on some platforms (Sleeper user ids) and not on others
        # (Fantrax owner names). Left to itself the parser types the first kind
        # as int64, and the frame stops matching the string keys the league
        # config and the SQL backend both use.
        frame.index = frame.index.astype(str)
        return frame

    def _load_single(self, fstr: str) -> pd.DataFrame | None:
        file_path = Path(self.in_dir, fstr.format(ext=self.extension))
        if not file_path.exists():
            return None
        return self._read_csv(file_path)

    def _load_indexed_set(self, fstr: str) -> dict[Any, pd.DataFrame]:
        # Recovers the per-season key embedded in each filename. Under the
        # default seasons_by='year' that key is the season year; under
        # 'order' it is the ordinal the file was written with.
        glob, matcher = fstr_matcher(fstr, self.extension)
        frames: dict[Any, pd.DataFrame] = {}
        if not self.in_dir.exists():
            return frames
        for file_path in sorted(self.in_dir.glob(glob)):
            m = matcher.match(file_path.name)
            if m is None:
                continue
            num = m.group('num')
            key = int(num) if num.lstrip('-').isdigit() else num
            frames[key] = self._read_csv(file_path)
        return frames

    def load_frames(self, frame_set: str | list[str] | None = None) -> dict[str, Any]:
        loaders = {
            'dynasty_elo': lambda: self._load_single(self.dynasty_fstr),
            'seasonal_elo': lambda: self._load_indexed_set(self.elo_fstr),
            'roto_history': lambda: self._load_indexed_set(self.roto_fstr),
        }
        if frame_set is None:
            frame_set = list(loaders.keys())
        elif isinstance(frame_set, str):
            frame_set = [frame_set]

        out: dict[str, Any] = {}
        for fs in frame_set:
            if fs not in loaders:
                raise KeyError('Unknown frame set: {}'.format(fs))
            loaded = loaders[fs]()
            # Omit sets with no data on disk so FrameManager.load_frames never
            # has to iterate a missing/None entry.
            if loaded is not None and (not isinstance(loaded, dict) or loaded):
                out[fs] = loaded
        return out

class EloSQL(DataBase):
    """Postgres twin of EloCSV.

    Publishes the FrameManager payload into the star schema and reads it back
    in the shape EloCSV returns, so the two are interchangeable as EloSystem's
    reader and writer.

    The frames are indexed by league member -- the id of the account that member
    plays under on the platform -- while the schema keys off surrogate ids.
    ``league_members`` in the league config bridges the two: it maps each member
    to the platform team id that identifies their ``dim_team`` row for a season,
    and each member is a ``dim_manager_platform`` row under
    ``platform_user_id``, which is what the load path reads the index back out
    of.

    That row is the join between an account and the *person* holding it, which is
    the ``dim_manager`` row behind it. One person can hold an account on each
    platform and play in any number of leagues across any number of Discord
    servers, so a member already on file from another league is matched on
    ``(platform, platform_user_id)`` and reuses their existing ``manager_id``
    rather than being minted again. Which leagues a manager turns out to be in
    is recorded in ``mvw_fact_league_managers``.

    With ``anonymizer`` set in the config, names are tokenised at the storage
    boundary: the dim tables held here always carry real values, tokens exist
    only in the DB, and the reversal maps live under ``anon_loc``. Which columns
    that covers is ``anon_columns``, defaulting to the platform identity.
    """

    def __init__(
            self,
            config: dict,
            league_config: dict | None = None,
            connector: psycopg2.extensions.connection | None = None,
            working_directory: Path | None = None,
    ) -> None:
        super().__init__(
            config
        )

        if isinstance((conn_dict := config.get('conn_dict')), dict):
            pass
        else:
            if isinstance((conn_uri := config.get('conn_uri')), str):
                conn_dict = uri_to_dict(conn_uri)
            else:
                raise KeyError('No connection details supplied.')
        if not validate_conn_dict(conn_dict):
            raise ValueError('Incomplete connection details supplied.')
        self.conn_dict = conn_dict
        # Connect on first use, not here. Constructing this backend must not
        # reach the network: EloSystem builds every configured backend up
        # front, so an unreachable database would otherwise take the CSV
        # workflow down with it.
        self._conn = connector

        self.schema = self.conn_dict.get('schema', config.get('schema', 'fantasy_sports'))

        # Anonymisation is a storage-boundary concern: the dim tables held here
        # always carry real values, and the tokens exist only in the DB. So it
        # has to be configured before the first pull.
        self.anonymized = bool(config.get('anonymizer', False))
        # Maps default under the resources directory, next to the rest of the
        # local data; a relative anon_loc is read the same way, and an absolute
        # one wins outright.
        self.wd = Path(working_directory) if working_directory is not None else Path('.')
        self.anon_loc = Path(config.get('anon_loc', DEFAULT_ANON_DIR))
        if not self.anon_loc.is_absolute():
            self.anon_loc = self.wd / self.anon_loc
        self.anon_cols: dict[str, dict[str, str]] = {
            dim: dict(cols) for dim, cols in ANON_COLS.items()
        }
        for dim, cols in config.get('anon_columns', dict()).items():
            self.anon_cols.setdefault(dim, dict()).update(cols)

        # Pulled lazily, one dim at a time, the first time each is read.
        self.dim_tables: dict[str, pd.DataFrame] = {}

        self.league_config: dict[str, Any] = {}
        self.seasons: dict[Any, Any] = {}
        self.platform = None
        self.current_sports_year = None
        self._league_id = -1
        self._league_id_stale = True
        self.league_name = None
        # Store the config without resolving which dim_league row it is --
        # that needs the DB, and construction stays offline.
        self._store_league_config(league_config)

        self.current_frame = pd.DataFrame()

    @property
    def conn(self):
        """The database connection, opened on first use."""
        if self._conn is None:
            self._conn = connect(self.conn_dict)
        return self._conn

    @property
    def league_id(self) -> int:
        """Which dim_league row this config is, resolved against the DB once."""
        if self._league_id_stale:
            self._resolve_league_id()
        return self._league_id

    @league_id.setter
    def league_id(self, value: int) -> None:
        self._league_id = value
        self._league_id_stale = False

    # ------------------------------------------------------------------
    # dimension tables
    # ------------------------------------------------------------------

    @staticmethod
    def _dim_table(dim: str) -> str:
        return 'dim_{}'.format(dim)

    @staticmethod
    def _dim_keys(dim: str) -> list[str]:
        """The dim's key columns, which is what its upsert conflicts on."""
        return list(ELO_DIM_KEYS.get(dim, ('{}_id'.format(dim),)))

    @classmethod
    def _dim_key(cls, dim: str) -> str | None:
        """The dim's surrogate id, or None if it has a natural composite key.

        Only a single-column key is ours to mint, and only such a dim is held
        indexed by it -- a composite key belongs to the platform, so there is no
        id to generate and nothing to index on.
        """
        keys = cls._dim_keys(dim)
        return keys[0] if len(keys) == 1 else None

    def _dim_frame(self, dim: str) -> pd.DataFrame:
        """The cached dim table, pulled from the DB the first time it is read.

        Every dim access goes through here, which is what keeps construction
        offline: nothing is fetched until something actually needs a row.

        Indexed by its surrogate id where it has one; a composite-key dim comes
        back with every key column still a column.
        """
        self._pull_dim(dim, False)
        return self.dim_tables[self._dim_table(dim)]

    def _dim(self, dim: str) -> pd.DataFrame:
        """The cached dim table with every key back as a column."""
        frame = self._dim_frame(dim)
        if self._dim_key(dim) is None:
            # Already flat; reset_index would only add its RangeIndex as a column.
            return frame.copy()
        return frame.reset_index()

    # ------------------------------------------------------------------
    # anonymisation
    # ------------------------------------------------------------------

    def _anon_map_path(self, dim: str) -> Path:
        """Where a dim's reversal map lives.

        One file per dim: anonymize() rewrites its whole map on every call, so
        two dims sharing a file would leave the second one's tokens the only
        ones reversible.
        """
        return self.anon_loc / ANON_MAP_FSTR.format(dim=dim)

    def _anon_cols(self, dim: str) -> dict[str, str]:
        frame = self.dim_tables.get(self._dim_table(dim))
        if not self.anonymized or frame is None:
            return dict()
        return {
            column: category
            for column, category in self.anon_cols.get(dim, dict()).items()
            if column in frame.columns
        }

    def _anonymize_dim(self, dim: str, frame: pd.DataFrame) -> pd.DataFrame:
        """Tokenise a dim on its way to the DB, writing the reversal map.

        Rows go out ordered by key so a token keeps meaning the same row from one
        publish to the next: anonymize() numbers per call, so anything that
        reordered the frame would silently repoint every token.
        """
        columns = self._anon_cols(dim)
        if not columns:
            return frame
        self.anon_loc.mkdir(parents=True, exist_ok=True)
        return anonymize(
            frame.sort_values(self._dim_keys(dim)),
            columns,
            self._anon_map_path(dim),
        )

    def _deanonymize_dim(self, dim: str, frame: pd.DataFrame) -> pd.DataFrame:
        """Restore real values on a dim just read out of the DB.

        A missing map leaves the frame as-is: tokens are still valid keys, so a
        read against a DB anonymised elsewhere degrades to token-named members
        rather than failing.
        """
        columns = self._anon_cols(dim)
        if not columns or not self._anon_map_path(dim).exists():
            return frame
        return deanonymize(frame, columns, self._anon_map_path(dim))

    def anon_tokens(self, dim: str, category: str) -> dict[Any, Any]:
        """The real value -> token lookup for one category of one dim.

        Lets the fact tables reuse the tokens a dim push just minted instead of
        calling anonymize() again, which would overwrite that dim's map.
        """
        path = self._anon_map_path(dim)
        if not self.anonymized or not path.exists():
            return dict()
        with path.open() as handle:
            mapping = json.load(handle)
        return {value: token for token, value in mapping.get(category, dict()).items()}

    def _fact_name_tokens(self) -> dict[Any, Any]:
        """Tokens for the name the facts denormalise, keyed by the real name."""
        category = self._anon_cols(ANON_MEMBER_DIM).get(ANON_FACT_NAME_COL)
        if category is None:
            return dict()
        return self.anon_tokens(ANON_MEMBER_DIM, category)

    # ------------------------------------------------------------------
    # dimension tables
    # ------------------------------------------------------------------

    def _pull_dim(self, dim: str, overwrite: bool) -> bool:
        table = self._dim_table(dim)
        if not overwrite:
            if table in self.dim_tables:
                return True
        # read_sql_table requires a SQLAlchemy connectable; self.conn is a raw
        # psycopg2 connection, so query explicitly like the load methods do.
        # index_col is None for a composite-key dim, which leaves its key columns
        # where they are.
        self.dim_tables.update({table: pd.read_sql_query(
            f'SELECT * FROM {self.schema}.{table}', self.conn, index_col=self._dim_key(dim)
        )})
        self.dim_tables[table] = self._deanonymize_dim(dim, self.dim_tables[table])
        return True

    def pull_dims(self, which: str | set[str] | None = None, overwrite: bool = False) -> bool:
        if isinstance(which, str):
            return self._pull_dim(which, overwrite)
        else:
            if which is None:
                which = ELO_DIMS
            for each in which:
                self._pull_dim(each, overwrite)
            return True

    def reset_dims(self) -> bool:
        return self.pull_dims(overwrite=True)

    def _push_dim(self, dim: str) -> bool:
        frame = self._dim(dim)
        if frame.empty:
            return True
        upsert_dataframe(
            self.conn,
            self._anonymize_dim(dim, frame),
            self._dim_table(dim),
            self._dim_keys(dim),
            self.schema
        )
        return True

    def push_dims(self, which: str | set[str] | None = None) -> bool:
        if isinstance(which, str):
            return self._push_dim(which)
        else:
            # Parents before children, whatever order the caller asked in --
            # the foreign keys out of dim_team and dim_online_league make the
            # write order load-bearing.
            if which is None:
                which = ELO_DIM_ORDER
            else:
                which = [dim for dim in ELO_DIM_ORDER if dim in which]
            for each in which:
                self._push_dim(each)
            return True

    def _next_dim_id(self, dim: str) -> int:
        # The dim tables carry no sequence defaults, so surrogate ids are minted
        # here off whatever the cached table already holds.
        if self._dim_key(dim) is None:
            raise KeyError('dim_{} has no surrogate id to mint'.format(dim))
        index = self._dim_frame(dim).index
        if len(index) == 0:
            return 0
        return int(index.max()) + 1

    def _append_dim(self, dim: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        table = self._dim_table(dim)
        existing = self._dim_frame(dim)
        new = pd.DataFrame.from_records(rows)
        if (key := self._dim_key(dim)) is not None:
            new = new.set_index(key)
        combined = new if existing.empty else pd.concat([existing, new])
        if key is None:
            # No index to collide on, so a re-staged natural key would otherwise
            # go in twice and the upsert would conflict with itself.
            combined = combined.drop_duplicates(
                subset=self._dim_keys(dim), keep='last'
            ).reset_index(drop=True)
        # Staged rows may omit nullable columns; keep the table's own column
        # order so the eventual insert lines up with it.
        combined = combined.reindex(columns=existing.columns)
        # An omitted column arrives as all-NA float64, which a later update
        # cannot write a string or a bool into. Object is both what psycopg2
        # hands back for an all-NULL column and what accepts either.
        for column in combined.columns:
            if combined[column].isna().all():
                combined[column] = combined[column].astype(object)
        self.dim_tables[table] = combined

    def _update_dim(self, dim: str, rows: list[dict[str, Any]]) -> None:
        """Refresh the columns a sync owns on rows that already exist.

        Only the columns named in `rows` are touched, and a None among them
        means nothing was scraped for it, so whatever is stored survives. Every
        other column -- the ones the Discord side owns -- is never written here.
        """
        if not rows:
            return
        existing = self._dim_frame(dim)
        table = self._dim_table(dim)
        keys = self._dim_keys(dim)
        # One row can be staged by several seasons -- an account, or a team that
        # never changed hands -- and update() rejects a duplicated key outright.
        # The newest season is staged last, so that is the one to keep.
        updates = pd.DataFrame.from_records(rows).drop_duplicates(
            subset=keys, keep='last'
        )
        # DataFrame.update aligns on the index, so a composite-key dim has to be
        # keyed up for the call and flattened again afterwards.
        if self._dim_key(dim) is None:
            columns = list(existing.columns)
            keyed = existing.set_index(keys)
            keyed.update(updates.set_index(keys))
            self.dim_tables[table] = keyed.reset_index().reindex(columns=columns)
        else:
            existing.update(updates.set_index(keys[0]))

    # ------------------------------------------------------------------
    # league config
    # ------------------------------------------------------------------

    def set_league_config(self, league_config: dict[str, Any] | None) -> int:
        """Adopt an EloLeague config and resolve which dim_league row it is.

        publish() calls this again with the config off the payload, so seasons
        added since construction are picked up before anything is written.
        """
        self._store_league_config(league_config)
        return self._resolve_league_id()

    def _store_league_config(self, league_config: dict[str, Any] | None) -> None:
        """Adopt the config without touching the DB; the id resolves on read."""
        self.league_config = league_config or dict()
        self.seasons = self.league_config.get('seasons', dict())
        self.platform = self.league_config.get('platform')
        self.current_sports_year = self.league_config.get('current_sports_year')
        self._league_id_stale = True

    def _season_platform(self, year: Any) -> Any:
        """Which platform a season was played on.

        Defaults to the league's platform, but a season may name its own:
        dim_online_league carries the platform per season precisely so a league
        that moved -- Fantrax one year, Sleeper the next -- keeps a single
        identity across the move.
        """
        return self.seasons.get(year, dict()).get('platform', self.platform)

    def _league_platforms(self) -> list[Any]:
        """The platforms this league has played on, newest season first."""
        seen = []
        for year in sorted(self.seasons, reverse=True):
            if (platform := self._season_platform(year)) not in seen:
                seen.append(platform)
        if not seen and self.platform is not None:
            seen.append(self.platform)
        return seen

    def _platform_league_ids(self) -> set[tuple]:
        """The (platform, league id) pairs this config's seasons are known by."""
        return {
            (self._season_platform(year), season['league_id'])
            for year, season in self.seasons.items() if season.get('league_id')
        }

    def _lookup_league_id(self) -> int:
        """Find the dim_league row behind this config by way of any season's
        platform league id. -1 when the league is not in the DB yet."""
        online = self._dim('online_league')
        if online.empty:
            return -1
        # Matched on the pair rather than the id alone: a league id is only
        # unique within its own platform, and one Discord server can run leagues
        # on more than one.
        pairs = self._platform_league_ids()
        known = online[[
            (platform, platform_league_id) in pairs
            for platform, platform_league_id
            in zip(online['platform'], online['platform_league_id'])
        ]]
        if known.empty:
            return -1
        return int(known['league_id'].max())

    def _resolve_league_id(self) -> int:
        configured = self.league_config.get('league_id', -1)
        if configured is not None and configured >= 0:
            self.league_id = configured
        else:
            self.league_id = self._lookup_league_id()

        leagues = self._dim('league')
        if not leagues.empty:
            mine = leagues[leagues['league_id'] == self.league_id]
            if not mine.empty:
                self.league_name = mine['league_name'].iloc[-1]
        return self.league_id

    def get_lid(self) -> int:
        return self.league_id

    # ------------------------------------------------------------------
    # dimension sync
    # ------------------------------------------------------------------

    def _members(self, year: Any) -> dict[str, Any]:
        return self.seasons.get(year, dict()).get('league_members', dict())

    def _scraped_league_name(self) -> str | None:
        """The platform's own name for this league.

        Each season is a separate league on the platform carrying the same
        display name, so the newest scraped season wins.
        """
        if (name := self.league_config.get('league_name')):
            return name
        for year in sorted(self.seasons, reverse=True):
            if (name := self.seasons[year].get('league_name')):
                return name
        return None

    def _stored_server_id(self) -> Any:
        """The discord_server_id already on this league's row, if it has one."""
        leagues = self._dim('league')
        if leagues.empty:
            return None
        mine = leagues[leagues['league_id'] == self.league_id]
        if mine.empty:
            return None
        stored = mine['discord_server_id'].iloc[-1]
        return None if pd.isna(stored) else stored

    def _ensure_league(self) -> int:
        name = self._scraped_league_name()
        if self.league_id >= 0:
            updates: dict[str, Any] = {'league_id': self.league_id}
            # An existing row may predate the scrape that learned the real name
            # -- refresh it, but never blank it back to a placeholder.
            if name and name != self.league_name:
                self.league_name = name
                updates['league_name'] = name
            # A row left without a server id gets one now, so the column is
            # never null. Whatever is stored is left alone: only the Discord
            # side ever replaces a generated id with the real one.
            if self._stored_server_id() is None:
                updates['discord_server_id'] = self.league_config.get(
                    'discord_server_id', bigint_generator()
                )
            if len(updates) > 1:
                self._update_dim('league', [updates])
            return self.league_id

        self.league_id = self._next_dim_id('league')
        # A generated name only stands in until a scrape supplies the real one.
        self.league_name = name or id_generator()
        # No platform here: a league is a community on a Discord server, and
        # which platform it played on is a property of each of its seasons.
        #
        # discord_server_id is seeded with a generated id when the config has
        # none, the same way dim_manager's Discord-owned columns are: the row
        # stays complete, and the Discord side overwrites it with the real one.
        self._append_dim('league', [{
            'league_id': self.league_id,
            'discord_server_id': self.league_config.get(
                'discord_server_id', bigint_generator()
            ),
            'league_name': self.league_name,
        }])
        return self.league_id

    def _online_league_id(self, year: Any) -> int | None:
        online = self._dim('online_league')
        if online.empty:
            return None
        mask = (online['league_id'] == self.league_id) & (online['league_year'] == year)
        matched = online[mask]
        if matched.empty:
            return None
        return int(matched['online_league_id'].max())

    def _add_league_year(self, year: int, platform_id: str) -> int:
        online_league_id = self._next_dim_id('online_league')
        self._append_dim('online_league', [{
            'online_league_id': online_league_id,
            'league_id': self.league_id,
            'platform': self._season_platform(year),
            'platform_league_id': platform_id,
            'league_year': year,
        }])
        return online_league_id

    def add_league_year(self, year: int | None = None, platform_id: str | None = None) -> int:
        """Stage the dim_online_league row for one season and return its id.

        Seasons already in the table come back as-is, so this is safe to call
        repeatedly for the same year.
        """
        if year is None:
            year = self.current_sports_year
        existing = self._online_league_id(year)
        if existing is not None:
            return existing
        if platform_id is None:
            platform_id = self.seasons.get(year, dict()).get('league_id', id_generator())
        return self._add_league_year(year, platform_id)

    def _ensure_online_leagues(self) -> dict[Any, int]:
        return {year: self.add_league_year(year) for year in sorted(self.seasons)}

    @staticmethod
    def _account_name(info: dict[str, Any]) -> Any:
        """The name the platform shows an account under.

        None when the scrape did not report one, which leaves whatever is stored
        alone. short_name is deliberately not a fallback: on Fantrax that is the
        *team*'s abbreviation, not anything the account is called.
        """
        return info.get('display_name')

    def _accounts(self) -> dict[tuple, int]:
        """manager id for every platform account on file, across every league."""
        accounts = self._dim('manager_platform')
        if accounts.empty:
            return dict()
        return {
            (platform, str(user_id)): int(manager_id)
            for platform, user_id, manager_id
            in zip(accounts['platform'], accounts['platform_user_id'],
                   accounts['manager_id'])
        }

    def _ensure_managers(self) -> dict[tuple, int]:
        """One dim_manager row per person, one dim_manager_platform row per account.

        A member is identified by the account they play under, which is what
        league_members is keyed by, and what dim_manager_platform holds as
        platform_user_id -- so that, not player_name, is what the load path reads
        the frame index back out of.

        dim_manager_platform spans every league in the schema, so a member who
        already plays elsewhere -- another league, another Discord server -- is
        matched here and keeps the manager_id they already have. Only a genuinely
        new account mints a new person. That is the whole reason the two tables
        are separate.

        player_name and discord_id belong to the Discord side; they are seeded
        with placeholder ids and never written again, so whatever Discord sets
        there survives every later sync. display_name is the platform's, so it is
        refreshed on every sync that reports one.

        Returns:
            manager id per (platform, member), spanning every account on file --
            not just this league's.
        """
        by_account = self._accounts()

        manager_rows = []
        new_accounts = []
        updated_accounts = []
        next_id = self._next_dim_id('manager')
        for year in sorted(self.seasons):
            platform = self._season_platform(year)
            for member, info in self._members(year).items():
                account = (platform, str(member))
                if (manager_id := by_account.get(account)) is not None:
                    updated_accounts.append({
                        'manager_id': manager_id,
                        'platform': platform,
                        'display_name': self._account_name(info),
                    })
                    continue
                by_account[account] = next_id
                manager_rows.append({
                    'manager_id': next_id,
                    'player_name': id_generator(),
                    'discord_id': id_generator(),
                })
                new_accounts.append({
                    'manager_id': next_id,
                    'platform': platform,
                    'platform_user_id': str(member),
                    # Never blank on insert, so the column always names something
                    # -- the account id itself until a scrape knows better.
                    'display_name': self._account_name(info) or str(member),
                })
                next_id += 1
        self._append_dim('manager', manager_rows)
        self._update_dim('manager_platform', updated_accounts)
        self._append_dim('manager_platform', new_accounts)
        return by_account

    def _scraped_team_cols(self, info: dict[str, Any], manager_id: int) -> dict[str, Any]:
        """The dim_team columns the platform is the source of truth for.

        is_champion and comanager_id are deliberately absent: a standing of 1
        mid-season is not a champion, and co-manager links come from Discord.
        """
        return {
            'team_name': info.get('curr_name'),
            'manager_id': manager_id,
            'is_commish': info.get('is_commish', False),
            'place_finish': info.get('standing'),
        }

    def _ensure_teams(self, online_league_ids: dict[Any, int], manager_ids: dict[tuple, int]) -> None:
        """One dim_team row per (season, platform team id).

        New teams are inserted; teams already on file have their scraped
        columns refreshed, so a rename, a handover or a moved standing lands
        without disturbing anything else on the row.
        """
        teams = self._dim_frame('team')
        existing: dict[tuple, int] = {}
        if not teams.empty:
            existing.update({
                (online_league_id, platform_team_id): int(team_id)
                for team_id, online_league_id, platform_team_id
                in zip(teams.index, teams['online_league_id'], teams['platform_team_id'])
            })

        new_rows = []
        updated_rows = []
        next_id = self._next_dim_id('team')
        for year in sorted(self.seasons):
            online_league_id = online_league_ids[year]
            platform = self._season_platform(year)
            for member, info in self._members(year).items():
                platform_team_id = str(info.get('team_id'))
                scraped = self._scraped_team_cols(
                    info, manager_ids[(platform, str(member))]
                )
                team_id = existing.get((online_league_id, platform_team_id))
                if team_id is None:
                    new_rows.append({
                        'team_id': next_id,
                        'online_league_id': online_league_id,
                        'platform_team_id': platform_team_id,
                        'league_year': year,
                        **scraped,
                    })
                    existing[(online_league_id, platform_team_id)] = next_id
                    next_id += 1
                else:
                    updated_rows.append({'team_id': team_id, **scraped})
        self._update_dim('team', updated_rows)
        self._append_dim('team', new_rows)

    def _league_manager_ids(self, manager_ids: dict[tuple, int]) -> list[int]:
        """The managers this league's own seasons name.

        manager_ids spans every account in the schema, so it cannot stand in for
        this: the bridge records who is in *this* league, and a manager only in
        some other one does not belong in it.
        """
        mine = {
            manager_ids[account]
            for year in self.seasons
            for member in self._members(year)
            if (account := (self._season_platform(year), str(member))) in manager_ids
        }
        return sorted(mine)

    def _push_league_managers(self, manager_ids: dict[tuple, int]) -> int:
        """Record which managers this league has.

        The bridge is derived, so this league's rows are rewritten wholesale
        rather than merged -- a member dropped from every season's league_members
        should stop being in the league. There is no unique constraint for an
        upsert to conflict on, and a scoped replace is what keeps a re-publish
        idempotent; other leagues' rows are never touched.
        """
        frame = pd.DataFrame(
            [
                {'league_id': self.league_id, 'manager_id': manager_id}
                for manager_id in self._league_manager_ids(manager_ids)
            ],
            columns=LEAGUE_MANAGER_SPEC['columns'],
        )
        return replace_dataframe(
            self.conn,
            frame,
            LEAGUE_MANAGER_SPEC['table'],
            LEAGUE_MANAGER_SPEC['scope'],
            self.league_id,
            self.schema
        )

    def sync_dims(self) -> None:
        """Bring the dim tables in line with the league config, then push them.

        Runs on its own -- a newly scraped season's members and teams can be
        registered before any elos exist for them -- and publish() calls it
        first so the fact-table foreign keys always have something to resolve
        against.
        """
        self._ensure_league()
        online_league_ids = self._ensure_online_leagues()
        manager_ids = self._ensure_managers()
        self._ensure_teams(online_league_ids, manager_ids)
        self.push_dims()
        # After the dims: the bridge has foreign keys into dim_league and
        # dim_manager, so both have to be on the DB side before it lands.
        self._push_league_managers(manager_ids)

    # ------------------------------------------------------------------
    # columns the sync does not own
    # ------------------------------------------------------------------

    def resolve_manager_id(self, member: str, platform: Any = None) -> int | None:
        """The dim_manager id for a league member, by the account they play under.

        The platform is half the identity -- platform_user_id is only unique
        within one -- so an explicit platform is matched exactly. Left out, this
        league's own platforms are tried newest season first, which is what
        resolves a member of a league that has moved between them.
        """
        accounts = self._accounts()
        if platform is not None:
            return accounts.get((platform, str(member)))
        for candidate in self._league_platforms():
            if (manager_id := accounts.get((candidate, str(member)))) is not None:
                return manager_id
        return None

    def resolve_team_id(self, year: Any, member: str) -> int | None:
        """The dim_team id for one member's team in one season."""
        online_league_id = self._online_league_id(year)
        if online_league_id is None:
            return None
        info = self._members(year).get(member)
        if info is None:
            return None
        teams = self._dim('team')
        if teams.empty:
            return None
        matched = teams[
            (teams['online_league_id'] == online_league_id)
            & (teams['platform_team_id'] == str(info.get('team_id')))
        ]
        if matched.empty:
            return None
        return int(matched['team_id'].max())

    def _set_team_column(self, team_id: int, column: str, value: Any, push: bool) -> int:
        table = self._dim_frame('team')
        if team_id not in table.index:
            raise KeyError('No dim_team row with team_id {}'.format(team_id))
        # Object dtype takes a clear-to-None as readily as a value, whatever
        # the column happened to arrive as.
        table[column] = table[column].astype(object)
        table.loc[team_id, column] = value
        if push:
            self._push_dim('team')
        return team_id

    def set_champion(
            self,
            year: Any,
            member: str | None = None,
            team_id: int | None = None,
            is_champion: bool | None = True,
            push: bool = True,
    ) -> int:
        """Flag (or clear) a team as a season's champion.

        sync_dims never writes is_champion -- a standing of 1 mid-season is not
        a champion -- so this is how the season's result gets recorded, once it
        is actually decided.

        Args:
            year:        Season the team played in.
            member:      League member owning the team; ignored if team_id is given.
            team_id:     Address the dim_team row directly instead.
            is_champion: True, False, or None to clear.
            push:        Write the dim back to the DB straight away.

        Returns:
            The dim_team id that was written.

        Raises:
            KeyError: If the team cannot be resolved, or is not on file.
        """
        if team_id is None:
            team_id = self.resolve_team_id(year, member)
        if team_id is None:
            raise KeyError('No team on file for {} in {}'.format(member, year))
        return self._set_team_column(team_id, 'is_champion', is_champion, push)

    def set_comanager(
            self,
            year: Any,
            member: str | None = None,
            comanager: str | int | None = None,
            team_id: int | None = None,
            push: bool = True,
    ) -> int:
        """Point a team at its co-manager, or clear the link.

        sync_dims never writes comanager_id, since co-manager links come from
        the Discord side rather than from anything the platform reports.

        Args:
            year:      Season the team played in.
            member:    League member owning the team; ignored if team_id is given.
            comanager: The co-manager's platform owner name, their manager_id,
                       or None to clear the link.
            team_id:   Address the dim_team row directly instead.
            push:      Write the dim back to the DB straight away.

        Returns:
            The dim_team id that was written.

        Raises:
            KeyError: If the team or the co-manager cannot be resolved.
        """
        if team_id is None:
            team_id = self.resolve_team_id(year, member)
        if team_id is None:
            raise KeyError('No team on file for {} in {}'.format(member, year))

        comanager_id = comanager
        if isinstance(comanager, str):
            comanager_id = self.resolve_manager_id(comanager)
            if comanager_id is None:
                raise KeyError('No manager on file for {}'.format(comanager))
        return self._set_team_column(team_id, 'comanager_id', comanager_id, push)

    # ------------------------------------------------------------------
    # publishing
    # ------------------------------------------------------------------

    def _resolve_year(self, num: int) -> Any:
        """DataBase hands an indexed frame its season key; under
        seasons_by='order' that key is an ordinal, which has to come back to a
        year before it can name a season in the DB."""
        if self.seasons_by == 'order':
            years = sorted(self.seasons)
            if 0 <= num < len(years):
                return years[num]
        return num

    MEMBER_TEAM_COLS = ['member', 'league_year', 'platform_team_id',
                        'manager_id', 'manager_name']
    MEMBER_MANAGER_COLS = ['member', 'manager_id', 'manager_name']

    def _member_teams(self) -> pd.DataFrame:
        """member -> platform team id and manager, per season, out of league_members.

        The manager is resolved here rather than read off dim_team, because a
        member is an account id and only the season settles which platform that
        id belongs to.
        """
        accounts = self._dim('manager_platform')
        resolved: dict[tuple, tuple] = {}
        if not accounts.empty:
            resolved = {
                (platform, str(user_id)): (manager_id, display_name)
                for platform, user_id, manager_id, display_name
                in zip(accounts['platform'], accounts['platform_user_id'],
                       accounts['manager_id'], accounts['display_name'])
            }

        rows = []
        for year in self.seasons:
            platform = self._season_platform(year)
            for member, info in self._members(year).items():
                manager_id, manager_name = resolved.get(
                    (platform, str(member)), (None, None)
                )
                rows.append({
                    'member': member,
                    'league_year': year,
                    'platform_team_id': str(info.get('team_id')),
                    'manager_id': manager_id,
                    'manager_name': manager_name,
                })
        return pd.DataFrame.from_records(rows, columns=self.MEMBER_TEAM_COLS)

    def _league_member_managers(self) -> pd.DataFrame:
        """member -> manager across every platform this league has used.

        Season-independent, so it can still name a manager for a week falling in
        a season they did not play -- which per-season resolution cannot do, and
        which is exactly the departed dynasty manager's case. It is also how the
        load path gets a member back out of a manager id.
        """
        empty = pd.DataFrame(columns=self.MEMBER_MANAGER_COLS)
        accounts = self._dim('manager_platform')
        if accounts.empty:
            return empty
        platforms = self._league_platforms()
        mine = accounts[accounts['platform'].isin(platforms)].dropna(subset='manager_id')
        if mine.empty:
            return empty
        # Sorted so the preferred row lands last for drop_duplicates: the newest
        # season's platform wins, which is the account a member who moved with
        # the league plays under now.
        rank = {platform: i for i, platform in enumerate(platforms)}
        mine = mine.assign(_rank=mine['platform'].map(rank)).sort_values(
            ['_rank', 'manager_id'], ascending=[False, True]
        )
        mine = mine.rename(columns={'platform_user_id': 'member',
                                    'display_name': 'manager_name'})
        # Both directions have to be one-to-one: a member names one manager, and
        # a manager comes back as one member. A person holding an account on two
        # of this league's platforms would otherwise duplicate every fact row.
        mine = mine.drop_duplicates(subset='member', keep='last')
        mine = mine.drop_duplicates(subset='manager_id', keep='last')
        return mine[self.MEMBER_MANAGER_COLS].astype({'manager_id': 'int64'})

    def _dynasty_week_years(self) -> dict[int, Any]:
        """Dynasty frames run one continuous week axis across every season, so
        each week has to be traced back to the season it falls in."""
        weeks: dict[int, Any] = {}
        week = 0
        for year in sorted(self.seasons):
            for _ in range(self.seasons[year].get('current_season_length', 0) + 1):
                weeks[week] = year
                week += 1
        return weeks

    def _attach_ids(self, long: pd.DataFrame, keep_teamless: bool = False) -> pd.DataFrame:
        """Resolve the member/week rows of a pivoted frame onto their dim ids.

        A member is the id of an account on one platform, so it reaches the person
        behind it through dim_manager_platform -- for the season the week falls
        in, since that is what settles the platform. manager_id and the
        denormalised manager_name both come from there.

        With keep_teamless, a member who did not play the season a week falls
        in still gets a row, carrying no team id. That is the dynasty case: a
        manager who has left keeps a rating -- it goes on regressing toward
        the mean, and the league average depends on it -- but they own no team
        in a season they were not in, so there is no team to point at. Their
        identity on the row is the manager id, which is what the dynasty facts
        are read back by.
        """
        member_teams = self._member_teams()
        teams = self._dim('team')
        if long.empty:
            return pd.DataFrame()
        if not keep_teamless and (member_teams.empty or teams.empty):
            return pd.DataFrame()

        # A member can only own one team per season, so collapse any historical
        # duplicates onto the newest id.
        teams = teams.sort_values('team_id').drop_duplicates(
            subset=['platform_team_id', 'league_year'], keep='last'
        )

        how = 'left' if keep_teamless else 'inner'
        keyed = long.merge(member_teams, on=['member', 'league_year'], how=how)
        keyed = keyed.merge(
            teams[['team_id', 'platform_team_id', 'league_year', 'online_league_id']],
            on=['platform_team_id', 'league_year'],
            how=how
        )
        fallback = (
            self._league_member_managers().set_index('member')
            if keep_teamless else pd.DataFrame()
        )
        if not fallback.empty:
            # A week falling in a season this member did not play came through the
            # left joins with no manager on it. Resolve it off the account alone:
            # a departed manager still holds one, they just own no team under it.
            for column in ('manager_id', 'manager_name'):
                keyed[column] = keyed[column].fillna(
                    keyed['member'].map(fallback[column])
                )
        # A member the accounts cannot place is not one of ours to publish.
        keyed = keyed.dropna(subset='manager_id')
        keyed['manager_id'] = keyed['manager_id'].astype('int64')
        keyed['league_id'] = self.league_id
        return keyed

    def _shape_frame(self, destination: str, long: pd.DataFrame) -> pd.DataFrame:
        spec = FACT_SPECS[destination]
        keep_teamless = spec.get('member_key') == 'manager_id'
        shaped = self._attach_ids(long, keep_teamless=keep_teamless).rename(
            columns={'rating': spec['value']}
        ).reindex(columns=spec['columns'])
        if keep_teamless and 'team_id' in shaped.columns:
            # A missing team has to reach the DB as a real NULL; left as NaN it
            # is a float and will not go into an integer column.
            shaped['team_id'] = shaped['team_id'].astype('object').where(
                shaped['team_id'].notna(), None
            )
        # manager_name is a denormalised copy of the account's display name, so
        # it takes the token that dim's push already minted -- anonymising here
        # would rewrite dim_manager_platform's map and repoint every one of its
        # tokens.
        if (tokens := self._fact_name_tokens()):
            shaped['manager_name'] = shaped['manager_name'].map(
                lambda name: tokens.get(name, name)
            )
        return shaped

    def _write_facts(self, destination: str, scope_id: int) -> int:
        spec = FACT_SPECS[destination]
        if self.current_frame.empty:
            # Nothing resolved onto the dims; leave whatever is already stored
            # rather than clearing the scope out from under it.
            return 0
        return replace_dataframe(
            self.conn,
            self.current_frame,
            spec['table'],
            spec['scope'],
            scope_id,
            self.schema
        )

    def _publish_dynasty_elo(self, frame: pd.DataFrame) -> None:
        long = score_pivot(frame)
        long['league_year'] = long['week'].map(self._dynasty_week_years())
        self.current_frame = self._shape_frame('dynasty_elo', long)
        self._write_facts('dynasty_elo', self.league_id)

    def _publish_indexed_frame(self, destination: str, num: int, frame: pd.DataFrame) -> None:
        if destination not in FACT_SPECS:
            raise KeyError('Unknown destination: {}'.format(destination))
        year = self._resolve_year(num)
        online_league_id = self._online_league_id(year)
        if online_league_id is None:
            # A season the config did not carry at sync time still needs its
            # dim_online_league row before the facts can point at it.
            online_league_id = self.add_league_year(year)
            self.push_dims('online_league')

        long = score_pivot(frame)
        long['league_year'] = year
        self.current_frame = self._shape_frame(destination, long)
        self._write_facts(destination, online_league_id)

    def publish(self, payload: dict[str, Any]) -> None:
        if (config := payload.get('config')) is not None:
            self.set_league_config(config)
        self.sync_dims()
        super().publish(payload)

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------

    def _load_post_proc(self, frame: pd.DataFrame, member_key: str = 'team_id') -> pd.DataFrame:
        """Fact rows carry surrogate ids; the frames want the member back, which
        is the account id held in dim_manager_platform.platform_user_id.

        Seasonal rows reach the manager through their season's team. Dynasty
        rows name the manager outright, because a departed manager's later
        weeks have no team to route through.
        """
        accounts = self._league_member_managers()
        if accounts.empty:
            return pd.DataFrame(columns=['member', 'week', 'rating'])

        if member_key == 'team_id':
            teams = self._dim('team')[['team_id', 'manager_id']].dropna()
            if teams.empty:
                return pd.DataFrame(columns=['member', 'week', 'rating'])
            teams = teams.astype({'team_id': 'int64', 'manager_id': 'int64'})
            frame = frame.merge(teams, on='team_id', how='inner')
        else:
            frame = frame.dropna(subset=member_key).astype({member_key: 'int64'})

        return frame.merge(
            accounts[['manager_id', 'member']],
            on='manager_id',
            how='inner'
        )[['member', 'week', 'rating']]

    def _load_scoped(self, destination: str, scope_id: int) -> pd.DataFrame | None:
        spec = FACT_SPECS[destination]
        member_key = spec.get('member_key', 'team_id')
        raw = pd.read_sql_query(
            LOAD_QUERIES[spec['value']].format(
                member_col=member_key,
                schema=self.schema,
                table=spec['table'],
                scope_col=spec['scope'],
                scope_id=scope_id,
            ),
            self.conn,
        )
        if raw.empty:
            return None
        long = self._load_post_proc(raw, member_key)
        if long.empty:
            return None
        return score_unpivot(long)

    def _load_dynasty(self) -> pd.DataFrame | None:
        if self.league_id < 0:
            return None
        return self._load_scoped('dynasty_elo', self.league_id)

    def _league_years(self) -> dict[Any, int]:
        """The seasons this league has on the DB side: year -> online league id."""
        online = self._dim('online_league')
        if online.empty:
            return dict()
        mine = online[online['league_id'] == self.league_id]
        return {
            int(year): int(online_league_id) for year, online_league_id
            in zip(mine['league_year'], mine['online_league_id'])
        }

    def _load_indexed_set(self, destination: str) -> dict[Any, pd.DataFrame]:
        # Unlike EloCSV, whose per-season key is whatever the filename carried,
        # the DB always knows the real season year -- so that is the key here
        # even under seasons_by='order'.
        frames: dict[Any, pd.DataFrame] = {}
        if self.league_id < 0:
            return frames
        for year, online_league_id in sorted(self._league_years().items()):
            loaded = self._load_scoped(destination, online_league_id)
            if loaded is not None:
                frames[year] = loaded
        return frames

    def load_frames(self, frame_set: str | list[str] | None = None) -> dict[str, Any]:
        loaders = {
            'dynasty_elo': self._load_dynasty,
            'seasonal_elo': lambda: self._load_indexed_set('seasonal_elo'),
            'roto_history': lambda: self._load_indexed_set('roto_history'),
        }
        if frame_set is None:
            frame_set = list(loaders.keys())
        elif isinstance(frame_set, str):
            frame_set = [frame_set]

        out: dict[str, Any] = {}
        for fs in frame_set:
            if fs not in loaders:
                raise KeyError('Unknown frame set: {}'.format(fs))
            loaded = loaders[fs]()
            # Omit sets with no rows in the DB so FrameManager.load_frames never
            # has to iterate a missing/None entry.
            if loaded is not None and (not isinstance(loaded, dict) or loaded):
                out[fs] = loaded
        return out
