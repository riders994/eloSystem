from .basics import EloBase
from requests import Session
import os

from sleeper.api import (
    get_league, get_users_in_league, get_matchups_for_week
)

from fantraxapi import FantraxAPI
from fantraxapi.objs import (
    Team
)

PLAYOFF_START = 3

COOKIE_DICT = {
        'ui': os.environ.get('UI_COOKIE'),
        'FX_RM': os.environ.get('FX_RM_COOKIE'),

    }


class LeagueScraper(EloBase):

    current_matchup = None
    league_wrapper = None
    matchups = dict()
    members = None
    playoff_start = PLAYOFF_START

    def __init__(self, league_config: dict = None) -> None:
        super().__init__(league_config)

    def _load(self):
        super()._load()
        self.members = self.league_config.get('members')
        self.playoff_start = self.league_config.get('playoff_start', PLAYOFF_START)


class SleeperScraper(LeagueScraper):
    league_wrapper = None
    teams = None

    def _load(self) -> None:
        super()._load()
        self.teams = self.league_config.get('teams')

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
    league_wrapper = None
    members = None
    playoff_start = PLAYOFF_START
    scoring_periods = None

    def _load(self) -> None:
        super()._load()

    def get_playoff_start(self) -> int:
        if self.league_wrapper:
            p_end = False
            i = 0
            while not p_end:
                i += 1
                if not self.scoring_periods.get('P{}'.format(i)):
                    p_end = True
            self.playoff_start = len(self.scoring_periods) - i + 2
            return self.playoff_start
        else:
            self.login()
            return self.get_playoff_start()

    def get_managers(self) -> dict:
        return {team.team_id: team.name for team in self.league_wrapper.teams}
    
    def scrape(self) -> None:
        self.league_config['members'].update(self.get_managers())
        self.get_playoff_start()
        self.league_config['playoff_start'] = self.playoff_start

    def login(self) -> FantraxAPI:
        self.league_wrapper = FantraxAPI(league_id=self.league_id)
        self.scoring_periods = self.league_wrapper.scoring_periods()
        self.scoring_periods.update(self.league_wrapper.playoffs())
        return self.league_wrapper

    def get_scoreboard(self, week: int):
        if week < self.playoff_start:
            pweek = 'S{}'.format(week)
        else:
            pweek = 'P{}'.format(week - self.playoff_start + 1)
        self.current_matchup = None
        self.current_matchup = self.scoring_periods[pweek]

        return self.current_matchup


if __name__ == '__main__':
    fantrax_lc = {
        'league_id': 'blk3bn3clw9njuhc',
        'ltype': 'fantrax',
        'sport': 'nba',
        'is_dynasty': False,
        'members': dict(),
    }

    scr = FantraxScraper(fantrax_lc)
    scr.login()
    scr.scrape()
    print('done')