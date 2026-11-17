from datetime import datetime
from typing import TYPE_CHECKING

from .base import FantraxBaseObject
from .player import Player
from .team import Team

if TYPE_CHECKING:
    from .league import League


class Transaction(FantraxBaseObject):
    """Represents a single Transaction.

    Attributes:
        league (League): The League instance this object belongs to.
        id (str): Transaction ID.
        team (Team): Team who made the Transaction.
        date (datetime): Transaction Date.
        period (int | None): Scoring period the transaction was processed in, if reported.
        executed (bool): True when every move in the transaction was executed (e.g. a
            waiver claim that succeeded rather than being cancelled).
        players (list[TransactionPlayer]): Players in the Transaction.

    """

    def __init__(self, league: "League", data: list[dict]) -> None:
        super().__init__(league, data)
        first = self._data[0]
        cells = first["cells"]
        self.id: str = first["txSetId"]
        self.team: Team = self.league.team(cells[0]["teamId"])
        self.date: datetime = datetime.strptime(cells[1]["content"], "%a %b %d, %Y, %I:%M%p")
        period = cells[2]["content"].strip() if len(cells) > 2 else ""
        self.period: int | None = int(period) if period.isdigit() else None
        self.players: list[TransactionPlayer] = [TransactionPlayer(self.league, row) for row in self._data]
        self.executed: bool = all(p.executed for p in self.players)

    def __str__(self) -> str:
        return str(self.players)


class TransactionPlayer(Player):
    """Represents a single Player from a Transaction.

    Attributes:
        league (League): The League instance this object belongs to.
        id (str): Player ID.
        name (str): Player Name.
        short_name (str): Player Short Name.
        team_name (str): Team Name.
        team_short_name (str): Team Short Name.
        pos_short_name (str): Player Positions.
        positions (list[Position]): Player Positions.
        all_positions (list[Position]): Positions Player can be placed into.
        day_to_day (bool): Player Day-to-Day.
        out (bool): Player Out.
        injured_reserve (bool): Player on Injured Reserve.
        suspended (bool): Player Suspended.
        injured (bool): Player either Day-to-Day, Out, or on Injured Reserve.
        type (str): Transaction Type ("WW"/"FA" for claims, otherwise the transaction
            code such as "DROP"/"ADD").
        transaction_type (str): Human-readable transaction type (e.g. "Drop", "Claim").
        executed (bool): True when this move was executed rather than cancelled.
        result (str): Result text for this move (e.g. "Executed").
    """

    def __init__(self, league: "League", row: dict) -> None:
        super().__init__(league, row["scorer"])
        code = row["transactionCode"]
        self.type: str = row["claimType"] if code == "CLAIM" else code
        self.transaction_type: str = row.get("transactionType", self.type)
        self.executed: bool = bool(row.get("executed", False))
        self.result: str = row.get("result", {}).get("content", "")

    def __str__(self) -> str:
        return f"{self.type} {self.name}"
