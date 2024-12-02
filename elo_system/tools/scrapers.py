from basics.common_classes import EloBase

from sleeper.api import (
    get_league, get_users_in_league, get_matchups_for_week
)

from fantraxapi import FantraxAPI

PLAYOFF_START = 3


class LeagueScraper(EloBase):

    current_matchup = None
    league_wrapper = None
    matchups = dict()

    def __init__(self, league_config: dict = None) -> None:
        super().__init__(league_config)

    @property
    def playoff_start(self) -> int:
        return self.league_config.get('playoff_start', PLAYOFF_START)

    def _unload(self):
        super()._unload()


class SleeperScraper(LeagueScraper):
    league_wrapper = None
    members = None
    teams = None
    playoff_start = PLAYOFF_START

    def _unload(self) -> None:
        super()._unload()
        self.members = self.league_config['members']
        self.teams = self.league_config['teams']
        self.playoff_start = self.league_config.get('playoff_start', PLAYOFF_START)

    def get_playoff_start(self) -> int:
        if self.league_wrapper:
            return self.league_wrapper['settings']['playoff_week_start']
        else:
            self.login()
            return self.get_playoff_start()

    def scrape(self) -> None:
        self.league_config['members'].update(self.get_managers())
        self.league_config['teams'].update(self.id_tie)
        self.league_config['playoff_start']= self.playoff_start

    def login(self) -> dict:
        self.league_wrapper: dict = get_league(league_id=self.league_id)
        return self.league_wrapper

    def get_managers(self) -> dict:
        users: list = get_users_in_league(league_id=self.league_id)
        return {user['user_id']: user['display_name'] for user in users}

    @property
    def id_tie(self) -> dict:
        users = get_users_in_league(league_id=self.league_id)
        return {user['user_id']: i + 1 for i, user in enumerate(users)}

    def _get_non_playoff_scoreboard(self, week: int) -> list[dict]:
        if week < self.playoff_start:
            return get_matchups_for_week(league_id=self.league_id, week=week)
        # else:
        #     winners: list[PlayoffMatchup] = LeagueAPIClient.get_winners_bracket(league_id=self.league_id)
        #     losers: list[PlayoffMatchup] = LeagueAPIClient.get_losers_bracket(league_id=self.league_id)
        #     self.current_matchup = winners + losers

    def get_scoreboard(self, week: int, overwrite: bool = True) -> list[dict]:
        if overwrite:
            current_matchup: list[dict] = self._get_non_playoff_scoreboard(week)
            self.matchups.update({week: current_matchup})
        else:
            current_matchup = self.matchups.get(week)
            if not current_matchup:
                current_matchup: list[dict] = self._get_non_playoff_scoreboard(week)
                self.matchups.update({week: current_matchup})
        self.current_matchup = current_matchup

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
