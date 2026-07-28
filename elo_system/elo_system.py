import psycopg2

from typing import Any
from pathlib import Path

from .tools import EloLeague, EloCSV, EloSQL
from .tools.basics import load_config_file, write_config_file, str_to_path

CONFIGS = {
    'sql', 'csv', 'elo', 'league', 'ratings',
}

# The ratings config names the league, so it has to be read before the CSV
# backend is built -- that is what settles which directory a league writes to.
CONFIG_ORDER = ('ratings', 'league', 'elo', 'csv', 'sql')

# Default locations used when EloSystem is constructed without a config path
# (bootstrap mode): the directory skeleton is created relative to the CWD.
DEFAULT_RESOURCES_DIR = 'resources'
DEFAULT_CONFIGS_DIR = 'configs'
DEFAULT_SYS_CONFIG = 'sys_config.yml'
# Fallback when no league is configured at all (bootstrap, or a lone league).
DEFAULT_RATINGS_CONFIG = 'ratings_config.yml'





class EloSystem:

    def __init__(self, config_path: str | None = None, league: str | None = None):
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
        self.sql_config_loc = config.get('sql_config_name', 'sql_config.yml')

        # The CSV and SQL configs are shared; the ratings config is per league.
        # One EloSystem drives one league, so which one is settled here, before
        # any backend exists.
        self.ratings_configs: dict[str, str] = dict(config.get('ratings_configs', dict()))
        self.default_league = config.get('default_league')
        self.league = self._select_league(league)
        self.ratings_config_loc = self._ratings_config_loc()

        self.csv_config = dict()
        self.ratings_config = dict()
        self.sql_config = dict()

        self.reader = None
        self.writer = None
        self.elo_league = None
        self.elo_csv = None
        self.elo_sql = None


    def _select_league(self, league: str | None) -> str | None:
        """Settle which league this instance drives.

        Explicit argument first, then the config's default, then -- only when
        exactly one league is configured -- that one. An ambiguous choice is
        an error rather than a guess, because picking wrong would publish one
        league's ratings under another's name.
        """
        if league is not None:
            if self.ratings_configs and league not in self.ratings_configs:
                raise KeyError('Unknown league: {}. Configured: {}'.format(
                    league, ', '.join(sorted(self.ratings_configs)) or 'none'))
            return league
        if self.default_league is not None:
            return self.default_league
        if len(self.ratings_configs) == 1:
            return next(iter(self.ratings_configs))
        if not self.ratings_configs:
            return None
        raise KeyError(
            'Several leagues are configured ({}); pass league= or set '
            'default_league'.format(', '.join(sorted(self.ratings_configs)))
        )

    def _ratings_config_loc(self) -> str:
        """The ratings config filename for the selected league."""
        if self.league is not None and self.league in self.ratings_configs:
            return self.ratings_configs[self.league]
        if self.league is not None:
            return 'ratings_{}.yml'.format(self.league)
        return DEFAULT_RATINGS_CONFIG

    @property
    def league_dir(self) -> str | None:
        """The ratings subdirectory for this league.

        Defaults to the league key, so one CSV config can serve every league;
        a league can override it with ratings_dir in its own config.
        """
        return self.ratings_config.get('ratings_dir', self.league)

    def _backend(self, key: str):
        return {'sql': self.elo_sql, 'csv': self.elo_csv}[key]

    def _assign_rw(self):
        self.reader = self._backend(self.reader_key)
        self.writer = self._backend(self.writer_key)

    def _other_key(self, current) -> str:
        """The key of the backend that is not the one in hand."""
        if isinstance(current, EloCSV):
            return 'sql'
        if isinstance(current, EloSQL):
            return 'csv'
        raise KeyError('Nothing to toggle from; load the configs first')

    def _toggle(self, current):
        key = self._other_key(current)
        backend = self._backend(key)
        if backend is None:
            raise KeyError('No {} backend available'.format(key.upper()))
        return key, backend

    def toggle_reader(self):
        self.reader_key, self.reader = self._toggle(self.reader)

    def toggle_writer(self):
        self.writer_key, self.writer = self._toggle(self.writer)

    def set_reader(self, key: str) -> None:
        """Point the reader at the 'csv' or 'sql' backend by name."""
        if (backend := self._backend(key)) is None:
            raise KeyError('No {} backend available'.format(key.upper()))
        self.reader_key, self.reader = key, backend

    def set_writer(self, key: str) -> None:
        """Point the writer at the 'csv' or 'sql' backend by name."""
        if (backend := self._backend(key)) is None:
            raise KeyError('No {} backend available'.format(key.upper()))
        self.writer_key, self.writer = key, backend

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
                self.ratings_config,
                connector,
                self.resources_dir
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
                path,
                self.league_dir
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
            config = load_config_file(Path(self.configs_dir, self.ratings_config_loc))
        if self._validate_league_config(config):
            self.ratings_config = config
            self.elo_league = EloLeague(self.ratings_config)


    def _load_configs(self, configs: dict) -> bool:
        for k in configs:
            if k not in CONFIGS:
                raise KeyError(k)
        # Read in a fixed order rather than the caller's: the CSV backend
        # needs the league already known.
        ordered = [k for k in CONFIG_ORDER if k in configs]
        for k, v in ((k, configs[k]) for k in ordered):
            if k not in CONFIGS:
                raise KeyError(k)
            if k in {'elo', 'league', 'ratings'}:
                self.read_league_config(v)
            elif k == 'csv':
                self.read_csv_config(v)
            elif k == 'sql':
                self.read_sql_config(v)
        return True

    def load_configs(self, configs: dict | None = None, sql_config: dict | None = None, csv_config: dict | None = None, league_config: dict | None = None) -> bool:
        if isinstance(configs, dict):
            loaded = self._load_configs(configs)
        else:
            self.read_league_config(league_config)
            self.read_csv_config(csv_config)
            self.read_sql_config(sql_config)
            loaded = True

        # The backends exist only once their configs are read, so the
        # reader/writer can only be pointed at them here.
        self._assign_rw()
        return loaded

    def _sys_config(self) -> dict[str, Any]:
        # The keys have to be the ones __init__ reads back, and the values the
        # backend *names* -- writing self.reader would serialise the object.
        # The CSV and SQL configs are shared across leagues; ratings_configs
        # names one per league.
        sys_config = {
            'reader': self.reader_key,
            'writer': self.writer_key,
            'csv_config_name': self.csv_config_loc,
            'sql_config_name': self.sql_config_loc,
        }
        if self.ratings_configs:
            sys_config['ratings_configs'] = dict(self.ratings_configs)
        if self.default_league is not None:
            sys_config['default_league'] = self.default_league
        return sys_config

    def write_configs(self, which: str | list[str]) -> None:
        if isinstance(which, list):
            for i in which:
                self.write_configs(i)
        else:
            if which == 'sys':
                write_config_file(self.pathed_config, self._sys_config())
            elif which == 'csv':
                write_config_file(Path(self.configs_dir, self.csv_config_loc), self.csv_config)
            elif which == 'sql':
                write_config_file(Path(self.configs_dir, self.sql_config_loc), self.sql_config)
            elif which in {'league', 'ratings'}:
                write_config_file(Path(self.configs_dir, self.ratings_config_loc), self.ratings_config)


    def dump(self) -> dict[str, Any]:
        res = {'sys': self._sys_config()}
        if self.ratings_config is not None:
            if len(self.ratings_config):
                res.update({'ratings': self.ratings_config})
        if self.csv_config is not None:
            if len(self.csv_config):
                res.update({'csv': self.csv_config})
        if self.sql_config is not None:
            if len(self.sql_config):
                res.update({'sql': self.sql_config})
        self.write_configs(list(res.keys()))

        return res

    def sync_dims(self, years: list[int] | None = None, scrape: bool = True) -> None:
        """Register the configured seasons' members and teams in the SQL dims.

        Runs independently of publish(), so a season can have its managers and
        teams put on file before any elos exist for it. Pass scrape=False to
        sync from the league config as it stands instead of re-scraping.

        Args:
            years:  Seasons to sync; every configured season by default.
            scrape: Re-scrape each season first, so renames, handovers and
                    standings are current before the dims are written.
        """
        if self.elo_sql is None:
            raise KeyError('No SQL writer available')

        if self.elo_league is not None:
            if not self.elo_league.loaded:
                self.elo_league.load()
            if years is None:
                years = list(self.elo_league.seasons.keys())
            if scrape:
                for year in years:
                    self.elo_league.add_league(year, overwrite=True)
            self.ratings_config = self.elo_league.dump()

        self.elo_sql.set_league_config(self.ratings_config)
        self.elo_sql.sync_dims()

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
