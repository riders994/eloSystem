from abc import ABC, abstractmethod
from typing import Any

from ..basics import LeagueBase, PLAYOFF_START

import fantraxapi as ft


class LeagueScraper(LeagueBase, ABC):
    """Abstract base for platform scrapers.

    Holds the shared config/state plumbing (league id, managers, playoff
    start, season length) and defines the interface every platform scraper
    (e.g. FantraxScraper, a future SleeperScraper) must implement.
    """

    def __init__(self, config: dict) -> None:
        self.league_id = None
        self.league_wrapper = None
        self.managers = dict()
        self.playoff_start = PLAYOFF_START
        self.current_season_length = 0
        super().__init__(config)

    def _load(self) -> None:
        super()._load()
        self.league_id = self.config['league_id']
        self.playoff_start = self.config.get('playoff_start', PLAYOFF_START)

    def _dump(self):
        super()._dump()
        self.config['members'].update(self.managers)
        self.config.update({
            'playoff_start': self.playoff_start
        })

    @abstractmethod
    def login(self):
        """Connect to the platform and fetch the league wrapper + scoreboards."""
        raise NotImplementedError

    @abstractmethod
    def get_members(self) -> dict[str, Any]:
        """Return the canonical member map keyed by stable owner id:
        {owner_id: {'team_id', 'curr_name', 'curr_short', 'commish'}}."""
        raise NotImplementedError

    @abstractmethod
    def get_scoreboard(self, week: int):
        """Return the scoreboard object for the given week."""
        raise NotImplementedError

    @abstractmethod
    def get_playoff_start(self) -> int:
        """Return the first playoff week for the loaded season."""
        raise NotImplementedError

    @abstractmethod
    def get_current_season_length(self) -> int:
        """Return the number of scored periods in the season."""
        raise NotImplementedError


class FantraxScraper(LeagueScraper):

    def __init__(self, config: dict) -> None:
        self.current_matchup = None
        self.league_wrapper = None
        self.scoring_periods = None

        super().__init__(config)

    def login(self) -> ft.League:
        self.load()
        self.league_wrapper = ft.League(league_id=self.league_id)
        self.scoring_periods = self.league_wrapper.scoring_period_results()
        return self.league_wrapper

    def get_current_season_length(self) -> int:
        return len(self.scoring_periods)

    def get_playoff_start(self) -> int:
        if self.loaded:
            i = self.get_current_season_length() + 1
            po = True
            while po:
                i -= 1
                po = self.scoring_periods[i].playoffs
                if i == 1:
                    po = False
            return i + 1
        else:
            return PLAYOFF_START

    def get_members(self) -> dict[str, Any]:
        return {
            team.owners: {
                'team_id': team.id,
                'curr_name': team.name,
                'curr_short': team.short,
                'commish': team.commissioner,
            } for team in self.league_wrapper.teams
        }

    def get_scoreboard(self, week: int):
        self.current_matchup = None
        self.current_matchup = self.scoring_periods[week]

        return self.current_matchup
