import os
from typing import Any

from .basics import EloBase

from sleeper.api import (
    get_league, get_users_in_league, get_matchups_for_week
)

import fantraxapi as ft

PLAYOFF_START = 3

class LeagueScraper(EloBase):

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

    @staticmethod
    def get_playoff_start() -> int:
        return PLAYOFF_START

    @staticmethod
    def get_current_season_length() -> int:
        return 0


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
