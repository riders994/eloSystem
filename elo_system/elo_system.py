import re
from pathlib import Path
from typing import Any


import pandas as pd

from .tools.basics import week_formatter, EloBase, load_config_file, write_config_file, str_to_path
from .tools import (
    League,
    FantraxLeague,
    fantrax_formatter,
    FrameManager,
    nba_calculator,
    nfl_calculator
)

# FANTRAX_LC = 'fantrax_lc.yml'
# SLEEPER_LC = 'sleeper_lc.yml'
#
# LOCATION = 'resources'
#
# CONFIG_DIR = 'league_configs'
#
# ELO_DIR = 'elos'
#
# FANTRAX_IDS = {
#     2024: 'blk3bn3clw9njuhc',
#     2025: 'wserh14rmbbpqtcg',
# }
#
# SLEEPER_IDS = [
#     '',
#     '',
# ]

CONFIGS = {
    'sql', 'csv', 'elo', 'league',
}

# Default locations used when EloSystem is constructed without a config path
# (bootstrap mode): the directory skeleton is created relative to the CWD.
DEFAULT_RESOURCES_DIR = 'resources'
DEFAULT_CONFIGS_DIR = 'configs'
DEFAULT_SYS_CONFIG = 'sys_config.yml'




class EloLeague(EloBase):
    
    def __init__(self, config: dict | None = None) -> None:
        self.leagues = dict()
        self.seasons = dict()

        self.current_league = None

        self.current_season = None
        self.is_dynasty = False
        self.is_roto = False
        self.platform = None
        self.league_type = None

        self.season_stats = {
            'playoff_start': dict(),
            'season_length': dict()
        }

        self.calculator = None
        self.formatter = None
        self.frame_manager = None

        super().__init__(config)

    def _load(self) -> None:
        super()._load()
        self.league_type: str = self.config['league_type']
        self.platform: str = self.config['platform']

        self.current_season: int | None = self.config.get('current_season')
        self.is_dynasty: bool = self.config.get('is_dynasty', False)
        self.is_roto: bool = self.config.get('is_roto', False)
        self.seasons.update(self.config.get('seasons', dict()))
        self.osa_factor: float = self.config.get('osa_factor', .4)
        self.k: int = self.config.get('k', 60)
        self.extras = int(self.is_roto) + int(self.is_dynasty)

    def _dump(self) -> None:
        super()._dump()
        self.config.update({
            'current_season': self.current_season,
            'is_dynasty': self.is_dynasty,
            'seasons': self.seasons,
            'is_roto': self.is_roto,
            'osa_factor': self.osa_factor,
            'k': self.k
        })

    @staticmethod
    def _validate_fantrax(seas_dict: dict[str, Any]) -> bool:
        return seas_dict.get('league_id') is not None

    def _validate_season(self, seas_dict: dict[str, Any]) -> bool:
        if self.platform == 'fantrax':
            return self._validate_fantrax(seas_dict)
        return False

    def add_season(self, seas_dict: dict[str, Any], year: int, league: bool = False) -> bool:
        if self._validate_season(seas_dict):
            if self.platform == 'fantrax':
                self.seasons.update({year: seas_dict})

            if league:
                self.add_league(year)
            return True
        return False

    def _find_season(self, sid: str) -> int:
        for y, s in self.seasons.items():
            if s['league_id'] == sid:
                return y
        return 0

    def remove_season(self, year: int | None = None, league_id: str | None = None) -> dict[str, Any]:
        if year is None:
            if league_id is None:
                raise ValueError
            else:
                year = self._find_season(league_id)
                if year == 0:
                    raise ValueError
        if year not in self.seasons:
            raise KeyError
        self.remove_league(year)
        return self.seasons.pop(year)

    def _set_current_league(self):
        if self.leagues.get(self.current_season) is None:
            self.add_league(self.current_season)
        self.current_league = self.leagues[self.current_season]
        self.current_league.load()

    def set_current_season(self, year: int | None = None) -> int | None:
        if year is None:
            self.reset_current_season()
        else:
            self.current_season = year
        self._set_current_league()
        return self.current_season

    def reset_current_season(self) -> int | None:
        try:
            self.current_season = max(list(self.seasons.keys()))
        except ValueError as e:
            if 'empty' not in str(e):
                raise e
        self._set_current_league()
        self.current_league = self.leagues.get(self.current_season)
        if isinstance(self.current_league, League):
            self.current_league.load()

        return self.current_season

    def compile_season_stats(self) -> dict[str, Any]:
        pos = dict()
        sl = dict()
        for y, seas in self.seasons.items():
            pos.update({y: seas['playoff_start']})
            sl.update({y: seas['season_length']})
        self.season_stats['playoff_start'].update(pos)
        self.season_stats['season_length'].update(sl)
        return self.season_stats

    def add_league(self, league_year: int, overwrite: bool = False) -> None:
        if overwrite or self.leagues.get(league_year) is None:
            if self.seasons.get(league_year) is not None:
                l = FantraxLeague(league_year, self.seasons)
                l.scrape()
                self.leagues.update({league_year: l})
            else:
                raise KeyError

    def remove_league(self, league_year: str | int) -> None:
        if isinstance(league_year, int):
            self.leagues.pop(league_year, None)
        elif isinstance(league_year, str):
            for k, v in self.seasons:
                if v['league_id'] == league_year:
                    self.leagues.pop(k, None)

    def _set_calculator(self) -> None:
        if self.league_type == 'nba':
            self.calculator = nba_calculator
        elif self.league_type == 'nfl':
            self.calculator = nfl_calculator
        else:
            raise ValueError('Unknown league type: {}'.format(self.league_type))

    def _set_formatter(self) -> None:
        if self.platform == 'sleeper':
            pass
        elif self.platform == 'fantrax':
            self.formatter = fantrax_formatter

    def _set_frame_manager(self) -> None:
        if not isinstance(self.frame_manager, FrameManager):
            self.frame_manager = FrameManager(self.config)

    def _set_dynasty_start_week(self, year: int | list[int] | None = None):
        start_season = min(self.seasons.keys())
        if year is None:
            year = range(start_season, start_season  + len(self.seasons.keys()))
        if isinstance(year, int):
            s = self.seasons[year]
            w = 0
            if year != start_season:
                for y in range(start_season, year):
                    w += self.seasons[y]['current_season_length']
                    w += 1
            s.update({'dynasty_start_week': w})
        else:
            for y in year:
                self._set_dynasty_start_week(y)


    def _change_to_dynasty(self):
        if self.frame_manager.can_dynasty():
            self.frame_manager.set_is_dynasty(True)
            for s in self.seasons.keys():
                self.add_league(s)
                if not self.frame_manager.validate_season(s):
                    self.run_season(s)
            self._set_dynasty_start_week()
            self.is_dynasty = True
            self.run_dynasty()

    def change_dynasty(self, to: bool | None = None, delete: bool = False) -> bool:
        if isinstance(to, bool):
            if to == self.is_dynasty:
                return self.is_dynasty
        else:
            to = not self.is_dynasty
        if to:
            self._change_to_dynasty()
            return self.is_dynasty
        else:
            self.is_dynasty = False
            if delete:
                pass
        return self.is_dynasty

    def run_prep(self, year: int | None = None):
        if year is None:
            year = self.current_sports_year
        self.add_league(year)
        self.set_current_season(year)
        self._set_formatter()
        self._set_frame_manager()
        self._set_calculator()

    def _return_frames(self, year: int) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame] | tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
        if self.extras == 2:
            return self.frame_manager.seasonal_elo[year], self.frame_manager.dynasty_elo, self.frame_manager.roto_history[year]
        elif self.extras == 1:
            if self.is_dynasty:
                return self.frame_manager.seasonal_elo[year], self.frame_manager.dynasty_elo
            elif self.is_roto:
                return self.frame_manager.seasonal_elo[year], self.frame_manager.roto_history[year]
            return None
        else:
            return self.frame_manager.seasonal_elo[year]

    def _rename(self, scoreboard: pd.DataFrame, season: int) -> pd.Series:
        id_map = {v['team_id']: k for k, v in self.seasons[season]['league_members'].items()}
        return scoreboard['opponent'].map(id_map)

    def _run_one(self, week: int, year: int, overwrite: bool = False) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame] | tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
        if week == 0:
            self.frame_manager.generate(year, overwrite)
        else:
            formatted_scores = self.formatter(self.league_type, self.current_league.get_week(week))
            formatted_scores['opponent'] = self._rename(formatted_scores, year)
            if self.is_dynasty:
                dynasty_week = week + self.seasons[year]['dynasty_start_week']
                try:
                    self.calculator(
                        self.frame_manager.dynasty_elo,
                        formatted_scores,
                        dynasty_week,
                        overwrite,
                    )
                except AttributeError:
                    raise KeyError('No Dynasty frame initialized')
            else:
                try:
                    self.calculator(
                        self.frame_manager.seasonal_elo[year],
                        formatted_scores,
                        week,
                        overwrite,
                    )
                except KeyError as e:
                    if e.args[0] == self.current_sports_year:
                        raise KeyError('Current sports year has no frames')
        return self._return_frames(year)

    def _run_multiple(self, weeks: str, year: int, overwrite: bool = False) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame] | tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
        formed_weeks = week_formatter(weeks)
        if isinstance(formed_weeks, int):
            self._run_one(formed_weeks, year, overwrite)
        elif isinstance(formed_weeks, range):
            for week in formed_weeks:
                self._run_one(week, year, overwrite)
        else:
            raise ValueError
        return self._return_frames(year)

    def run_dynasty(self, overwrite: bool = False):
        for s in self.seasons.keys():
            self.run_season(s)

    def run_season(self, year: int | None = None, overwrite: bool = False, ):
        if year is None:
            year = self.current_sports_year
        self.run_prep(year)
        weeks = '0:{}'.format(self.seasons[year]['current_season_length'])
        self._run_multiple(weeks, year, overwrite)

    def publish(self) -> dict[str, Any]:
        payload = self.frame_manager.publish()
        payload.update({'config': self.config})

        return payload

    def load_frames(self, frames: dict[str, dict]) -> None:
        self.frame_manager.load_frames(frames)

    def run(self, week: int | str, year: int | None = None, overwrite: bool = False, ):
        if year is None:
            year = self.current_sports_year

        if isinstance(week, str):
            return self._run_multiple(week, year, overwrite)
        else:
            return self._run_one(week, year, overwrite)


