from basics.common_classes import EloBase
import pandas as pd


class Formatter(EloBase):

    members = dict()
    teams = dict()
    sport = None

    def _unload(self) -> None:
        super()._unload()
        self.sport = self.league_config.get('sport', 'nfl')
        self.members = self.league_config.get('members', dict())
        id_teams = self.league_config.get('teams', dict())
        self.teams = {person: id_teams[team_id] for team_id, person in self.members.items()}


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