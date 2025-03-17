from .formatter import Formatter
from .basics import median_elo_calc, score_elo_calc, bin_elo_calc, trin_elo_calc
import pandas as pd
import numpy as np


class Calculator(Formatter):

    is_dynasty = False
    loaded = False
    osa_factor = .4
    k = 60

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

    def _load(self) -> None:
        super()._load()
        self.is_dynasty = self.league_config.get('is_dynasty', False)
        self.osa_factor = self.league_config.get('osa_factor', self.osa_factor)
        self.k = self.league_config.get('k', self.k)

    def load(self, ratings_frames: dict[pd.DataFrame] = None) -> None:
        self._load()
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

    def publish(self):
        if self.is_dynasty:
            df = self.dynasty_elo_frame.copy()
        else:
            df = self.seasonal_elo_frame.copy()
        return df


class NFLCalculator(Calculator):

    def _run_elo(self, scoreboard, week: int = None, dynasty_week: int = None):
        scores = scoreboard.scores.values
        s_elo_vec = self.seasonal_elo_frame['week_{}'.format(week - 1)]
        s_res_elos = median_elo_calc(scores, s_elo_vec, self.k)
        self.seasonal_elo_frame['week_{}'.format(week)] = s_res_elos
        if dynasty_week:
            d_elo_vec = self.dynasty_elo_frame['week_{}'.format(dynasty_week - 1)]
            d_res_elos = median_elo_calc(scores, d_elo_vec)
            self.dynasty_elo_frame['week_{}'.format(dynasty_week)] = d_res_elos

class NBACalculator(Calculator):
    scoring = 'score'

    def __init__(self, league_config: dict = dict()) -> None:
        super().__init__(league_config=league_config)
        self._load()
        if self.scoring == 'score':
            self.calculator = score_elo_calc
        elif self.scoring == 'binary':
            self.calculator = bin_elo_calc
        elif self.scoring == 'trinary':
            self.calculator = trin_elo_calc

    def _load(self) -> None:
        super()._load()
        self.scoring = self.league_config.get('scoring', self.scoring)

    def _run_elo(self, scoreboard, week: int = None, dynasty_week: int = None):
        last_week = 'week_{}'.format(week - 1)
        new_week = dict()
        calced = set()
        true_scores = scoreboard['true_score']
        new_dynasty = dict()
        for player_1_id in scoreboard.index:
            if player_1_id not in calced:
                player_2_id = scoreboard['opponent'][player_1_id]

                #                 _logger.info('Calculating for %s vs. %s', player_1, player_2)
                player_1_data = [
                    self.seasonal_elo_frame.loc[player_1_id, last_week] * 1.0, true_scores[player_1_id]
                ]
                player_2_data = [
                    self.seasonal_elo_frame.loc[player_2_id, last_week] * 1.0, true_scores[player_2_id]
                ]
                scores = self.calculator(player_1_data, player_2_data, self.k)
                #                 _logger.info('Adding scores to new week')
                new_week.update({player_1_id: scores[0]})
                new_week.update({player_2_id: scores[1]})
                calced.add(player_1_id)
                calced.add(player_2_id)
                if dynasty_week:
                    d_last_week = 'week_{}'.format(dynasty_week - 1)
                    player_1_data = [
                        self.dynasty_elo_frame.loc[player_1_id, d_last_week] * 1.0, true_scores[player_1_id]
                    ]
                    player_2_data = [
                        self.dynasty_elo_frame.loc[player_2_id, d_last_week] * 1.0, true_scores[player_2_id]
                    ]
                    scores = self.calculator(player_1_data, player_2_data, self.k)
                    new_dynasty.update({player_1_id: scores[0]})
                    new_dynasty.update({player_2_id: scores[1]})
        #         _logger.info('Writing to frame')
        for k, v in self.seasonal_elo_frame[last_week].items():
            if not new_week.get(k):
                new_week.update({k: v})
        self.seasonal_elo_frame['week_{}'.format(week)] = pd.Series(new_week)
        if dynasty_week:
            for k, v in self.dynasty_elo_frame[d_last_week].items():
                if not new_dynasty.get(k):
                    new_dynasty.update({k: v})
            self.dynasty_elo_frame['week_{}'.format(dynasty_week)] = pd.Series(new_dynasty)


