import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

from ..exceptions import DateNotInSeason
from .base import FantraxBaseObject
from .player import Player
from .team import Team

if TYPE_CHECKING:
    from .league import League


class Trade(FantraxBaseObject):
    """Represents a single Trade.

    Attributes:
        league (League): The League instance this object belongs to.
        proposed_by (Team): Team Trade Proposed By.
        proposed (datetime): Datetime Trade was Proposed.
        accepted (datetime): Datetime Trade was Accepted.
        executed (datetime): Datetime Trade will be Executed.
        moves (list[TradeDraftPick | TradePlayer]): List of Moves in this Trade.

    """

    _data: dict

    def __init__(self, league: "League", data: dict) -> None:
        super().__init__(league, data)
        info = {i["name"]: i["value"] for i in self._data["usefulInfo"]}

        self.trade_id: str = self._data["txSetId"]
        self.proposed_by = self.league.team(self._data["creatorTeamId"])
        self.proposed: datetime = self._parse_datetime(info["Proposed"])
        self.accepted: datetime = self._parse_datetime(info["Accepted"])
        self.executed: datetime = self._parse_datetime(info["To be executed"])
        self.moves: list[TradeDraftPick | TradePlayer] = []
        for move in self._data["moves"]:
            self.moves.append(TradeDraftPick(self, move) if "draftPick" in move else TradePlayer(self, move))

    # Fantrax stamps trade times in US Eastern, so the trailing token is EST in
    # winter and EDT in summer (and could be any North-American zone abbreviation).
    # The string carries no year, so strip the zone token and try each season-boundary
    # year. The token is matched as a zone (ends in "T", or UTC/GMT) so the AM/PM that
    # precedes it is never clobbered.
    _TZ_SUFFIX = re.compile(r"\s+(?:[A-Z]{1,3}T|UTC|GMT)\s*$")

    def _parse_datetime(self, data: str) -> datetime:
        base = self._TZ_SUFFIX.sub("", data.strip())
        for year in (self.league.start_date.year, self.league.end_date.year):
            try:
                parsed = datetime.strptime(f"{base} {year}", "%b %d, %I:%M %p %Y")
            except ValueError:
                continue
            if self.league.start_date <= parsed <= self.league.end_date:
                return parsed
        raise DateNotInSeason(data)

    def __str__(self) -> str:
        return "\n".join([str(m) for m in self.moves])


class TradeItem(FantraxBaseObject, ABC):
    _data: dict

    def __init__(self, trade: "Trade", data: dict) -> None:
        super().__init__(trade.league, data)
        self.trade: Trade = trade
        self.from_team: Team = self.league.team(self._data["from"]["teamId"])
        self.to_team: Team = self.league.team(self._data["to"]["teamId"])

    def __str__(self) -> str:
        return f"From: {self.from_team.name} To: {self.to_team.name} {self._item_description()}"

    @abstractmethod
    def _item_description(self) -> str:
        pass


class TradeDraftPick(TradeItem):
    """Represents a single Traded Draft Pick.

    Attributes:
        league (League): The League instance this object belongs to.
        trade (Trade): The Trade instance this TradeDraftPick belongs to.
        from_team (Team): Fantasy Team Traded From.
        to_team (Team): Fantasy Team Traded To.
        round (int): Draft Pick Round.
        year (int): Draft Pick Year.
        owner (Team): Fantasy Team of Original Pick Owner.

    """

    def __init__(self, trade: Trade, data: dict) -> None:
        super().__init__(trade, data)
        self.round: int = self._data["draftPick"]["round"]
        self.year: int = self._data["draftPick"]["year"]
        self.owner: Team = self.league.team(self._data["draftPick"]["origOwnerTeam"]["id"])

    def _item_description(self) -> str:
        return f"Pick: {self.year}, Round {self.round} ({self.owner.name})"


class TradePlayer(TradeItem):
    """Represents a single Traded Player.

    Attributes:
        league (League): The League instance this object belongs to.
        trade (Trade): The Trade instance this TradePlayer belongs to.
        from_team (Team): Fantasy Team Traded From.
        to_team (Team): Fantasy Team Traded To.
        player (Player): The Player instance this TradePlayer belongs to.
        fantasy_points_per_game (float): Fantasy Points Per Game.
        total_fantasy_points (float): Total Fantasy Points.

    """

    def __init__(self, trade: Trade, data: dict) -> None:
        super().__init__(trade, data)
        self.player: Player = Player(self.league, data["scorer"])
        self.fantasy_points_per_game: float = self._data["scorePerGame"]
        self.total_fantasy_points: float = self._data["score"]

    def _item_description(self) -> str:
        return f"TradePlayer: {self.player.name} {self.player.pos_short_name} - {self.player.team_short_name} {self.fantasy_points_per_game} {self.total_fantasy_points}"