class EloData(EloBase):

    def __init__(
            self, config: dict
    ) -> None:
        super().__init__(config)

        self.seasons_by = config.get('seasons_by', 'year')
        self.dynasty_fstr = config.get('dynasty_fstr', 'dynasty_elo{ext}')
        self.elo_fstr = config.get('elo_fstr', '{num}_season_elo{ext}')
        self.roto_fstr = config.get('roto_fstr', '{num}_roto_elo{ext}')

    def _publish_dynasty_elo(self, frame: pd.DataFrame) -> None:
        pass

    def _publish_seasonal_elo(self, num:int , frame: pd.DataFrame) -> None:
        pass

    def _publish_seasonal_elos(self, frames: dict[int, pd.DataFrame]):
        sorted_keys = sorted(frames)
        ranks = {k: i for i, k in enumerate(sorted_keys)}
        for k, v in frames.items():
            if self.seasons_by == 'year':
                self._publish_seasonal_elo(k, v)
            elif self.seasons_by == 'order':
                self._publish_seasonal_elo(ranks[k], v)

    def _publish_roto(self, num: int, frame: pd.DataFrame) -> None:
        pass

    def _publish_roto_history(self, frames: dict[str, pd.DataFrame]):
        sorted_keys = sorted(frames)
        ranks = {k: i for i, k in enumerate(sorted_keys)}
        for k, v in frames.items():
            if self.seasons_by == 'year':
                self._publish_roto(k, v)
            elif self.seasons_by == 'order':
                self._publish_roto(ranks[k], v)

    def publish(self, payload: dict[str, Any]) -> None:
        if (delo := payload.get('dynasty_elo')) is not None:
            self._publish_dynasty_elo(delo)
        if (selo := payload.get('seasonal_elo')) is not None:
            self._publish_seasonal_elos(selo)
        if (roto := payload.get('roto_history')) is not None:
            self._publish_roto_history(roto)


