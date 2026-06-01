import time

from typing import Any
from .basics import EloBase
from .scrapers import FantraxScraper

PLAYOFF_START = 3

class League(EloBase):
    """League class."""

    ext_id = 0
    nickname = None
    tags = list()

    current_scraper = None

    current_scoring_periods = None
    current_season_length = 1
    current_sports_year = None
    dynasty_end_col = 0
    first_season = 9999
    is_dynasty = False
    league_years = None
    archived_league_years = None
    members = None
    playoff_start = PLAYOFF_START

    def __init__(self, league_config: dict = dict()) -> None:
        super().__init__(league_config)

    def _load(self):
        super()._load()
        self.ext_id = self.league_config.get('ext_id', self.ext_id)
        self.nickname = self.league_config.get('nickname', self.nickname)
        self.tags = self.league_config.get('tags', self.tags)
        self.set_current_sports_year(self.get_current_sports_year())
        self.current_season_length = self.league_config.get('current_season_length', 1)
        self.dynasty_end_col = self.league_config.get('dynasty_end_col', 0)
        self.first_season = self.league_config.get('first_season', PLAYOFF_START)
        self.is_dynasty = self.league_config.get('is_dynasty', False)
        self.league_years = self.league_config.get('league_years', dict())
        self.archived_league_years = self.league_config.get('archived_league_years', dict())
        self.members = self.league_config.get('members', dict())
        self.playoff_start = self.league_config.get('playoff_start', PLAYOFF_START)

    def _dump(self):
        super()._dump()
        self.league_config['ext_id'] = self.ext_id
        self.league_config['nickname'] = self.nickname
        self.league_config['tags'] = self.tags
        self.league_config['current_season_length'] = self.current_season_length
        self.league_config['current_sports_year'] = self.current_sports_year
        self.league_config['dynasty_end_col'] = self.dynasty_end_col
        self.league_config['first_season'] = self.first_season
        self.league_config['is_dynasty'] = self.is_dynasty
        self.league_config['league_years'] = self.league_years
        self.league_config['archived_league_years'] = self.archived_league_years
        self.league_config['members'] = self.members
        self.league_config['playoff_start'] = self.playoff_start

    def add_season(self, year: int, league_id: str, length: int = None, switch: bool = False, overwrite: bool = False) -> dict[str, Any]:
        if self.loaded:
            if not overwrite:
                season = self.league_years.get(year)
                if season:
                    return season
            if len(self.league_years.keys()) == 0:
                return self._add_initial_season(year, switch, league_id)
            if year < self.first_season:
                return self._add_initial_season(year, switch, league_id)
            if year > self.current_sports_year:
                self.set_current_sports_year(year)
            season = {
                'league_id': league_id,
            }
            if self.is_dynasty:
                self.dynasty_end_col += 1 + length
                season.update({
                    'dynasty_end_col': self.dynasty_end_col,
                })
            self.league_years.update({year: season})
            return season

        else:
            raise ValueError

    def _add_initial_season(self, year: int, is_dynasty: bool, league_id: str) -> dict[str, Any]:
        self.first_season, self.current_sports_year = year, year
        season = {
            'league_id': league_id,
        }
        if is_dynasty:
            self.is_dynasty = True
        self.league_years.update({year: season})
        return season

    def get_current_sports_year(self):
        t = time.localtime()
        y = t.tm_year
        m = t.tm_mon
        if self.sport == 'nba':
            if m < 7:
                y -= 1
        if self.sport == 'nfl':
            if m < 3:
                y -= 1
        return y

    def reset_first_season(self) -> None:
        try:
            self.first_season = min(self.league_years.keys())
        except ValueError:
            self.first_season = 9999

    def set_current_sports_year(self, year: int) -> None:
        self.current_sports_year = year

    def set_current_season_length(self, length: int) -> None:
        self.current_season_length = length

    def set_playoff_start(self, start: int) -> None:
        self.playoff_start = start

    def add_tag(self, tag: str) -> None:
        self.tags.append(tag)

    def set_nickname(self, nickname: str) -> None:
        self.nickname = nickname

    def _update_members(self, members: dict[str, Any], year:int = None) -> None:
        if year is None:
            year = self.current_sports_year
        self.league_years[year]['members'] = members
        if year == self.current_sports_year:
            self.members = members


class FantraxLeague(League):
    """Abstraction of the League class for Fantrax leagues."""

    def get_scraper(self, year: int = None) -> FantraxScraper:
        try:
            if year is not None:
                self.current_scraper = FantraxScraper(self.league_years[year]['league_id'], self.league_config)
                self.current_sports_year = year
            else:
                self.current_scraper = FantraxScraper(self.league_years[self.current_sports_year]['league_id'], self.league_config)
        except KeyError:
            year = max(self.league_years.keys())
            self.current_scraper = FantraxScraper(self.league_years[year]['league_id'], self.league_config)
            self.current_sports_year = year
        self.current_scraper.login()
        return self.current_scraper

    def update_members(self, year: int = None) -> None:
        if year is None:
            year = self.current_sports_year
        if year == self.current_sports_year:
            self._update_members(self.current_scraper.get_managers(), year)
        else:
            self.get_scraper(year)
            self.update_members(year)
