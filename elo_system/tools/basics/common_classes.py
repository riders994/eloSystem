from typing import Any


class EloBase:
    """
    Base class for all Elo System related functionality
    """

    league_config = dict()
    loaded = False
    sport = None

    def __init__(self, league_config: dict = None) -> None:
        if league_config:
            self.load_league(league_config)

    def load_league(self, league_config: dict) -> None:
        self.league_config = league_config

    def _load(self) -> None:
        self.sport = self.league_config.get('sport')

    def _dump(self) -> None:
        self.league_config['sport'] = self.sport

    def load(self) -> dict[str, Any]:
        self._load()
        self.loaded = True
        return self.league_config

    def dump(self) -> dict[str, Any]:
        self._dump()
        return self.league_config