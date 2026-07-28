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

def _week_columns(elo_frame: pd.DataFrame, week: int | None) -> tuple[int, str, str]:
    if week is None:
        week = elo_frame.shape[1] - 1
    return week, WEEK_STR.format(week), WEEK_STR.format(week - 1)


def _h2h_week(
        elo_frame: pd.DataFrame,
        score_frame: pd.DataFrame,
        last_week: str,
        elo_func,
        k: float,
) -> dict:
    """Rate every member against the one they actually played that week.

    Members whose 'opponent' is not a member id -- a bye, or a playoff round
    they sat out -- are left out of the returned mapping, and so carry their
    previous rating forward.
    """
    new_week = dict()
    calced = set()
    true_scores = score_frame['true_score']

    for player_1_id in score_frame.index:
        if player_1_id not in calced:
            player_2_id = score_frame['opponent'][player_1_id]
            if isinstance(player_2_id, str):
                if len(player_1_id):
                    player_1_data = [
                        elo_frame.loc[player_1_id, last_week] * 1.0, true_scores[player_1_id]
                    ]
                    player_2_data = [
                        elo_frame.loc[player_2_id, last_week] * 1.0, true_scores[player_2_id]
                    ]
                    scores = elo_func(player_1_data, player_2_data, k)
                    new_week.update({player_1_id: scores[0]})
                    new_week.update({player_2_id: scores[1]})
                    calced.add(player_1_id)
                    calced.add(player_2_id)
    return new_week


def _median_week(
        elo_frame: pd.DataFrame,
        score_frame: pd.DataFrame,
        last_week: str,
        k: float,
) -> dict:
    """Rate every member against the league's median score that week.

    Restricted to members the elo frame already knows about, and indexed by
    member rather than by position, so a scoreboard whose row order differs
    from the frame's still lines up.
    """
    rated = [member for member in score_frame.index if member in elo_frame.index]
    if not rated:
        return dict()
    scores = score_frame.loc[rated, 'scores'].values
    elos = elo_frame.loc[rated, last_week].astype(float)
    return dict(median_elo_calc(scores, elos, k).items())


def _write_week(elo_frame: pd.DataFrame, new_week: dict, this_week: str, last_week: str) -> pd.DataFrame:
    """Add the week's column, carrying forward anyone who was not rated."""
    for member_id, rating in elo_frame[last_week].items():
        if new_week.get(member_id) is None:
            new_week.update({member_id: rating})
    elo_frame[this_week] = pd.Series(new_week)
    return elo_frame


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
    week, this_week, last_week = _week_columns(elo_frame, week)
    if not overwrite:
        if this_week in elo_frame.columns:
            return elo_frame

    new_week = _h2h_week(elo_frame, score_frame, last_week, elo_func, k)

    return _write_week(elo_frame, new_week, this_week, last_week)

def nfl_calculator(
        elo_frame: pd.DataFrame,
        score_frame: pd.DataFrame,
        week: int | None = None,
        overwrite: bool = False,
        k: float = 60,
        scoring: str = 'median',
) -> pd.DataFrame:
    """Rate a week of head-to-head football.

    'median' -- the default -- scores every team against the league median
    that week, ignoring who they were scheduled against. 'default' scores
    each matchup head to head on the two teams' share of the points.

    The parameter order matches nba_calculator's, because EloLeague._run_one
    calls whichever it holds positionally.
    """
    if scoring not in {'default', 'median'}:
        raise ValueError
    week, this_week, last_week = _week_columns(elo_frame, week)
    if not overwrite:
        if this_week in elo_frame.columns:
            return elo_frame

    if scoring == 'median':
        new_week = _median_week(elo_frame, score_frame, last_week, k)
    else:
        new_week = _h2h_week(elo_frame, score_frame, last_week, score_elo_calc, k)

    return _write_week(elo_frame, new_week, this_week, last_week)

def set_calculator(league_type: str):
    if league_type == 'nba':
        return nba_calculator
    elif league_type == 'nfl':
        return nfl_calculator
    else:
        raise ValueError('Unknown league type: {}'.format(league_type))