class EloSQL(EloData):
    pass


class EloCSV(EloData):
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

    def _publish_seasonal_elo(self, num: int, frame: pd.DataFrame) -> None:
        file_path = Path(self.out_dir, self.elo_fstr.format(ext=self.extension, num=num))
        frame.to_csv(file_path, index=True)

    def _publish_roto(self, num: int, frame: pd.DataFrame) -> None:
        file_path = Path(self.out_dir, self.roto_fstr.format(ext=self.extension, num=num))
        frame.to_csv(file_path, index=True)

    @staticmethod
    def _fstr_matcher(fstr: str, ext: str) -> tuple[str, re.Pattern]:
        """Turn a filename format string into a glob pattern and a regex that
        captures the `{num}` field, so written files can be discovered and
        their season key recovered on load."""
        glob = fstr.format(num='*', ext=ext)
        pattern = (
            re.escape(fstr)
            .replace(re.escape('{num}'), r'(?P<num>.+?)')
            .replace(re.escape('{ext}'), re.escape(ext))
        )
        return glob, re.compile('^' + pattern + '$')

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
        glob, matcher = self._fstr_matcher(fstr, self.extension)
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

class EloSystem(EloBase):

    def __init__(self, config_path: str | None = None):
        if config_path is None:
            # Bootstrap mode: no config supplied. Create the resource/config
            # directory skeleton and start from whatever sys config exists
            # there (empty config if none yet). The ratings (output) directory
            # is created later by EloCSV once write_loc is known.
            self.resources_dir = str_to_path(DEFAULT_RESOURCES_DIR)
            self.configs_dir = self.resources_dir / DEFAULT_CONFIGS_DIR
            for directory in (self.resources_dir, self.configs_dir):
                directory.mkdir(parents=True, exist_ok=True)
            self.pathed_config = self.configs_dir / DEFAULT_SYS_CONFIG
            config = load_config_file(self.pathed_config) if self.pathed_config.exists() else dict()
        else:
            # A path was supplied: it must point to a valid config file.
            # load_config_file raises if the path is invalid/missing.
            self.pathed_config = str_to_path(config_path)
            config = load_config_file(self.pathed_config)
            self.configs_dir = self.pathed_config.parent
            self.resources_dir = self.configs_dir.parent

        super().__init__(config)

        self.csv_config_loc = self.config.get('csv_config_name', 'csv_config.yml')
        self.elo_league_config_loc = self.config.get('elo_league_config_name', 'elo_config.yml')
        self.sql_config_loc = self.config.get('sql_config_name', 'sql_config.yml')

        self.csv_config = dict()
        self.elo_league_config = dict()
        self.sql_config = dict()

        self.elo_league = None
        self.elo_csv = None
        self.elo_sql = None

        self.reader = None
        self.writer = None

    def _assign_rw(self):
        rw = {'sql': self.elo_sql, 'csv': self.elo_csv}

        self.reader = rw[self.config['reader']]
        self.writer = rw[self.config['writer']]

    @staticmethod
    def _validate_sql_config(config: dict) -> bool:

        return True

    def read_sql_config(self, config: dict | None) -> None:
        if config is None:
            config = load_config_file(Path(self.configs_dir, self.sql_config_loc))
        if self._validate_sql_config(config):
            self.sql_config = config
            # self.elo_sql = EloSQL(self.sql_config)
            self._assign_rw()

    @staticmethod
    def _validate_csv_config(config: dict) -> bool:
        if config.get('write_loc') is None:
            return False
        return True

    def read_csv_config(self, config: dict | None) -> None:
        if config is None:
            config = load_config_file(Path(self.configs_dir, self.csv_config_loc))
        if self._validate_csv_config(config):
            self.csv_config = config
            self.elo_csv = EloCSV(self.csv_config, self.configs_dir.parent)
            self._assign_rw()

    @staticmethod
    def _validate_league_config(config: dict) -> bool:
        if config.get('platform') is None:
            return False
        if config.get('league_type') is None:
            return False
        if config.get('current_sports_year') is None:
            return False
        return True

    def read_league_config(self, config: dict | None) -> None:
        if config is None:
            config = load_config_file(Path(self.configs_dir, self.elo_league_config_loc))
        if self._validate_league_config(config):
            self.elo_league_config = config
            self.elo_league = EloLeague(self.elo_league_config)


    def _load_configs(self, configs: dict) -> bool:
        for k, v in configs.items():
            if k not in CONFIGS:
                raise KeyError(k)
            if k == 'sql':
                self.read_sql_config(v)
            elif k == 'csv':
                self.read_csv_config(v)
            elif k == 'league':
                self.read_league_config(v)
        return True

    def load_configs(self, configs: dict | None = None, sql_config: dict | None = None, csv_config: dict | None = None, league_config: dict | None = None) -> bool:
        if isinstance(configs, dict):
            return self._load_configs(configs)
        else:
            self.read_csv_config(csv_config)
            self.read_sql_config(sql_config)
            self.read_league_config(league_config)

        return True

    def write_configs(self, which: str | list[str]) -> None:
        if isinstance(which, list):
            for i in which:
                self.write_configs(i)
        else:
            if which == 'sys':
                write_config_file(self.pathed_config, self.config)
            elif which == 'csv':
                write_config_file(Path(self.configs_dir, self.csv_config_loc), self.csv_config)
            elif which == 'sql':
                write_config_file(Path(self.configs_dir, self.sql_config_loc), self.sql_config)
            elif which == 'league':
                write_config_file(Path(self.configs_dir, self.elo_league_config_loc), self.elo_league_config)


    def dump(self) -> dict[str, Any]:
        res = {'sys': super().dump()}
        if self.elo_league_config is not None:
            if len(self.elo_league_config):
                res.update({'league': self.elo_league_config})
        if self.csv_config is not None:
            if len(self.csv_config):
                res.update({'csv': self.csv_config})
        if self.sql_config is not None:
            if len(self.sql_config):
                res.update({'sql': self.sql_config})
        self.write_configs(list(res.keys()))

        return res

    def publish(self):
        payload = self.elo_league.publish()
        self.writer.publish(payload)

    def load_frames(self, frame_set: str | list[str] | None) -> None:
        frames = self.reader.load_frames(frame_set)
        self.elo_league.load_frames(frames)


if __name__ == '__main__':
    sys_config_path = './resources/configs/sys_config.yml'
    ftc24 = {
        'league_id': 'blk3bn3clw9njuhc'
    }
    ftc25 = {
        'league_id': 'wserh14rmbbpqtcg'
    }

    sys = EloSystem(sys_config_path)
    sys.load_configs()
    mmm = sys.elo_league
    mmm.load()
    mmm.add_season(ftc24, 2024, True)
    mmm.add_season(ftc25, 2025, True)
    mmm.add_league(2025)
    mmm.add_league(2024)
    mmm.dump()
    mmm.run_prep(2025)
    mmm.run_prep(2024)
    mmm.run_season(2025)
    mmm.run_season(2024)

    mmm.dump()

    mmm.change_dynasty(True)

    sys.publish()
    print('done')
