import numpy as np
import pandas as pd

from ..basics import ROTO_COLS
from elo_system._vendor.fantraxapi.objs import ScoringPeriodResult


def roto_calc(scoreboard: pd.DataFrame) -> pd.DataFrame:
    stats = []
    for col in ROTO_COLS:
        array = scoreboard[col].values
        temp = array.argsort()
        ranks = np.empty_like(temp)
        ranks[temp] = np.arange(len(array))
        if col == 'TO':
            ranks = max(ranks) - ranks
        ranks += 1
        stats.append(ranks)
    rotos = np.array(stats).sum(axis=0)
    scoreboard['roto'] = rotos
    temp = rotos.argsort()
    ranks = np.empty_like(temp)
    ranks[temp] = np.arange(len(rotos) - 1, -1, -1)
    scoreboard['roto_rank'] = ranks + 1
    return scoreboard

def fantrax_formatter(league_type: str, scoreboard: ScoringPeriodResult, roto: bool = False) -> pd.DataFrame:
    if league_type == 'nba':
        matchup_dict = dict()
        for matchup in scoreboard.matchups.values():
            matchup_dict.update({
                matchup.home.owners: matchup.home_categories,
                matchup.away.owners: matchup.away_categories,
            })
        board_df = pd.DataFrame.from_dict(matchup_dict, orient='index').rename(columns={'Pts': 'true_score'})
        board_df['true_score'] = board_df['true_score'] / 9
        if roto:
            return roto_calc(board_df)
        else:
            return board_df
    else:
        return pd.DataFrame()


def sleeper_formatter(league_type: str, scoreboard: list[dict], roto: bool = False) -> pd.DataFrame:
    """Turn a week of Sleeper matchups into a score frame indexed by owner id.

    Sleeper reports one flat record per roster, paired up by a shared
    ``matchup_id``. The frame carries what both NFL scoring modes need:
    ``scores`` (raw points) for the median/all-play calculation, and
    ``true_score``/``opponent`` for the head-to-head one.

    Rosters idle in a given week -- Sleeper leaves ``matchup_id`` null for
    teams not in that round of the playoff bracket -- keep their points but
    get no opponent, so the median mode still sees them and the head-to-head
    mode skips them.
    """
    if league_type != 'nfl':
        return pd.DataFrame()

    # Group the rosters that share a matchup_id. A null id means "not playing".
    pairings = dict()
    for entry in scoreboard:
        if (matchup_id := entry.get('matchup_id')) is not None:
            pairings.setdefault(matchup_id, []).append(entry)

    opponent_of = dict()
    for entries in pairings.values():
        if len(entries) == 2:
            first, second = entries
            opponent_of[first['roster_id']] = second
            opponent_of[second['roster_id']] = first

    rows = dict()
    for entry in scoreboard:
        points = entry.get('points') or 0.0
        opponent = opponent_of.get(entry['roster_id'])
        if opponent is None:
            true_score, opponent_id = np.nan, None
        else:
            opponent_points = opponent.get('points') or 0.0
            total = points + opponent_points
            # An unplayed week scores 0-0 for both sides; call that a draw
            # rather than dividing by zero.
            true_score = 0.5 if total == 0 else points / total
            opponent_id = str(opponent['roster_id'])
        rows[entry['owner_id']] = {
            'scores': points,
            'true_score': true_score,
            'opponent': opponent_id,
        }

    return pd.DataFrame.from_dict(rows, orient='index')


def set_formatter(platform: str):
    if platform == 'fantrax':
        return fantrax_formatter
    elif platform == 'sleeper':
        return sleeper_formatter
    else:
        raise ValueError(f'Unknown platform: {platform}')
