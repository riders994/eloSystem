from basics.common_funcs import median_elo_calc
import pandas as pd


class Calculator:

    def __init__(self, elo_frame):
        self.elo_frame = elo_frame


class FootballCalc(Calculator):
    def run(self, scoreboard, week: int, overwrite: bool = True) -> pd.Series:
        complete = False
        if not overwrite:
            complete = bool(self.elo_frame.get('week_{}'.format(week)))
        if complete:
            elo_vec = self.elo_frame['week_{}'.format(week - 1)]
            res_elos = median_elo_calc(scoreboard, elo_vec)
            self.elo_frame['week_{}'.format(week)] = res_elos
        return self.elo_frame['week_{}'.format(week)]


class BasketballCalc(Calculator):
    pass
