from datetime import date
from typing import TYPE_CHECKING

from ..exceptions import NotTeamInLeague
from ._parse import parse_float
from .base import FantraxBaseObject
from .game import Game
from .player import Player
from .position import Position

if TYPE_CHECKING:
    from .league import League
    from .team import Team


class Roster(FantraxBaseObject):
    """Represents a Player's Roster.

    Attributes:
        league (League): The League instance this object belongs to.
        team (Team): Team who made te Transaction.
        period_number (int): Daily Period Number.
        period_date (date): Daily Period Date.
        active (int): Number of Players in Active Slots.
        active_max (int): Max Number of Players that can be in Active Slots.
        reserve (int): Number of Players in Reserve Slots.
        reserve_max (int): Max Number of Players that can be in Reserve Slots.
        injured (int): Number of Players in Injured Slots.
        injured_max (int): Max Number of Players that can be in Injured Slots.
        rows (list[RosterRow]): List of RosterRows in the Roster.
        salary (SalaryInfo | None): Team salary-cap summary, or None for non-salary leagues.
        draft_picks (list[RosterDraftPick]): Future draft picks the team owns.
        cap_hit_penalties (list[CapHitPenalty]): Dead-money cap hits charged to the team.

    """

    _data: dict

    def __init__(self, league: "League", team_id: str, data: dict) -> None:
        super().__init__(league, data[0])
        self.team: Team = self.league.team(team_id)
        self.period_number: int = int(self._data["displayedSelections"]["displayedPeriod"])
        self.period_date: date = self.league.scoring_dates[self.period_number]
        misc: dict = self._data.get("miscData", {})
        lookup: dict[str, dict] = {d["name"]: d for d in misc.get("statusTotals", [])}
        self.active: int = int(lookup["Active"]["total"]) if "Active" in lookup else 0
        self.active_max: int = int(lookup["Active"]["max"]) if "Active" in lookup else 0
        self.reserve: int = int(lookup["Reserve"]["total"]) if "Reserve" in lookup else 0
        self.reserve_max: int = int(lookup["Reserve"]["max"]) if "Reserve" in lookup else 0
        self.injured: int = int(lookup["Inj Res"]["total"]) if "Inj Res" in lookup else 0
        self.injured_max: int = int(lookup["Inj Res"]["max"]) if "Inj Res" in lookup else 0
        salary_info = misc.get("salaryInfo")
        self.salary: SalaryInfo | None = SalaryInfo(self.league, salary_info) if salary_info else None
        self.draft_picks: list[RosterDraftPick] = [
            RosterDraftPick(self.league, year["year"], pick)
            for year in self._data.get("draftPicksData", {}).get("draftPicksPerYear", [])
            for pick in year.get("draftPickList", [])
        ]
        self.cap_hit_penalties: list[CapHitPenalty] = [CapHitPenalty(self.league, penalty) for penalty in self._data.get("capHitPenaltyData", {}).get("tableData", [])]
        self.rows = []
        for stats_group, schedule_group in zip(self._data["tables"], data[1]["tables"]):
            stats_header = stats_group["header"]["cells"]
            schedule_header = schedule_group["header"]["cells"]
            for stats_row, schedule_row in zip(stats_group["rows"], schedule_group["rows"]):
                if "posId" not in stats_row:
                    continue
                stuff = {"posId": stats_row["posId"], "future_games": {}, "total_fantasy_points": None, "fantasy_points_per_game": None, "salary": None, "contract_year": None, "age": None}
                if "scorer" in stats_row or stats_row["statusId"] == "1":
                    if "scorer" in stats_row:
                        stuff["scorer"] = stats_row["scorer"]
                        for header, cell in zip(schedule_header, schedule_row["cells"]):
                            if cell["content"] and "eventStr" in header and header["eventStr"]:
                                key = header["shortName"]
                                stuff["future_games"][key] = cell

                        for header, cell in zip(stats_header, stats_row["cells"]):
                            if "sortKey" in header:
                                match header["sortKey"]:
                                    case "SCORE":
                                        stuff["total_fantasy_points"] = float(cell["content"])
                                    case "FPTS_PER_GAME":
                                        stuff["fantasy_points_per_game"] = float(cell["content"])
                            # Salary/contract columns only exist in salary leagues; age is universal.
                            match header.get("key"):
                                case "salary":
                                    stuff["salary"] = parse_float(cell["content"]) if cell.get("content") else None
                                case "contract":
                                    stuff["contract_year"] = cell["content"] or None
                                case "age":
                                    stuff["age"] = int(cell["content"]) if cell.get("content", "").strip().isdigit() else None
                            if cell["content"] and "eventStr" in header and header["eventStr"]:
                                stuff["game_today"] = cell
                self.rows.append(RosterRow(self, stuff))

    def __str__(self) -> str:
        rows = "\n".join([str(r) for r in self.rows])
        return f"{self.team} Roster\n{rows}"


