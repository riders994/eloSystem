from .basics import (
    median_elo_calc,
    score_elo_calc,
    bin_elo_calc,
    trin_elo_calc,
    EloBase,
    WEEK_STR
)
import pandas as pd
import numpy as np

from typing import Any


def offseason_adjustment(ratings: pd.Series, factor: float = 0.4) -> pd.Series:
    if factor >= 1:
        raise ValueError
    if factor <= 0:
        raise ValueError
    return ((ratings - 1500) * (1 - factor)) + 1500

def nba_calculator(
        elo_frame: pd.DataFrame,
        score_frame: pd.DataFrame,
        week: int | None = None,
        overwrite: bool = False,
        scoring: str = 'default',
        k: float = 60,
) -> pd.DataFrame:
    if scoring == 'default':
        elo_func = score_elo_calc
    elif scoring == 'trinary':
        elo_func = trin_elo_calc
    elif scoring == 'binary':
        elo_func = bin_elo_calc
    else:
        raise ValueError
    if week is None:
        week = elo_frame.shape[1] - 1
    this_week = WEEK_STR.format(week)
    last_week = WEEK_STR.format(week - 1)
    if not overwrite:
        if this_week in elo_frame.columns:
            return elo_frame

    new_week = dict()
    calced = set()
    true_scores = score_frame['true_score']

    for player_1_id in score_frame.index:
        if player_1_id not in calced:
            player_2_id = score_frame['opponent'][player_1_id]
            if isinstance(player_2_id, str):
                if len(player_1_id):
                    #                 _logger.info('Calculating for %s vs. %s', player_1, player_2)
                    player_1_data = [
                        elo_frame.loc[player_1_id, last_week] * 1.0, true_scores[player_1_id]
                    ]
                    player_2_data = [
                        elo_frame.loc[player_2_id, last_week] * 1.0, true_scores[player_2_id]
                    ]
                    scores = elo_func(player_1_data, player_2_data, k)
                    #                 _logger.info('Adding scores to new week')
                    new_week.update({player_1_id: scores[0]})
                    new_week.update({player_2_id: scores[1]})
                    calced.add(player_1_id)
                    calced.add(player_2_id)
        #         _logger.info('Writing to frame')
    for k, v in elo_frame[last_week].items():
        if new_week.get(k) is None:
            new_week.update({k: v})
    elo_frame[this_week] = pd.Series(new_week)

    return  elo_frame

def nfl_calculator(
        elo_frame: pd.DataFrame,
        score_frame: pd.DataFrame,
        scoring: str = 'default',
        week: int | None = None,
        osa_factor: float = 0.4,
        k: float = 60,
        overwrite: bool = False,
):
    if scoring in {'default', 'median'}:
        elo_func = median_elo_calc
    else:
        raise ValueError
    if week is None:
        week = score_frame.shape[1] - 1
    this_week = WEEK_STR.format(week)
    last_week = WEEK_STR.format(week - 1)
    if not overwrite:
        if this_week in elo_frame.columns:
            return elo_frame



    scores = score_frame.scores.values
    s_elo_vec = elo_frame[last_week]
    s_res_elos = median_elo_calc(scores, s_elo_vec, k)
    elo_frame[this_week] = s_res_elos

    return elo_frame


class nCalculator(EloBase):

    is_dynasty = False
    osa_factor = .4
    k = 60

    team_elo_frame = None
    dynasty_elo_frame = None
    seasonal_elo_frame = None
    league_years = None

    def __init__(self, league_config: dict = dict()) -> None:
        super().__init__(league_config=league_config)

    def _elo_gen(self) -> pd.DataFrame:
        return pd.DataFrame(
                    {'week_0': [1500] * len(self.members)}, index=self.members.keys()
                )

    def _generate(self, schemas: list = None, schema: str = 'seasonal_elo_frame') -> None:
        if isinstance(schemas, list):
            for s in schemas:
                self._generate(schema=s)
        dim = len(self.members)
        if dim:
            setattr(self, schema, self._elo_gen())

    def _load(self) -> None:
        super()._load()
        self.is_dynasty = self.league_config.get('is_dynasty', False)
        self.osa_factor = self.league_config.get('osa_factor', self.osa_factor)
        self.league_years = self.league_config.get('league_years', self.league_years)
        self.k = self.league_config.get('k', self.k)

    def _dump(self) -> None:
        super()._dump()
        self.league_config['is_dynasty'] = self.is_dynasty
        self.league_config['osa_factor'] = self.osa_factor
        self.league_config['league_years'] = self.league_years
        self.league_config['k'] = self.k

    def load(self, ratings_frames: dict[Any, Any] = None) -> None:
        self._load()
        if ratings_frames:
            self.load_ratings(ratings_frames)
        self.loaded = True

    def clear_frames(self):
        self.team_elo_frame = None
        self.dynasty_elo_frame = None
        self.seasonal_elo_frame = None

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
            if self.dynasty_elo_frame is not None:
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
                complete = isinstance(self.seasonal_elo_frame.get('week_{}'.format(week)), pd.Series)
            if not complete:
                self._run_elo(scoreboard, week=week)


    def generate(self):
        if self.is_dynasty:
            self._generate_dynasty()
        else:
            self._generate()
        self.loaded = True


    def run(self, week: int, scoreboard: pd.DataFrame = None,  overwrite: bool = True):
        self._load()
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
            if week == 0:
                return self.generate()
            raise AssertionError
