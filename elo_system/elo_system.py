from elo_system.tools import SleeperScraper


class EloSystem:
    scraper = None
    config = dict()

    def __init__(self, config, scraper=None):
        self.config.update(config)
        self.league_info = self.config.get("league_info", dict())
        if scraper:
            self.scraper = scraper
        else:
            self._gen_scraper()
            self.scraper.login()

    def _gen_scraper(self):
        ltype = self.league_info.get('ltype', 'sleeper')
        if ltype == 'sleeper':
            self.scraper = SleeperScraper()
        if ltype == 'fantrax':
            self.scraper = None
        raise ValueError

    def run_multiple(self):
        pass

    def run(self):
        pass
