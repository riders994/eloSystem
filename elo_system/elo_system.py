from typing import Any

import pandas as pd

from tools import SleeperScraper, FantraxFormatter, SleeperFormatter, NBACalculator, NFLCalculator, FantraxLeague

from tools.basics import week_formatter, EloBase
import os
import yaml


FANTRAX_LC = 'fantrax_lc.yml'
SLEEPER_LC = 'sleeper_lc.yml'

LOCATION = 'resources'

CONFIG_DIR = 'league_configs'

ELO_DIR = 'elos'

FANTRAX_IDS = {
    2024: 'blk3bn3clw9njuhc',
    2025: 'wserh14rmbbpqtcg',
}

SLEEPER_IDS = [
    '',
    '',
]

class EloSystem(EloBase):

    calculator = None
    formatter = None
    league = None
    scraper = None

    config_name = None
    resource_dir = None
    is_dynasty = False
    league_years = None


    def __init__(self, config_input, name: str):
        self.config_name = name
        if isinstance(config_input, dict):
            league_config = config_input
        elif isinstance(config_input, str):
            self.resource_dir = config_input
            league_config = self._read_config(name)
        super().__init__(league_config)

    def _read_config(self, name) -> dict:
        with open(os.path.join('..', self.resource_dir, CONFIG_DIR, name)) as f:
            return yaml.safe_load(f)

    def _write_config(self):
        with open(os.path.join('..', self.resource_dir, CONFIG_DIR, self.config_name), 'w') as f:
            yaml.safe_dump(self.league_config, f)

    def _get_elo_path(self, location = None):
        if location is None:
            location = ELO_DIR
        return os.path.join('..', self.resource_dir, location)

    def _get_season_number(self) -> int:
        return list(self.league_years.keys()).index(self.league.current_sports_year)

    def _get_league(self):
        ltype = self.league_config.get('ltype', 'sleeper')
        if ltype == 'sleeper':
            self.league = SleeperScraper(league_config=self.league_config)
        elif ltype == 'fantrax':
            self.league = FantraxLeague(league_config=self.league_config)
        else:
            raise ValueError
        self.league.load()
        self.scraper = self.league.get_scraper()

    def _get_formatter(self):
        ltype = self.league_config.get('ltype', 'sleeper')
        if ltype == 'sleeper':
            self.formatter = SleeperFormatter(league_config=self.league_config)
        elif ltype == 'fantrax':
            self.formatter = FantraxFormatter(league_config=self.league_config)
        else:
            raise ValueError

    def _get_calculator(self):
        ltype = self.league_config.get('sport', 'nfl')
        if ltype == 'nfl':
            self.calculator = NFLCalculator(league_config=self.league_config)
        elif ltype == 'nba':
            self.calculator = NBACalculator(league_config=self.league_config)
        else:
            raise ValueError

    def _get_current_week(self, week):
        return self.calculator.seasonal_elo_frame.get('week_{}'.format(week))

    def _load(self, no_frames: bool = False, ):
        super()._load()
        self.resource_dir = self.league_config.get('resource_dir', self.resource_dir)
        self.config_name = self.league_config.get('config_name', self.config_name)
        self.is_dynasty = self.league_config.get('is_dynasty', self.is_dynasty)
        self.league_years = self.league_config.get('league_years', self.league_years)
        self._get_league()
        self.league.load()
        self._get_formatter()
        self.formatter.load()
        self._get_calculator()
        dfs = dict()
        l = self._get_elo_path()
        if self.is_dynasty and not no_frames:
            dynasty_elo_frame = pd.read_csv(os.path.join(l, 'dynasty_elo.csv'), index_col=0)
            dfs.update({'dynasty_elo_frame': dynasty_elo_frame})
        if not no_frames:
            seasonal_elo_frame = pd.read_csv(os.path.join(l, 'seasonal_elos_{}.csv'.format(self._get_season_number())), index_col=0)
            id_check = seasonal_elo_frame.index.copy()
            id_check = id_check.map({v:k for k, v in self.league.members.items()})
            if id_check.hasnans:
                self.league.update_members()
                self.load_league(self.league.dump())
                self._load()
            seasonal_elo_frame.index = seasonal_elo_frame.index.map({v:k for k, v in self.league.members.items()})

            dfs.update({'seasonal_elo_frame': seasonal_elo_frame})
        self.calculator.load(dfs)

    def load(self, no_frames: bool = False):
        self._load(no_frames=no_frames)
        self.loaded = True
        return self.league_config

    def _dump(self) -> None:
        super()._dump()
        self.league_config['resource_dir'] = self.resource_dir
        self.league_config['config_name'] = self.config_name
        self.league_config['is_dynasty'] = self.is_dynasty
        self.league_config['league_years'] = self.league_years
        self._write_config()

    def _change_dynasty(self) -> None:
        if self.is_dynasty:
            self.is_dynasty = False
            self.league.is_dynasty = False
            self.calculator.is_dynasty = False
            self.dump()
        else:
            self.is_dynasty = True
            self.league.is_dynasty = True
            self.calculator.is_dynasty = True
            self.dump()

    def build_dynasty(self):
        if not self.is_dynasty:
            self._change_dynasty()
        curr = self.league.current_season_length
        self.load(True)
        self.calculator.clear_frames()
        self.calculator.generate()
        for y, ly in self.league_years.items():
            self.league.set_current_sports_year(y)
            self.league.get_scraper()
            run_str = f'0:{ly.get('season_length', curr)}'
            self.run(run_str, True)



    def _validate_dynasty_frame(self) -> bool:
        f = self.calculator.dynasty_elo_frame
        c = self.league.dynasty_end_col
        if c == f.shape[1]:
            col_count = 0
            curr = self.league.current_season_length
            for y, ly in self.league_years.items():
                if y != max(self.league_years.keys()):
                    col_count += 1 + ly.get('season_length', curr)
            col_count += self.calculator.seasonal_elo_frame.shape[1]
            return c == col_count

        return False

    def validate_dynasty(self) -> bool:
        if self.is_dynasty:
            if self.calculator.dynasty_elo_frame is not None:
                return self._validate_dynasty_frame()
            return False
        else:
            ly = self.league_years.keys()
            return len(ly) == max(ly) - min(ly) + 1

    def _run_multiple(self, weeks, overwrite=False):
        week_range = week_formatter(weeks)
        for week in week_range:
            self._run(week, overwrite)

    def _run(self, week, overwrite=False):
        if week == 0:
            self.calculator.run(week, overwrite=overwrite)
        else:
            board = self.scraper.get_scoreboard(week)
            formatted = self.formatter.run(board)
            self.calculator.run(week, formatted, overwrite=overwrite)



    def run(self, weeks, overwrite=False):
        if isinstance(weeks, int):
            cw = self._get_current_week(weeks)
            if cw is not None:
                if not overwrite:
                    return cw
            self._run(weeks, overwrite=overwrite)
        if isinstance(weeks, str):
            if weeks.find(':') == -1:
                self.run(int(weeks), overwrite=overwrite)
            else:
                self._run_multiple(weeks, overwrite=overwrite)
        return self._get_current_week(weeks)

    def publish(self, names: bool = False, to_csv: bool = False, location = None):
        dfs = dict()
        if self.is_dynasty:
            df = self.calculator.dynasty_elo_frame.copy()
            if names:
                df.index = df.index.map(self.scraper.get_managers())
            if to_csv:
                l = self._get_elo_path(location)
                df.to_csv(os.path.join(l, 'dyansty_elo.csv'))
            dfs.update({'dynasty': df})
        df = self.calculator.seasonal_elo_frame.copy()
        if names:
            df.index = df.index.map(self.scraper.get_managers())
        if to_csv:
            l = self._get_elo_path(location)
            df.to_csv(os.path.join(l, 'seasonal_elos_{}.csv'.format(self._get_season_number())))

        dfs.update({'seasonal': df})
        return dfs




if __name__ == '__main__':

    # sleeper_test = EloSystem(get_config(SLEEPER_LC))
    fantrax_test = EloSystem(LOCATION, FANTRAX_LC)

    for test in [
        # sleeper_test,
        fantrax_test,
    ]:
        test.load(True)
        test.build_dynasty()
        # test.run(weeks='23:24')
        test.publish(True, True)
        test.dump()
        print('done')