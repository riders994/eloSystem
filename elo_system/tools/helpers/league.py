from typing import Any

from .scraper import FantraxScraper
from elo_system._vendor.fantraxapi.objs import ScoringPeriodResult
from ..basics import (
    LeagueBase,
    PLAYOFF_START
)

APPROVED_DESTINATIONS = {
    'scoreboards', 'seasonal_elo', 'dynsaty_elo', 'roto'
}

class League(LeagueBase):

    approved_destinations = APPROVED_DESTINATIONS

    def __init__(self, year: int, config: dict):
        self.level = year

        self.scraper = None

        self.consolation_elo = True
        self.current_season_length = 1
        self.dynasty_start_week = 0
        self.last_scored_week = None
        self.league_id = None
        self.league_members = dict()
        self.playoff_start = PLAYOFF_START

        self.scoreboards = dict()
        self.roto = None
        
        super().__init__(config)

    def _generate_scraper(self) -> None:
        self.scraper.login()

    def _load(self) -> None:
        self.league_id = self.config['league_id']

        self.consolation_elo = self.config.get('consolation_elo', self.consolation_elo)
        self.current_season_length = self.config.get('current_season_length', self.current_season_length)
        self.dynasty_start_week = self.config.get('dynasty_start_week', self.dynasty_start_week)
        self.last_scored_week = self.config.get('last_scored_week', self.last_scored_week)
        self.league_members = self.config.get('league_members', self.league_members)
        self.playoff_start = self.config.get('playoff_start', self.playoff_start)
        self._generate_scraper()


    def _dump(self) -> None:
        self.config.update({
            'current_season_length': self.current_season_length,
            'dynasty_start_week': self.dynasty_start_week,
            'last_scored_week': self.last_scored_week,
            'league_id': self.league_id,
            'league_members': self.league_members,
            'playoff_start': self.playoff_start
        })

    def _get_members(self) -> dict[str, Any]:
        return self.scraper.get_members()

    def _set_member(self, member_id: str, member_info: dict[str, Any]) -> None:
        if member_id not in self.league_members:
            self.league_members.update({
                member_id: {
                    'curr_name': member_info['curr_name'],
                    'names': [member_info['curr_name']],
                    'short_name': member_info['curr_short'],
                    'team_id': member_info['team_id'],
                    'is_commish': member_info['commish'],
                }
            })

    def _set_members(self, members: dict[str, Any]) -> None:
        for member_id, member_info in members.items():
            self._set_member(member_id, member_info)

    def _update_member(self, member_id: str, member_info: dict[str, Any], overwrite: bool = False) -> None:
        old_info = self.league_members.get(member_id)
        if old_info is None:
            self._set_member(member_id, member_info)
        else:
            old_info['names'].append(member_info['curr_name'])
            old_info.update({
                'short_name': member_info['curr_short'],
                    'team_id': member_info['team_id'],
                    'is_commish': member_info['commish'],
            })
            if overwrite:
                old_info.update({
                    'curr_name': member_info['curr_name'],
                })


    def _update_members(self, members: dict[str, Any], overwrite: bool = False) -> None:
        for member_id, member_info in members.items():
            self._update_member(member_id, member_info, overwrite)

    def update_members(self, members: dict[str, Any], overwrite: bool = False) -> None:
        self._update_members(members, overwrite)

    def reset_members(self):
        self._update_members(self._get_members(), True)

    def _get_playoff_start(self) -> int:
        return self.scraper.get_playoff_start()

    def _get_current_season_length(self) -> int:
        return self.scraper.get_current_season_length()

    def set_current_season_length(self, length: int | None = None) -> None:
        if isinstance(length, int):
            self.current_season_length = length
        else:
            self.current_season_length = self._get_current_season_length()

    def set_playoff_start(self, start: int | None = None) -> None:
        if isinstance(start, int):
            self.playoff_start = start
        else:
            self.playoff_start = self._get_playoff_start()

    def scrape(self) -> dict[str, Any]:
        self.load()
        self.set_playoff_start()
        self.set_current_season_length()
        self.reset_members()

        return self.dump()


class FantraxLeague(League):

    def _generate_scraper(self):
        scraper_config = {
            'league_id': self.league_id,
            'playoff_start': self.playoff_start,
            'members': self.config.get('members', dict()),
        }
        self.scraper = FantraxScraper(scraper_config)
        super()._generate_scraper()

    def get_week(self, week: int | None = None) -> ScoringPeriodResult:
        if week is None:
            week = self.last_scored_week
            if week is None:
                week = self.current_season_length
        return self.scraper.get_scoreboard(week)