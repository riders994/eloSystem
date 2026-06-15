from datetime import date
from typing import TYPE_CHECKING

from .base import FantraxBaseObject
from .player import Player
from .position import PositionCount
from .roster import Roster

if TYPE_CHECKING:
    from .league import League


class Team(FantraxBaseObject):
    """Represents a single Team.

    Each season is a separate Fantrax league with brand-new team IDs, and owners can
    rename their team (name and short) at any time, so none of those identify a team
    across seasons. Use owners for that; logo can corroborate (custom-uploaded logos
    persist across seasons, while stock logos are shared between teams).

    Attributes:
        league (League): The League instance this object belongs to.
        id (str): Team ID.
        name (str): Team Name.
        short (str): Team Short Name.
        logo (str): Team Logo URL.
        commissioner (bool): Is the Team owned by a League commissioner? Not every data source reports this; it defaults to False.
        owners (str): Owner account name(s). Fetched lazily with one request on first access, then cached. Empty for placeholder teams (e.g. the Bye slot in an odd-sized playoff bracket), which aren't league members.

    """

    def __init__(self, league: "League", team_id: str, data: dict) -> None:
        super().__init__(league, data)
        self.id: str = team_id
        self.name: str = self._data["name"]
        self.short: str = self._data["shortName"]
        self.commissioner: bool = self._data.get("commissioner", False)
        self._owners: str | None = None
        if "logoUrl512" in self._data:
            self.logo: str = self._data["logoUrl512"]
        elif "logoUrl256" in self._data:
            self.logo: str = self._data["logoUrl256"]
        else:
            self.logo: str = self._data["logoUrl128"]

    @property
    def owners(self) -> str:
        if self._owners is None:
            if self.id not in self.league.team_lookup:
                # Placeholder teams (e.g. a bracket's Bye slot) have no roster page to ask
                self._owners = ""
                return self._owners
            from .. import api

            response = api.get_team_roster_position_counts(self.league, self.id)
            self._owners = response["teamHeadingInfo"]["owners"]["value"]
            # that request rebuilt league.teams; share the cache with the new instance
            current = self.league.team_lookup.get(self.id)
            if current is not None:
                current._owners = self._owners
        return self._owners

    def __str__(self) -> str:
        return self.name

    def position_counts(self, scoring_period_number: int | None = None) -> dict[str, PositionCount]:
        """Returns a Dictionary of PositionCount objects that represents the positions used for a specific period or the latest period's standings when scoring_period_number is None.

        Args:
            scoring_period_number (int | None): Period Number, defaults to `None`.

        Returns:
            dict[str, PositionCount]: Dictionary of Position Short Names to PositionCount objects.

        """
        return self.league.position_counts(self.id, scoring_period_number=scoring_period_number)

    def live_scores(self, score_date: date) -> list["Player"]:
        """Returns a list of Player objects with scores for that day.

        Args:
            score_date (date): Date of the Live Scoring.

        Returns:
            list[Player]: List of Player objects with scores for that day.

        """
        return self.league.live_scores(score_date)[self.id]

    def roster(self, period_number: int | None = None) -> Roster:
        """Returns a Roster object that represents the Team's roster.

        Args:
            period_number (int | None): Daily Period Number, defaults to None.

        Returns:
            Roster: Roster object that represents the Team's roster.

        """
        return self.league.team_roster(team_id=self.id, period_number=period_number)