class RosterRow(FantraxBaseObject):
    """Represents a single Row on a Player's Roster.

    Attributes:
        league (League): The League instance this object belongs to.
        roster (Roster): The Roster instance this RosterRow belongs to.
        position (Position): The Position object associated with the RosterRow.
        player (Player | None): The Player in the RosterRow.
        total_fantasy_points (float | None): The Total Fantasy Points for the Player in the RosterRow.
        fantasy_points_per_game (float | None): The Fantasy Points Per Game for the Player in the RosterRow.
        salary (float | None): The Player's salary (salary-cap leagues only, else None).
        contract_year (str | None): The Player's contract year (salary-cap leagues only, else None).
        age (int | None): The Player's age, when the roster reports it.
        game_today (Game): Game for the Player in the RosterRow.
        future_games (dict[str, Game]): Dictionary of dates to future Games or the last game of the season if it's over.

    """

    _data: dict

    def __init__(self, roster: Roster, data: dict) -> None:
        super().__init__(roster.league, data)
        self.roster: Roster = roster
        self.position: Position = self.league.positions[self._data["posId"]]
        self.player: Player | None = Player(self.league, self._data["scorer"]) if "scorer" in self._data else None
        self.total_fantasy_points: float | None = self._data["total_fantasy_points"]
        self.fantasy_points_per_game: float | None = self._data["fantasy_points_per_game"]
        self.salary: float | None = self._data["salary"]
        self.contract_year: str | None = self._data["contract_year"]
        self.age: int | None = self._data["age"]
        # A roster row only carries games when it has a player (see Roster.__init__: the
        # game cells are collected inside the "scorer" block), so player is set here.
        self.game_today: Game | None = Game(self.league, self.player, roster.period_date.strftime("%a %m/%d"), self._data["game_today"]) if "game_today" in self._data and self.player is not None else None
        self.future_games: dict[str, Game] = {k: Game(self.league, self.player, k, v) for k, v in self._data["future_games"].items()} if self.player is not None else {}

    def __str__(self) -> str:
        return f"{self.position.short_name}: {self.player if self.player else 'Empty'}"


class SalaryInfo(FantraxBaseObject):
    """Team salary-cap summary for a roster period (salary-cap leagues only).

    Attributes:
        league (League): The League instance this object belongs to.
        cap (float | None): Total salary cap.
        used (float | None): Salary used.
        remaining (float | None): Salary remaining under the cap.
        floor (float | None): Salary floor the team must spend to.
        claim_budget (float | None): Remaining waiver/claim budget.

    """

    def __init__(self, league: "League", data: dict) -> None:
        super().__init__(league, data)
        by_key: dict[str, dict] = {item["key"]: item for item in data.get("info", []) if "key" in item}

        def value(key: str) -> float | None:
            return parse_float(by_key[key]["value"]) if key in by_key else None

        self.cap: float | None = value("salaryCap")
        self.used: float | None = value("salaryUsed")
        self.remaining: float | None = value("salaryRemaining")
        self.floor: float | None = value("salaryFloor")
        self.claim_budget: float | None = value("claimBudget")

    def __str__(self) -> str:
        return f"Salary {self.used}/{self.cap}"


class RosterDraftPick(FantraxBaseObject):
    """A future draft pick a team owns.

    Attributes:
        league (League): The League instance this object belongs to.
        year (int): Draft year.
        round (int): Draft round.
        original_owner (Team | str | None): Team the pick originally belonged to (differs
            from the current owner for a traded pick); the raw id when not a league member.

    """

    def __init__(self, league: "League", year: int, data: dict) -> None:
        super().__init__(league, data)
        self.year: int = year
        self.round: int = data["round"]
        owner_id = data.get("origOwnerTeamId")
        self.original_owner: "Team | str | None"
        if not owner_id:
            self.original_owner = None
        else:
            try:
                self.original_owner = self.league.team(owner_id)
            except NotTeamInLeague:
                self.original_owner = owner_id

    def __str__(self) -> str:
        return f"{self.year} Round {self.round}"


class CapHitPenalty(FantraxBaseObject):
    """A dead-money cap hit charged to a team (salary-cap leagues only).

    Attributes:
        league (League): The League instance this object belongs to.
        player (Player | None): Player the penalty is for.
        amount (float): Salary amount of the penalty.
        start_period (str): Period the penalty starts in (e.g. "1 (Mar 25/26)").
        description (str): Penalty description.
        ending_season_year (int | None): Season year the penalty ends.

    """

    def __init__(self, league: "League", data: dict) -> None:
        super().__init__(league, data)
        self.player: Player | None = Player(self.league, data["scorer"]) if "scorer" in data else None
        self.amount: float = parse_float(str(data.get("salaryAmount", "")).replace("$", ""))
        self.start_period: str = data.get("startPeriod", "")
        self.description: str = data.get("description", "")
        self.ending_season_year: int | None = data.get("endingSeasonYear")

    def __str__(self) -> str:
        return f"{self.player} {self.amount} ({self.start_period})"
