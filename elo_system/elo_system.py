import psycopg2

from typing import Any
from pathlib import Path

from .tools import EloLeague, EloCSV, EloSQL
from .tools.basics import load_config_file, write_config_file, str_to_path

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





class EloSystem:

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


        self.reader_key = config.get('reader', 'csv')
        self.writer_key = config.get('writer', 'csv')
        self.csv_config_loc = config.get('csv_config_name', 'csv_config.yml')
        self.elo_league_config_loc = config.get('elo_league_config_name', 'elo_config.yml')
        self.sql_config_loc = config.get('sql_config_name', 'sql_config.yml')

        self.csv_config = dict()
        self.elo_league_config = dict()
        self.sql_config = dict()

        self.reader = None
        self.writer = None
        self.elo_league = None
        self.elo_csv = None
        self.elo_sql = None


    def _assign_rw(self):
        rw = {'sql': self.elo_sql, 'csv': self.elo_csv}

        self.reader = rw[self.reader_key]
        self.writer = rw[self.writer_key]

    def toggle_reader(self):
        if isinstance(self.reader, EloCSV):
            if self.elo_sql is not None:
                self.reader = self.elo_sql
            else:
                raise KeyError('No SQL reader available')
        if isinstance(self.reader, EloSQL):
            if self.elo_league is not None:
                self.reader = self.elo_league
            else:
                raise KeyError('No CSV reader available')

    def toggle_writer(self):
        if isinstance(self.writer, EloCSV):
            if self.elo_sql is not None:
                self.writer = self.elo_sql
            else:
                raise KeyError('No SQL writer available')
        if isinstance(self.writer, EloSQL):
            if self.elo_league is not None:
                self.writer = self.elo_league
            else:
                raise KeyError('No CSV writer available')

    @staticmethod
    def _validate_sql_config(config: dict) -> bool:
        if config.get('conn_dict', config.get('conn_uri')) is None:
            return False
        return True

    def _set_elo_sql(
            self,
            config: dict,
            connector: psycopg2.extensions.connection | None = None,
            league_id: int = -1,
            league_name: str | None = None
    ):
        if self._validate_sql_config(config):
            self.sql_config = config
            self.elo_sql = EloSQL(
                self.sql_config,
                self.elo_league_config,
                connector
            )

    def _get_elo_sql(self):
        config = load_config_file(Path(self.configs_dir, self.sql_config_loc))
        self._set_elo_sql(config)

    def set_elo_sql(
            self,
            config: dict,
            connector: psycopg2.extensions.connection,
            league_id: int = -1,
            league_name: str | None = None
    ):
        self._set_elo_sql(config, connector, league_id, league_name)

    def read_sql_config(self, config: dict | None) -> None:
        if config is None:
            self._get_elo_sql()
        else:
            self._set_elo_sql(config)

    @staticmethod
    def _validate_csv_config(config: dict) -> bool:
        if config.get('write_loc') is None:
            return False
        return True

    def _set_elo_csv(
            self,
            config: dict,
            spath: str | None = None,
    ):
        if spath is None:
            path = self.configs_dir.parent
        else:
            path = str_to_path(spath)
        if self._validate_csv_config(config):
            self.csv_config = config
            self.elo_csv = EloCSV(
                self.csv_config,
                path
            )

    def set_elo_csv(
            self,
            config: dict,
            spath: str
    ):
        self._set_elo_csv(config, spath)

    def _get_elo_csv(self):
        config = load_config_file(Path(self.configs_dir, self.csv_config_loc))
        self._set_elo_csv(config)

    def read_csv_config(self, config: dict | None) -> None:
        if config is None:
            self._get_elo_csv()
        else:
            self._set_elo_csv(config)

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
            if k in {'elo', 'league'}:
                self.read_league_config(v)
            elif k == 'csv':
                self.read_csv_config(v)
            elif k == 'sql':
                self.read_sql_config(v)
        return True

    def load_configs(self, configs: dict | None = None, sql_config: dict | None = None, csv_config: dict | None = None, league_config: dict | None = None) -> bool:
        if isinstance(configs, dict):
            return self._load_configs(configs)
        else:
            self.read_league_config(league_config)
            self.read_csv_config(csv_config)
            self.read_sql_config(sql_config)

        return True

    def write_configs(self, which: str | list[str]) -> None:
        if isinstance(which, list):
            for i in which:
                self.write_configs(i)
        else:
            if which == 'sys':
                write_config_file(self.pathed_config, {
                            'reader': self.reader,
                            'writer': self.writer,
                            'csv_config_loc': self.csv_config_loc,
                            'elo_league_config_loc': self.elo_league_config_loc,
                            'sql_config_loc': self.sql_config_loc,
                })
            elif which == 'csv':
                write_config_file(Path(self.configs_dir, self.csv_config_loc), self.csv_config)
            elif which == 'sql':
                write_config_file(Path(self.configs_dir, self.sql_config_loc), self.sql_config)
            elif which == 'league':
                write_config_file(Path(self.configs_dir, self.elo_league_config_loc), self.elo_league_config)


    def dump(self) -> dict[str, Any]:
        res = {'sys': {
                    'reader': self.reader,
                    'writer': self.writer,
                    'csv_config_loc': self.csv_config_loc,
                    'elo_league_config_loc': self.elo_league_config_loc,
                    'sql_config_loc': self.sql_config_loc,
        }}
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
        if isinstance(self.reader, EloCSV):
            frames = self.reader.load_frames(frame_set)
        elif isinstance(self.reader, EloSQL):
            frames = self.reader.load_frames(frame_set)
        self.elo_league.load_frames(frames)

    def set_lid(self):
        if isinstance(self.reader, EloCSV):
            self.elo_league.set_lid(-1)
        elif isinstance(self.reader, EloSQL):
            self.elo_league.set_lid(self.reader.get_lid())
        else:
            raise NotImplementedError
