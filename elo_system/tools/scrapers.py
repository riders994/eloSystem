from basics.common_classes import EloBase

from sleeper.api import LeagueAPIClient
from sleeper.enum import Sport
from sleeper.model import (
    League,
    Matchup,
    PlayoffMatchup,
)
from fantraxapi import FantraxAPI

PLAYOFF_START = 3


class LeagueScraper(EloBase):

    playoff_start = 3
    current_matchup = None
    league_wrapper = None

    def __init__(self, league_config: dict = None) -> None:
        super().__init__(league_config)

    def _unload(self):
        super()._unload()
        self.playoff_start = self.league_config.get('playoff_start', PLAYOFF_START)


class SleeperScraper(LeagueScraper):

    def login(self):
        self.league_wrapper: League = LeagueAPIClient.get_league(league_id=self.league_id)
        return self.league_wrapper

    def get_scoreboard(self, week: int):
        if week < self.playoff_start:
            self.current_matchup: list[Matchup] = LeagueAPIClient.get_matchups_for_week(league_id=self.league_id, week=week)
        else:
            winners: list[PlayoffMatchup] = LeagueAPIClient.get_winners_bracket(league_id=self.league_id)
            losers: list[PlayoffMatchup] = LeagueAPIClient.get_losers_bracket(league_id=self.league_id)
            self.current_matchup = winners + losers

        return self.current_matchup


class FantraxScraper(LeagueScraper):
    def login(self) -> FantraxAPI:
        self.league_wrapper = FantraxAPI(league_id=self.league_id)
        return self.league_wrapper

    def get_scoreboard(self, week: int):
        if week < self.playoff_start:
            self.current_matchup = None
        else:
            pass

        return self.current_matchup
