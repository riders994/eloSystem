from basics.common_funcs import median_elo_calc
from .formatter import Formatter
import pandas as pd
import numpy as np


class Calculator(Formatter):

    is_dynasty = False
    loaded = False
    osa_factor = .4

    team_elo_frame = None
    dynasty_elo_frame = None
    seasonal_elo_frame = None

    def __init__(self, league_config: dict = dict()) -> None:
        super().__init__(league_config=league_config)

    def _elo_gen(self) -> pd.DataFrame:
        return pd.DataFrame(
                    {'week_0': [1500] * len(self.members)}, index=self.members.keys()
                )

    def _generate(self, schemas: list = None, schema: str = 'seasonal_elo_frame') -> None:
        if isinstance(schemas, list):
            for s in schemas:
                self._generate(s)
        dim = len(self.members)
        if dim:
            setattr(self, schema, self._elo_gen())

    def _unload(self) -> None:
        super()._unload()
        self.is_dynasty = self.league_config.get('is_dynasty', False)
        self.osa_factor = self.league_config.get('osa_factor', self.osa_factor)

    def load(self, ratings_frames: dict[pd.DataFrame] = None) -> None:
        self._unload()
        if ratings_frames:
            self.load_ratings(ratings_frames)
        self.loaded = True

    def load_ratings(self, ratings_frames: dict) -> None:
        for schema, frame in ratings_frames.items():
            setattr(self, schema, frame)

    def _generate_dynasty(self) -> None:
        self._generate(schemas=['dynasty_elo_frame', 'seasonal_elo_frame'])

    def _osa(self, elos) -> np.array:
        return ((elos - 1500) * (1 - self.osa_factor)) + 1500

    def _run_elo(self, scoreboard, week: int = None, dynasty_week: int = None):
        pass

    def _run_dynasty(self, scoreboard: pd.DataFrame, week: int, overwrite: bool = True) -> pd.Series:
        dynasty_week = week
        if week:
            complete = False
            if not overwrite:
                complete = bool(self.seasonal_elo_frame.get('week_{}'.format(week)))
                dynasty_week = len(self.dynasty_elo_frame.columns) - 1
            if not complete:
                dynasty_week = len(self.dynasty_elo_frame.columns)
                self._run_elo(scoreboard, week=week, dynasty_week=dynasty_week)
        else:
            if self.dynasty_elo_frame:
                dynasty_week = len(self.dynasty_elo_frame.columns)
                d_elo_vec = self.dynasty_elo_frame['week_{}'.format(dynasty_week - 1)]
                osa_results = self._osa(d_elo_vec)
                self.dynasty_elo_frame['week_{}'.format(dynasty_week)] = osa_results
                self.seasonal_elo_frame = pd.DataFrame(
                    {'week_0': osa_results}, index=self.dynasty_elo_frame.index
                )

            else:
                self._generate_dynasty()
                dynasty_week = 0

        return self.dynasty_elo_frame['week_{}'.format(dynasty_week)]

    def _run(self, scoreboard: pd.DataFrame, week: int, overwrite: bool = True) -> pd.Series:
            complete = False
            if not overwrite:
                complete = bool(self.seasonal_elo_frame.get('week_{}'.format(week)))
            if not complete:
                self._run_elo(scoreboard, week=week)


    def generate(self):
        if self.is_dynasty:
            self._generate_dynasty()
        else:
            self._generate()

    def run(self, week: int,scoreboard: pd.DataFrame = None,  overwrite: bool = True):
        self._unload()
        if self.loaded:
            if week:
                if self.is_dynasty:
                    return self._run_dynasty(scoreboard, week, overwrite)
                else:
                    return self._run(scoreboard, week, overwrite)
            else:
                if self.is_dynasty:
                    return self._run_dynasty(scoreboard, week, overwrite)
                else:
                    return self._generate()
        else:
            raise AssertionError


class NFLCalculator(Calculator):

    def _run_elo(self, scoreboard, week: int = None, dynasty_week: int = None):
        scores = scoreboard.scores.values
        s_elo_vec = self.seasonal_elo_frame['week_{}'.format(week - 1)]
        s_res_elos = median_elo_calc(scores, s_elo_vec)
        self.seasonal_elo_frame['week_{}'.format(week)] = s_res_elos
        if dynasty_week:
            d_elo_vec = self.dynasty_elo_frame['week_{}'.format(dynasty_week - 1)]
            d_res_elos = median_elo_calc(scores, d_elo_vec)
            self.dynasty_elo_frame['week_{}'.format(dynasty_week)] = d_res_elos