from datetime import date, datetime, time
from typing import TYPE_CHECKING

from ..exceptions import DateNotInSeason
from .base import FantraxBaseObject
from .player import Player

if TYPE_CHECKING:
    from .league import League

_WEEKDAYS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


class Game(FantraxBaseObject):
    """Represents a single Game.

    Attributes:
        league (League): The League instance this object belongs to.
        id (str): Game ID.
        player (Player): Player to view this game from.
        date (date): The date this game is played.
        opponent (str): Short Name of the opponent.
        time (time): Start time of the (first) game if it hasn't been played yet.
        times (list[time]): All start times on this date; more than one for a doubleheader.
        home (bool): Is Player Home?
        away (bool): Is Player Away?

    """

    _data: dict

    def __init__(self, league: "League", player: Player, game_date: str, data: dict) -> None:
        super().__init__(league, data)
        self.id: str = self._data["eventId"]
        self.player: Player = player
        league_start = self.league.start_date.date()
        league_end = self.league.end_date.date()
        # The game date carries no year; seasons span a year boundary, so try the start
        # year then the end year. Parsing is wrapped because a date like Feb 29 raises
        # ValueError against a non-leap candidate year before the other year is tried.
        self.date: date | None = None
        for year in (self.league.start_date.year, self.league.end_date.year):
            try:
                candidate = datetime.strptime(f"{game_date} {year}", "%a %m/%d %Y").date()
            except ValueError:
                continue
            if league_start <= candidate <= league_end:
                self.date = candidate
                break
        if self.date is None:
            raise DateNotInSeason(game_date)

        self.time: time | None = None
        self.times: list[time] = []
        parts = data["content"].removesuffix(" F").split("\u003cbr/\u003e")
        if ":" in parts[1]:
            # Single game: parts == ["<opp>", "<Weekday> <Time>"]. Doubleheader (baseball):
            # parts == ["<opp> <Weekday>", "<Time1>", "<Time2>"] -- the weekday moves into
            # parts[0] and each later part is one start time.
            opponent = parts[0].strip()
            tokens = opponent.split(" ")
            if len(tokens) > 1 and tokens[-1] in _WEEKDAYS:
                opponent = " ".join(tokens[:-1])
            self.opponent: str = opponent
            if self.opponent.startswith("@"):
                # "@OPP": the player's team is visiting, so the opponent is the home team.
                self.opponent = self.opponent[1:]
                home = self.opponent
            else:
                # "OPP": the player's team is hosting.
                home = self.player.team_short_name

            # The time is the last whitespace token of each part that carries one.
            self.times = [datetime.strptime(part.split(" ")[-1], "%I:%M%p").time() for part in parts[1:] if ":" in part]
            self.time = self.times[0] if self.times else None
        else:
            # Played game "<away> <score><br/>@<home> <score>": the "@" side (parts[1]) is home.
            away_team = "".join(i for i in parts[0] if not i.isdigit() and i not in [" ", "@"])
            home = "".join(i for i in parts[1] if not i.isdigit() and i not in [" ", "@"])
            self.opponent = away_team if home == self.player.team_short_name else home
        self.home: bool = home == self.player.team_short_name
        self.away: bool = home != self.player.team_short_name

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Game):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(("Game", self.id))

    def __str__(self) -> str:
        return f"[{self.id}:{f'{self.opponent} @{self.player.team_short_name}' if self.home else f'{self.player.team_short_name} @{self.opponent}'}{f' {self.time}' if self.time else ''}]"
