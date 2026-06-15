from ..basics import ROTO_COLS
from elo_system._vendor.fantraxapi.objs import ScoringPeriodResult
import pandas as pd
import numpy as np


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


def set_formatter(platform: str):
    if platform == 'fantrax':
        return fantrax_formatter
    # elif platform == 'sleeper':
    #     pass
    else:
        raise ValueError(f'Unknown platform: {platform}')
