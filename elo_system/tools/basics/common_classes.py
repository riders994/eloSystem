

class EloBase:

    league_config = dict()
    league_id = None

    def __init__(self, league_config: dict = None) -> None:
        if league_config:
            self.load_league(league_config)

    def load_league(self, league_config: dict) -> None:
        self.league_config = league_config
        self._unload()

    def _unload(self):
        self.league_id = self.league_config['league_id']
