from elo_system.tools import (
    SleeperScraper,
    SleeperFormatter,
    NFLCalculator,
)


class EloSystem:

    calculator = None
    formatter = None
    scraper = None


    def __init__(self, config: dict):
        self.league_config = config
        self._gen_scraper()
        self.scraper.login()

    def _gen_scraper(self):
        ltype = self.league_info.get('ltype', 'sleeper')
        if ltype == 'sleeper':
            self.scraper = SleeperScraper(league_config=self.league_config)
        if ltype == 'fantrax':
            self.scraper = None
        raise ValueError

    def _gen_formatter(self):
        ltype = self.league_info.get('ltype', 'sleeper')
        if ltype == 'sleeper':
            self.formatter = SleeperFormatter(league_config=self.league_config)
        if ltype == 'fantrax':
            self.formatter = None
        raise ValueError

    def _gen_calculator(self):
        ltype = self.league_info.get('sport', 'nfl')
        if ltype == 'nfl':
            self.calculator = NFLCalculator(league_config=self.league_config)
        if ltype == 'nba':
            self.calculator = None
        raise ValueError

    def _run_multiple(self):
        pass

    def run(self):
        pass
