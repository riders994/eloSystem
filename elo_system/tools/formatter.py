from .basics import EloBase
from fantraxapi import ScoringPeriod
import pandas as pd
import numpy as np

ROTO_COLS = {
    'FG%', 'FT%', '3PTM', 'PTS', 'REB', 'AST', 'ST', 'BLK', 'TO'
}


class Formatter(EloBase):

    members = dict()
    teams = dict()
    sport = None

    def _load(self) -> None:
        super()._load()
        self.sport = self.league_config.get('sport', 'nfl')
        self.members = self.league_config.get('members', dict())
        id_teams = self.league_config.get('teams', dict())
        self.teams = {person: id_teams.get(team_id) for team_id, person in self.members.items()}


class SleeperFormatter(Formatter):

    def nfl(self, scoreboard):
        dename = {self.teams[user]: team_id for team_id, user in self.members.items()}
        return {
            dename[team['roster_id']]: team['points'] for team in scoreboard
        }


    def run(self, scoreboard: list[dict]) -> pd.DataFrame:
        if self.sport == 'nfl':
            print(self.nfl(scoreboard))
            return pd.DataFrame(
                {'scores': self.nfl(scoreboard)}
            )

class FantraxFormatter(Formatter):
    roto = False

    def _load(self) -> None:
        super()._load()
        self.roto = self.league_config.get('roto', False)

    def _roto(self, scoreboard: pd.DataFrame):
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

    def nba(self, scoreboard: ScoringPeriod):
        matchup_dict = dict()
        for matchup in scoreboard.matchups.values():
            matchup_dict.update({
                matchup.home.team_id: matchup.home_categories,
                matchup.away.team_id: matchup.away_categories,
            })
        board_df = pd.DataFrame.from_dict(matchup_dict, orient='index').rename(columns={'Pts': 'true_score'})
        board_df['true_score'] = board_df['true_score']/9
        if self.roto:
            return self._roto(board_df)
        return board_df

    def nfl(self, scoreboard):
        pass

    def run(self, scoreboard: ScoringPeriod) -> pd.DataFrame:
        if self.sport == 'nfl':
            pass
        elif self.sport == 'nba':
            return self.nba(scoreboard)