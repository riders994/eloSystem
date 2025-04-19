from tools import SleeperScraper, FantraxScraper, FantraxFormatter, SleeperFormatter, NBACalculator, NFLCalculator

from tools.basics import week_formatter
import os
import yaml


FANTRAX_LC = 'fantrax_lc.yml'
SLEEPER_LC = 'sleeper_lc.yml'
CONFIG_DIR = os.path.join('..', 'resources', 'league_configs')

class EloSystem:

    calculator = None
    formatter = None
    scraper = None
    loaded = False


    def __init__(self, config: dict):
        self.league_config = config
        self._gen_scraper()
        self.scraper.login()

    def _gen_scraper(self):
        ltype = self.league_config.get('ltype', 'sleeper')
        if ltype == 'sleeper':
            self.scraper = SleeperScraper(league_config=self.league_config)
            self.scraper.login()
        elif ltype == 'fantrax':
            self.scraper = FantraxScraper(league_config=self.league_config)
            self.scraper.login()
        else:
            raise ValueError

    def _gen_formatter(self):
        ltype = self.league_config.get('ltype', 'sleeper')
        if ltype == 'sleeper':
            self.formatter = SleeperFormatter(league_config=self.league_config)
        elif ltype == 'fantrax':
            self.formatter = FantraxFormatter(league_config=self.league_config)
        else:
            raise ValueError

    def _gen_calculator(self):
        ltype = self.league_config.get('sport', 'nfl')
        if ltype == 'nfl':
            self.calculator = NFLCalculator(league_config=self.league_config)
        elif ltype == 'nba':
            self.calculator = NBACalculator(league_config=self.league_config)
        else:
            raise ValueError

    def _get_current_week(self, week):
        return self.calculator.seasonal_elo_frame.get('week_{}'.format(week))

    def _run_multiple(self, weeks, overwrite=False):
        week_range = week_formatter(weeks)
        for week in week_range:
            self._run(week, overwrite)

    def _run(self, week, overwrite=False):
        if week == 0:
            self._gen_scraper()
            self.scraper.scrape()
            self._gen_formatter()
            self._gen_calculator()
            self.calculator.run(week, overwrite=overwrite)
        else:
            board = self.scraper.get_scoreboard(week)
            formatted = self.formatter.run(board)
            self.calculator.run(week, formatted, overwrite=overwrite)



    def run(self, weeks, overwrite=False):
        if isinstance(weeks, int):
            cw = self._get_current_week(weeks)
            if cw:
                if not overwrite:
                    return cw
            self._run(weeks, overwrite=overwrite)
        elif isinstance(weeks, str):
            self._run_multiple(weeks, overwrite=overwrite)
        return self._get_current_week(weeks)

    def publish(self, names=False):
        df = self.calculator.publish()
        if names:
            df.index = df.index.map(self.scraper.get_managers())
        return df




if __name__ == '__main__':
    def get_config(loc):
        with open(os.path.join(CONFIG_DIR, loc)) as f:
            return yaml.load(f, Loader=yaml.SafeLoader)

    # sleeper_test = EloSystem(get_config(SLEEPER_LC))
    fantrax_test = EloSystem(get_config(FANTRAX_LC))

    for test in [
        # sleeper_test,
        fantrax_test,
    ]:
        test.run(weeks='0:24')
        test.publish(True).to_csv('./seasonal_elos1.csv')
        print('done')