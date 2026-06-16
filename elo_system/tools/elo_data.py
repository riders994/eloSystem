import pandas as pd
import psycopg2

from typing import Any
from pathlib import Path
from rv_pytools.sqltools import connect

from .basics import (
    DataBase,
    ELO_DIMS,
    ELO_COLS,
    LOAD_ELO,
    LOAD_ROTO,
    ROTO_COLS
)
from .helpers import (
    fstr_matcher,
    score_pivot,
    score_unpivot,
    upsert_dataframe,
    uri_to_dict,
    validate_conn_dict
)


class EloSQL(DataBase):

    def __init__(
            self,
            config: dict,
            connector: psycopg2.extensions.connection | None = None,
    ) -> None:
        super().__init__(
            config
        )

        if isinstance((conn_dict:= config.get('conn_dict')), dict):
            pass
        else:
            if isinstance((conn_uri := config.get('conn_uri')), str):
                conn_dict = uri_to_dict(conn_uri)
            else:
                raise KeyError('No connection details supplied.')
        if validate_conn_dict(conn_dict):
            self.conn_dict = conn_dict
        if connector is None:
            self.conn = connect(self.conn_dict)
        else:
            self.conn = connector

        self.schema = self.conn_dict.get('schema', config.get('schema', 'fantasy_sports'))
        self.load_dict = {
            'schema': self.schema,
            'year_end': ''
        }
        self.dim_tables: dict[str, pd.DataFrame] = {}
        self.reset_dims()

        self.curr_league_config: dict[str, Any] = dict()

        self.current_frame = pd.DataFrame()

    def _pull_dim(self, dim: str, overwrite: bool) -> bool:
        if not overwrite:
            if dim in self.dim_tables:
                return True
        # read_sql_table requires a SQLAlchemy connectable; self.conn is a raw
        # psycopg2 connection, so query explicitly like the load methods do.
        self.dim_tables.update({dim: pd.read_sql_query(
            f'SELECT * FROM {self.schema}.dim_{dim}', self.conn, index_col=f'{dim}_id'
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

    def _elo_publish_prep(self) -> None:
        dim_on = ['platform_team_id', 'league_year']
        # manager_id / team_id are the numeric indexes of their dim tables;
        # reset them to columns so the on= merges resolve and both ids survive
        # into the final ELO_COLS selection. (Stored dims keep their index.)
        deduped_man = self.dim_tables['manager'].reset_index().sort_values('manager_id').drop_duplicates(subset='discord_id', keep='last')
        deduped_man_teams = self.dim_tables['team'].reset_index().sort_values('team_id').drop_duplicates(subset=dim_on, keep='last').merge(
            deduped_man,
            on='manager_id',
            how='inner'
        ).rename(columns={'player_name': 'manager_name'})

        d = self.curr_league_config['is_dynasty']
        self.current_frame['is_dynasty'] = d
        if d:
            self._set_dynasty_season()

        # Inner join on the two columns with different names
        self.current_frame = self.current_frame.merge(
            deduped_man_teams,
            on=dim_on,
            how='inner'
        )[ELO_COLS]

    def _set_dynasty_season(self) -> pd.DataFrame:
        seasons = self.curr_league_config['seasons']
        seas_col = list()
        for year, season in seasons.items():
            csl = season['current_season_length'] + 1
            seas_col += [year] * csl
        self.current_frame['league_year'] = self.current_frame['week'].map({i: v for i, v in enumerate(seas_col)})

    def _roto_frame_prep(self):
        self.current_frame.rename(columns={'rating': 'score'}, inplace=True)

        self.current_frame = self.current_frame[ROTO_COLS]

    def _publish_dynasty_elo(self, frame: pd.DataFrame) -> None:
        self.current_frame = score_pivot(frame).rename(columns={'rating': 'elo', 'member': 'platform_team_id'})
        self._elo_publish_prep()
        cols = list(self.current_frame.columns)
        cols.pop()
        upsert_dataframe(
            self.conn,
            self.current_frame,
            'fact_elos',
            cols,
            self.schema
        )

    def _publish_indexed_frame(self, destination: str, num: int, frame: pd.DataFrame) -> None:
        self.current_frame = score_pivot(frame)
        self.current_frame['league_year'] = num
        if destination == 'seasonal_elo':
            self._elo_publish_prep()

            table = destination.split('_')[1]
        elif destination == 'roto_history':
            self._roto_frame_prep()

            table = destination.split('_')[0]
        else:
            raise KeyError('Unknown destination: {}'.format(destination))
        cols = list(self.current_frame.columns)
        cols.pop()
        upsert_dataframe(
            self.conn,
            self.current_frame,
            f'fact_{table}s',
            cols,
            self.schema
        )

    def _load_post_proc(self, frame: pd.DataFrame) -> pd.DataFrame:
        # team_id is the numeric index of dim_tables['team'], so join the
        # frame's team_id column against that index rather than on='team_id'.
        return frame.merge(
            self.dim_tables['team'],
            how='inner',
            left_on='team_id',
            right_index=True,
        ).rename(columns={'platform_team_id': 'member'})[['member', 'week', 'rating']]

    def _load_dynasty(self, league_id: int) -> pd.DataFrame | None:
        self.load_dict.update({
            'is_dynasty': 'TRUE',
            'league_id': league_id
        })
        dynasty_df = pd.read_sql_query(
            LOAD_ELO.format(**self.load_dict),
            self.conn,
        )
        return score_unpivot(self._load_post_proc(dynasty_df))

    def _lookup_league_years(self, league_id: int) -> set[int]:
        dim = self.dim_tables['league']
        mask = dim['league_id'] == league_id
        return set(dim['league_year'][mask])

    def _load_indexed_set(self, league_id: int, destination: str) -> dict[Any, pd.DataFrame]:
        # Recovers the per-season key embedded in each filename. Under the
        # default seasons_by='year' that key is the season year; under
        # 'order' it is the ordinal the file was written with.
        frames: dict[Any, pd.DataFrame] = {}
        years = self._lookup_league_years(league_id)
        self.load_dict.update({
            'is_dynasty': 'FALSE',
            'league_id': league_id
        })
        if destination == 'seasonal_elo':
            query = LOAD_ELO
        elif destination == 'roto_history':
            query = LOAD_ROTO

        for year in years:
            year_end = f'AND league_year = {year}'
            self.load_dict.update({'year_end': year_end})
            frame = pd.read_sql_query(
                query.format(**self.load_dict),
                self.conn,
            )
            frames[year] = score_unpivot(self._load_post_proc(frame))
        return frames

    def _lookup_league_id(self, platform_id: str) -> int:
        dim = self.dim_tables['league']
        mask = dim['platform_league_id'] == platform_id
        return dim['league_id'][mask].iloc[0]

    def load_frames(self, platform_id: str, frame_set: str | list[str] | None = None) -> dict[str, Any]:
        loaders = {
            'dynasty_elo': self._load_dynasty,
            'seasonal_elo': self._load_indexed_set,
            'roto_history': self._load_indexed_set,
        }
        if frame_set is None:
            frame_set = list(loaders.keys())
        elif isinstance(frame_set, str):
            frame_set = [frame_set]

        league_id = self._lookup_league_id(platform_id)

        out: dict[str, Any] = {}
        for fs in frame_set:
            if fs not in loaders:
                raise KeyError('Unknown frame set: {}'.format(fs))
            loaded = loaders[fs](league_id)
            # Omit sets with no data on disk so FrameManager.load_frames never
            # has to iterate a missing/None entry.
            if loaded is not None and (not isinstance(loaded, dict) or loaded):
                out[fs] = loaded
        return out

    def publish(self, payload: dict[str, Any]) -> None:
        self.curr_league_config = payload['config']
        super().publish(payload)


class EloCSV(DataBase):
    def __init__(
            self, config: dict
            , working_directory: Path
    ) -> None:
        super().__init__(
            config
        )
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
