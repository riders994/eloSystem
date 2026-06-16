import pandas as pd

from ..basics import (
    median_elo_calc,
    score_elo_calc,
    bin_elo_calc,
    trin_elo_calc,
    WEEK_STR
)


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
        k: float = 60,
        scoring: str = 'default',
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
        overwrite: bool = False,
        k: float = 60,
):
    if scoring not in {'default', 'median'}:
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

def set_calculator(league_type: str):
    if league_type == 'nba':
        return nba_calculator
    elif league_type == 'nfl':
        return nfl_calculator
    else:
        raise ValueError('Unknown league type: {}'.format(league_type))
