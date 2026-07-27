import pandas as pd
import psycopg2

from typing import Any
from pathlib import Path
from rv_pytools.sqltools import connect

from .basics import (
    DataBase,
    bigint_generator,
    id_generator,
    ELO_DIMS,
    FACT_SPECS,
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
        # Ensure the ratings (output) directory exists before any publish.
        self.out_dir = Path(self.wd, self.write_loc)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        # Input directory for load_frames (defaults to the output directory).
        self.in_dir = Path(self.wd, self.read_loc)

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
        return pd.read_csv(file_path, index_col=0)

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

    The frames are indexed by league member -- the platform owner account name
    -- while the schema keys off surrogate ids. ``league_members`` in the league
    config bridges the two: it maps each member to the platform team id that
    identifies their ``dim_team`` row for a season, and each member is also a
    ``dim_manager`` row under ``player_name``, which is what the load path
    reads the index back out of.
    """

    def __init__(
            self,
            config: dict,
            league_config: dict | None = None,
            connector: psycopg2.extensions.connection | None = None,
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
        if connector is None:
            self.conn = connect(self.conn_dict)
        else:
            self.conn = connector

        self.schema = self.conn_dict.get('schema', config.get('schema', 'fantasy_sports'))
        self.dim_tables: dict[str, pd.DataFrame] = {}
        self.reset_dims()

        self.league_config: dict[str, Any] = {}
        self.seasons: dict[Any, Any] = {}
        self.platform = None
        self.current_sports_year = None
        self.league_id = -1
        self.league_name = None
        self.set_league_config(league_config)

        self.current_frame = pd.DataFrame()

    # ------------------------------------------------------------------
    # dimension tables
    # ------------------------------------------------------------------

    @staticmethod
    def _dim_table(dim: str) -> str:
        return 'dim_{}'.format(dim)

    @staticmethod
    def _dim_key(dim: str) -> str:
        return '{}_id'.format(dim)

    def _dim(self, dim: str) -> pd.DataFrame:
        """The cached dim table with its surrogate id back as a column."""
        return self.dim_tables[self._dim_table(dim)].reset_index()

    def _pull_dim(self, dim: str, overwrite: bool) -> bool:
        table = self._dim_table(dim)
        if not overwrite:
            if table in self.dim_tables:
                return True
        # read_sql_table requires a SQLAlchemy connectable; self.conn is a raw
        # psycopg2 connection, so query explicitly like the load methods do.
        self.dim_tables.update({table: pd.read_sql_query(
            f'SELECT * FROM {self.schema}.{table}', self.conn, index_col=self._dim_key(dim)
        )})
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
        frame = self.dim_tables[self._dim_table(dim)]
        if frame.empty:
            return True
        upsert_dataframe(
            self.conn,
            frame.reset_index(),
            self._dim_table(dim),
            [self._dim_key(dim)],
            self.schema
        )
        return True

    def push_dims(self, which: str | set[str] | None = None) -> bool:
        if isinstance(which, str):
            return self._push_dim(which)
        else:
            if which is None:
                which = ELO_DIMS
            for each in which:
                self._push_dim(each)
            return True

    def _next_dim_id(self, dim: str) -> int:
        # The dim tables carry no sequence defaults, so surrogate ids are minted
        # here off whatever the cached table already holds.
        index = self.dim_tables[self._dim_table(dim)].index
        if len(index) == 0:
            return 0
        return int(index.max()) + 1

    def _append_dim(self, dim: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        table = self._dim_table(dim)
        existing = self.dim_tables[table]
        new = pd.DataFrame.from_records(rows).set_index(self._dim_key(dim))
        combined = new if existing.empty else pd.concat([existing, new])
        # Staged rows may omit nullable columns; keep the table's own column
        # order so the eventual insert lines up with it.
        self.dim_tables[table] = combined.reindex(columns=existing.columns)

    # ------------------------------------------------------------------
    # league config
    # ------------------------------------------------------------------

    def set_league_config(self, league_config: dict[str, Any] | None) -> int:
        """Adopt an EloLeague config and resolve which dim_league row it is.

        publish() calls this again with the config off the payload, so seasons
        added since construction are picked up before anything is written.
        """
        self.league_config = league_config or dict()
        self.seasons = self.league_config.get('seasons', dict())
        self.platform = self.league_config.get('platform')
        self.current_sports_year = self.league_config.get('current_sports_year')
        return self._resolve_league_id()

    def _platform_league_ids(self) -> set[str]:
        return {s['league_id'] for s in self.seasons.values() if s.get('league_id')}

    def _lookup_league_id(self) -> int:
        """Find the dim_league row behind this config by way of any season's
        platform league id. -1 when the league is not in the DB yet."""
        online = self._dim('online_league')
        if online.empty:
            return -1
        known = online[online['platform_league_id'].isin(self._platform_league_ids())]
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

    def _ensure_league(self) -> int:
        if self.league_id >= 0:
            return self.league_id
        self.league_id = self._next_dim_id('league')
        self.league_name = self.league_config.get('league_name', id_generator())
        self._append_dim('league', [{
            'league_id': self.league_id,
            'discord_server_id': self.league_config.get('discord_server_id', bigint_generator()),
            'platform': self.platform,
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

    def _ensure_managers(self) -> dict[str, int]:
        """One dim_manager row per league member, stored under the platform
        owner name the frames are indexed by."""
        managers = self._dim('manager')
        by_name: dict[str, int] = {}
        if not managers.empty:
            by_name.update({
                name: int(mid) for name, mid
                in zip(managers['player_name'], managers['manager_id'])
            })

        rows = []
        next_id = self._next_dim_id('manager')
        for year in sorted(self.seasons):
            for member, info in self._members(year).items():
                if member in by_name:
                    continue
                by_name[member] = next_id
                rows.append({
                    'manager_id': next_id,
                    'player_name': member,
                    'display_name': info.get('short_name', member),
                    'discord_id': None,
                    'is_comanager': False,
                })
                next_id += 1
        self._append_dim('manager', rows)
        return by_name

    def _ensure_teams(self, online_league_ids: dict[Any, int], manager_ids: dict[str, int]) -> None:
        """One dim_team row per (season, platform team id)."""
        teams = self._dim('team')
        known = set()
        if not teams.empty:
            known.update(zip(teams['online_league_id'], teams['platform_team_id']))

        rows = []
        next_id = self._next_dim_id('team')
        for year in sorted(self.seasons):
            online_league_id = online_league_ids[year]
            for member, info in self._members(year).items():
                platform_team_id = str(info.get('team_id'))
                if (online_league_id, platform_team_id) in known:
                    continue
                known.add((online_league_id, platform_team_id))
                rows.append({
                    'team_id': next_id,
                    'team_name': info.get('curr_name'),
                    'manager_id': manager_ids[member],
                    'online_league_id': online_league_id,
                    'platform_team_id': platform_team_id,
                    'league_year': year,
                    'is_commish': info.get('is_commish', False),
                })
                next_id += 1
        self._append_dim('team', rows)

    def sync_dims(self) -> None:
        """Create whatever dim rows the league config implies, then push them so
        the fact-table foreign keys have something to resolve against."""
        self._ensure_league()
        online_league_ids = self._ensure_online_leagues()
        manager_ids = self._ensure_managers()
        self._ensure_teams(online_league_ids, manager_ids)
        self.push_dims()

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

    def _member_teams(self) -> pd.DataFrame:
        """member -> platform team id, per season, out of league_members."""
        rows = [
            {
                'member': member,
                'league_year': year,
                'platform_team_id': str(info.get('team_id')),
            }
            for year in self.seasons
            for member, info in self._members(year).items()
        ]
        return pd.DataFrame.from_records(
            rows, columns=['member', 'league_year', 'platform_team_id']
        )

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

    def _attach_ids(self, long: pd.DataFrame) -> pd.DataFrame:
        """Resolve the member/week rows of a pivoted frame onto their dim ids."""
        member_teams = self._member_teams()
        teams = self._dim('team')
        managers = self._dim('manager')
        if long.empty or member_teams.empty or teams.empty or managers.empty:
            return pd.DataFrame()

        # A member can only own one team per season and a manager only holds one
        # dim row, so collapse any historical duplicates onto the newest id.
        teams = teams.sort_values('team_id').drop_duplicates(
            subset=['platform_team_id', 'league_year'], keep='last'
        )
        managers = managers.sort_values('manager_id').drop_duplicates(
            subset='player_name', keep='last'
        ).rename(columns={'player_name': 'manager_name'})

        keyed = long.merge(member_teams, on=['member', 'league_year'], how='inner')
        keyed = keyed.merge(
            teams[['team_id', 'platform_team_id', 'league_year', 'manager_id', 'online_league_id']],
            on=['platform_team_id', 'league_year'],
            how='inner'
        )
        keyed = keyed.merge(managers[['manager_id', 'manager_name']], on='manager_id', how='inner')
        keyed['league_id'] = self.league_id
        return keyed

    def _shape_frame(self, destination: str, long: pd.DataFrame) -> pd.DataFrame:
        spec = FACT_SPECS[destination]
        return self._attach_ids(long).rename(
            columns={'rating': spec['value']}
        ).reindex(columns=spec['columns'])

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

    def _load_post_proc(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Fact rows carry surrogate team ids; the frames want the member back,
        which is the manager's platform name over in dim_manager."""
        teams = self._dim('team')[['team_id', 'manager_id']].dropna()
        managers = self._dim('manager')[['manager_id', 'player_name']].dropna(subset='manager_id')
        if teams.empty or managers.empty:
            return pd.DataFrame(columns=['member', 'week', 'rating'])

        teams = teams.astype({'team_id': 'int64', 'manager_id': 'int64'})
        managers = managers.astype({'manager_id': 'int64'})
        return frame.merge(
            teams,
            on='team_id',
            how='inner'
        ).merge(
            managers,
            on='manager_id',
            how='inner'
        ).rename(columns={'player_name': 'member'})[['member', 'week', 'rating']]

    def _load_scoped(self, destination: str, scope_id: int) -> pd.DataFrame | None:
        spec = FACT_SPECS[destination]
        raw = pd.read_sql_query(
            LOAD_QUERIES[spec['value']].format(
                schema=self.schema,
                table=spec['table'],
                scope_col=spec['scope'],
                scope_id=scope_id,
            ),
            self.conn,
        )
        if raw.empty:
            return None
        long = self._load_post_proc(raw)
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
