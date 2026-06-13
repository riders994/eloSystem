from typing import Any

from .basics.common_classes import LeagueBase
from .basics.common_funcs import week_formatter
from .helpers import (
    League,
    FantraxLeague,
    FrameManager,
    set_formatter,
    set_calculator
)


import pandas as pd


class EloLeague(LeagueBase):

    def __init__(self, config: dict | None = None) -> None:
        self.leagues = dict()
        self.seasons = dict()

        self.current_league = None

        self.current_season = None
        self.extras = 0
        self.is_dynasty = False
        self.is_roto = False
        self.k = 60
        self.league_type = None
        self.platform = None

        self.season_stats = {
            'playoff_start': dict(),
            'current_season_length': dict()
        }

        self.calculator = None
        self.formatter = None
        self.frame_manager = None

        super().__init__(config)

    def _load(self) -> None:
        super()._load()
        self.league_type: str = self.config['league_type']
        self.platform: str = self.config['platform']

        self.current_season: int | None = self.config.get('current_season')
        self.extras = int(self.is_roto) + int(self.is_dynasty)
        self.is_dynasty: bool = self.config.get('is_dynasty', False)
        self.is_roto: bool = self.config.get('is_roto', False)
        self.k: int = self.config.get('k', self.k)
        self.seasons.update(self.config.get('seasons', dict()))

    def _dump(self) -> None:
        super()._dump()
        self.config.update({
            'current_season': self.current_season,
            'is_dynasty': self.is_dynasty,
            'seasons': self.seasons,
            'is_roto': self.is_roto,
            'k': self.k
        })

    @staticmethod
    def _validate_fantrax(seas_dict: dict[str, Any]) -> bool:
        return seas_dict.get('league_id') is not None

    def _validate_season(self, seas_dict: dict[str, Any]) -> bool:
        if self.platform == 'fantrax':
            return self._validate_fantrax(seas_dict)
        return False

    def add_season(self, seas_dict: dict[str, Any], year: int, league: bool = False) -> bool:
        if self._validate_season(seas_dict):
            if self.platform == 'fantrax':
                self.seasons.update({year: seas_dict})

            if league:
                self.add_league(year)
            return True
        return False

    def _find_season(self, sid: str) -> int:
        for y, s in self.seasons.items():
            if s['league_id'] == sid:
                return y
        return 0

    def remove_season(self, year: int | None = None, league_id: str | None = None) -> dict[str, Any]:
        if year is None:
            if league_id is None:
                raise ValueError
            else:
                year = self._find_season(league_id)
                if year == 0:
                    raise ValueError
        if year not in self.seasons:
            raise KeyError
        self.remove_league(year)
        return self.seasons.pop(year)

    def _set_current_league(self):
        if self.leagues.get(self.current_season) is None:
            self.add_league(self.current_season)
        self.current_league = self.leagues[self.current_season]
        self.current_league.load()

    def set_current_season(self, year: int | None = None) -> int | None:
        if year is None:
            self.reset_current_season()
        else:
            self.current_season = year
        self._set_current_league()
        return self.current_season

    def reset_current_season(self) -> int | None:
        try:
            self.current_season = max(list(self.seasons.keys()))
        except ValueError as e:
            if 'empty' not in str(e):
                raise e
        self._set_current_league()
        self.current_league = self.leagues.get(self.current_season)
        if isinstance(self.current_league, League):
            self.current_league.load()

        return self.current_season

    def compile_season_stats(self) -> dict[str, Any]:
        pos = dict()
        sl = dict()
        for y, seas in self.seasons.items():
            pos.update({y: seas['playoff_start']})
            sl.update({y: seas['current_season_length']})
        self.season_stats['playoff_start'].update(pos)
        self.season_stats['current_season_length'].update(sl)
        return self.season_stats

    def add_league(self, league_year: int, overwrite: bool = False) -> None:
        if overwrite or self.leagues.get(league_year) is None:
            if self.seasons.get(league_year) is not None:
                l = FantraxLeague(league_year, self.seasons)
                l.scrape()
                self.leagues.update({league_year: l})
            else:
                raise KeyError

    def remove_league(self, league_year: str | int) -> None:
        if isinstance(league_year, int):
            self.leagues.pop(league_year, None)
        elif isinstance(league_year, str):
            for k, v in self.seasons.items():
                if v['league_id'] == league_year:
                    self.leagues.pop(k, None)



    def _set_frame_manager(self) -> None:
        if not isinstance(self.frame_manager, FrameManager):
            self.frame_manager = FrameManager(self.config)

    def _set_dynasty_start_week(self, year: int | list[int] | None = None):
        start_season = min(self.seasons.keys())
        if year is None:
            year = range(start_season, start_season  + len(self.seasons.keys()))
        if isinstance(year, int):
            s = self.seasons[year]
            w = 0
            if year != start_season:
                for y in range(start_season, year):
                    w += self.seasons[y]['current_season_length']
                    w += 1
            s.update({'dynasty_start_week': w})
        else:
            for y in year:
                self._set_dynasty_start_week(y)


    def _change_to_dynasty(self):
        if self.frame_manager.can_dynasty():
            self.frame_manager.set_is_dynasty(True)
            for s in self.seasons.keys():
                self.add_league(s)
                if not self.frame_manager.validate_season(s):
                    self.run_season(s)
            self._set_dynasty_start_week()
            self.is_dynasty = True
            self.run_dynasty()

    def change_dynasty(self, to: bool | None = None, delete: bool = False) -> bool:
        if isinstance(to, bool):
            if to == self.is_dynasty:
                return self.is_dynasty
        else:
            to = not self.is_dynasty
        if to:
            self._change_to_dynasty()
            return self.is_dynasty
        else:
            self.is_dynasty = False
            if delete:
                pass
        return self.is_dynasty

    def run_prep(self, year: int | None = None):
        if year is None:
            year = self.current_sports_year
        self.add_league(year)
        self.set_current_season(year)
        self.formatter = set_formatter(self.platform)
        self._set_frame_manager()
        self.calculator = set_calculator(self.league_type)

    def _return_frames(self, year: int) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame] | tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
        if self.extras == 2:
            return self.frame_manager.seasonal_elo[year], self.frame_manager.dynasty_elo, self.frame_manager.roto_history[year]
        elif self.extras == 1:
            if self.is_dynasty:
                return self.frame_manager.seasonal_elo[year], self.frame_manager.dynasty_elo
            elif self.is_roto:
                return self.frame_manager.seasonal_elo[year], self.frame_manager.roto_history[year]
            return None
        else:
            return self.frame_manager.seasonal_elo[year]

    def _rename(self, scoreboard: pd.DataFrame, season: int) -> pd.Series:
        id_map = {v['team_id']: k for k, v in self.seasons[season]['league_members'].items()}
        return scoreboard['opponent'].map(id_map)

    def _run_one(self, week: int, year: int, overwrite: bool = False) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame] | tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
        if week == 0:
            self.frame_manager.generate(year, overwrite)
        else:
            formatted_scores = self.formatter(self.league_type, self.current_league.get_week(week))
            formatted_scores['opponent'] = self._rename(formatted_scores, year)
            if self.is_dynasty:
                dynasty_week = week + self.seasons[year]['dynasty_start_week']
                try:
                    self.calculator(
                        self.frame_manager.dynasty_elo,
                        formatted_scores,
                        dynasty_week,
                        overwrite,
                        self.k
                    )
                except AttributeError:
                    raise KeyError('No Dynasty frame initialized')
            else:
                try:
                    self.calculator(
                        self.frame_manager.seasonal_elo[year],
                        formatted_scores,
                        week,
                        overwrite,
                        self.k
                    )
                except KeyError as e:
                    if e.args[0] == self.current_sports_year:
                        raise KeyError('Current sports year has no frames')
        return self._return_frames(year)

    def _run_multiple(self, weeks: str, year: int, overwrite: bool = False) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame] | tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
        formed_weeks = week_formatter(weeks)
        if isinstance(formed_weeks, int):
            self._run_one(formed_weeks, year, overwrite)
        elif isinstance(formed_weeks, range):
            for week in formed_weeks:
                self._run_one(week, year, overwrite)
        else:
            raise ValueError
        return self._return_frames(year)

    def run_dynasty(self, overwrite: bool = False):
        for s in self.seasons.keys():
            self.run_season(s)

    def run_season(self, year: int | None = None, overwrite: bool = False, ):
        if year is None:
            year = self.current_sports_year
        self.run_prep(year)
        weeks = '0:{}'.format(self.seasons[year]['current_season_length'])
        self._run_multiple(weeks, year, overwrite)

    def publish(self) -> dict[str, Any]:
        payload = self.frame_manager.publish()
        payload.update({'config': self.config})

        return payload

    def load_frames(self, frames: dict[str, dict]) -> None:
        self.frame_manager.load_frames(frames)

    def run(self, week: int | str, year: int | None = None, overwrite: bool = False, ):
        if year is None:
            year = self.current_sports_year

        if isinstance(week, str):
            return self._run_multiple(week, year, overwrite)
        else:
            return self._run_one(week, year, overwrite)
