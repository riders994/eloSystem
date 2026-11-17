from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from ..exceptions import NotTeamInLeague
from ._parse import parse_date_range, parse_decimal, parse_float, period_number
from .base import FantraxBaseObject
from .team import Team

if TYPE_CHECKING:
    from .league import League


class ScoringPeriod(FantraxBaseObject):
    """Represents a single Period.

    Attributes:
        league (League): The League instance this object belongs to.
        start (date): Date this scoring period starts.
        end (date): Date this scoring period ends.
        number (int): Period number.
        range (str): String display of the Scoring Period range.

    """

    _data: dict

    def __init__(self, league: "League", data: dict) -> None:
        super().__init__(league, data)
        self.start: date
        self.end: date
        self.start, self.end = parse_date_range(self._data["name"], "%b %d/%y")
        self.number: int = self._data["value"]

    @property
    def range(self) -> str:
        return f"{self.start.strftime('%Y-%m-%d')} - {self.end.strftime('%Y-%m-%d')}"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ScoringPeriod):
            return self.league.league_id == other.league.league_id and self.number == other.number
        elif isinstance(other, int):
            return self.number == other
        elif isinstance(other, str) and other.isnumeric():
            return self.number == int(other)
        return False

    def __hash__(self) -> int:
        # __eq__ treats a ScoringPeriod as equal to its bare period number (int or
        # numeric str), so the hash must match hash(number) to keep the eq/hash
        # invariant. Deliberately NOT prefixed with the class name for that reason.
        return hash(self.number)

    def __str__(self) -> str:
        return f"[{self.number}:{self.range}]"


class ScoringPeriodResult(FantraxBaseObject):
    """Represents a single Scoring Period.

    Attributes:
        league (League): The League instance this object belongs to.
        playoffs (bool): This Scoring Period is Playoffs.
        name (str): Name.
        period (ScoringPeriod): Scoring Period object for this result.
        start (date): Start Date of the Period.
        end (date): End Date of the Period.
        next (date): Next Day after the Period.
        days (int): Number of Days in the Scoring Period.
        complete (bool): Is the Period Complete?
        current (bool): Is it the current Period?
        future (bool): Is the Period in the future?
        matchups (dict[str, Matchup]): Dict of Matchups with matchup ids as the key.
        other_brackets (dict[str, dict[str, Matchup]]): Dictionary of Bracket Name to its Matchups.
        title (str): Title of the Period.

    """

    _data: dict

    def __init__(self, league: "League", data: dict, other_data: list[tuple[str | None, dict]] | None = None, playoffs: bool | None = None) -> None:
        super().__init__(league, data)
        self.name: str = self._data["caption"]

        self.matchup_types: dict[str, Callable[[dict], dict[str, Matchup]]] = {
            'H2hRotisserie2': self._h2h_rot_2_factory,
            'H2hPointsBased3': self._h2h_points_based_3_factory,
        }

        self.matchup_type = data['tableType']

        # Caption styles vary by league ("Playoffs - Round 1", "Scoring Period: Playoffs 1"),
        # so callers that know the table came from a playoff view should pass playoffs explicitly.
        self.playoffs: bool = "Playoffs" in self.name if playoffs is None else playoffs
        self.start: date
        self.end: date
        self.start, self.end = parse_date_range(self._data["subCaption"], "%a %b %d, %Y")

        self.period: ScoringPeriod
        if self.playoffs:
            self.period = self.league.scoring_periods_lookup[self.range]
        else:
            self.period = self.league.scoring_periods[period_number(self.name)]

        self.next: date = self.end + timedelta(days=1)
        self.days: int = (self.next - self.start).days
        now = datetime.today().date()
        # Boundaries are inclusive of the start day and exclusive of `next` (the day
        # after the period ends) so the three flags stay mutually exclusive and cover
        # every day: a period is current on its opening day and complete from `next` on.
        self.complete: bool = now >= self.next
        self.current: bool = self.start <= now < self.next
        self.future: bool = now < self.start
        self.matchups: dict[str, Matchup] = self._matchup_factory(data)
        # A bracket whose view has no matching tab carries a None name (see
        # League._index_playoff_brackets), so the bracket key is optional.
        self.other_brackets: dict[str | None, dict[str, Matchup]] = {}
        if other_data:
            for name, obj in other_data:
                self.other_brackets.setdefault(name, {}).update(self._matchup_factory(obj))

    def _matchup_factory(self, data: dict) -> dict[str, Matchup]:
        if matchup_method := self.matchup_types.get(self.matchup_type):
            return matchup_method(data)
        else:
            # Unknown table types are treated as the pre-paired points-based shape.
            return {str(i): H2hPointsBased3(self, str(i), matchup["cells"]) for i, matchup in enumerate(data["rows"], 1)}

    def _h2h_rot_2_factory(self, data: dict) -> dict[str, Matchup]:
        res: dict[str, Matchup] = dict()
        pending: dict[str, dict] = dict()
        for row in data["rows"]:
            muid = row["matchupId"]
            first = pending.pop(muid, None)
            if first is None:
                pending[muid] = row
                continue
            # Fantrax's matchupId is "<away_team_id>_<home_team_id>" (the away side is
            # listed first, matching H2hPointsBased3's cell order). Anchor the sides to
            # that layout rather than to which row happened to arrive first, so the result
            # is stable regardless of row ordering. Fall back to arrival order only if the
            # ids can't be matched against the matchupId.
            first_id = first["fixedCells"][0]["teamId"]
            second_id = row["fixedCells"][0]["teamId"]
            if muid == f"{second_id}_{first_id}":
                away_data, home_data = row, first
            else:
                away_data, home_data = first, row
            res[muid] = H2HRotisserie2(self, muid, data, home_data, away_data)
        return res

    def _h2h_points_based_3_factory(self, data: dict) -> dict[str, Matchup]:
        return {str(i): H2hPointsBased3(self, str(i), matchup["cells"]) for i, matchup in enumerate(data["rows"], 1)}

    def add_matchups(self, data: dict) -> None:
        self.matchups.update(self._matchup_factory(data))

    @property
    def range(self) -> str:
        return f"{self.start.strftime('%Y-%m-%d')} - {self.end.strftime('%Y-%m-%d')}"

    @property
    def title(self) -> str:
        return f"{'Playoff ' if self.playoffs else ''}Period {self.period.number}"

    def __str__(self) -> str:
        output = f"{self.name}\n{self.days} Days ({self.start.strftime('%a %b %d, %Y')} - {self.end.strftime('%a %b %d, %Y')})"
        output += f"\n{'Complete' if self.complete else 'Current' if self.current else 'Future'}"
        for matchup in self.matchups.values():
            output += f"\n{matchup}"
        for name, matchups in self.other_brackets.items():
            output += f"\n{name}"
            for matchup in matchups.values():
                output += f"\n{matchup}"
        return output


class Matchup(FantraxBaseObject):
    """Shared base for the concrete matchup shapes.

    Subclasses populate ``away``/``home`` and ``away_score``/``home_score`` from
    whatever layout their table uses (:class:`H2hPointsBased3` parses pre-paired
    away/home cells; :class:`H2HRotisserie2` pairs per-team category rows). Everything
    here is format-agnostic and works off those public attributes, so it applies to
    every matchup type.

    Attributes:
        league (League): The League instance this object belongs to.
        scoring_period (ScoringPeriodResult): Scoring Period result this instance belongs to.
        matchup_key (str): Matchup Key.
        away (Team | str): Away Team (or its raw name when not a league member).
        away_score (float): Away Team Score.
        home (Team | str): Home Team (or its raw name when not a league member).
        home_score (float): Home Team Score.
        composite_key (str): "<home_team_id>_<away_team_id>" key built from this Matchup's two sides.

    """

    scoring_period: ScoringPeriodResult
    matchup_key: str
    away: Team | str
    home: Team | str
    away_score: float
    home_score: float

    @property
    def composite_key(self) -> str:
        home_id = self.home.id if isinstance(self.home, Team) else self.home
        away_id = self.away.id if isinstance(self.away, Team) else self.away
        return f"{home_id}_{away_id}"

    def winner(self) -> tuple[Team | str, float, Team | str, float] | tuple[None, None, None, None]:
        if self.away_score > self.home_score:
            return self.away, self.away_score, self.home, self.home_score
        elif self.away_score < self.home_score:
            return self.home, self.home_score, self.away, self.away_score
        else:
            return None, None, None, None

    def difference(self) -> float:
        # Operates on the public float scores so it works for every matchup shape;
        # subclasses with exact Decimal scores override to keep that precision.
        return abs(self.away_score - self.home_score)

    def __str__(self) -> str:
        if self.away_score or self.home_score:
            winner, winner_score, loser, loser_score = self.winner()
            return f"{self.scoring_period.title} {winner} ({winner_score}) vs {loser} ({loser_score})"
        else:
            return f"{self.scoring_period.title} {self.away} vs {self.home}"

class H2HRotisserie2(Matchup):
    """ Represents a H2H Matchup.
    Attributes:
            matchup_key (str): Matchup Key.
            away (:class:`~Team`): Away Team.
            away_score (float): Away Team Score.
            home (:class:`~Team`): Home Team.
            home_score (float): Home Team Score.
            no_contest (bool): True when one side is an empty bye slot (no real opponent),
                so the matchup is a non-contest. Its scores stay at the 0.5-0.5 tie default.
            scoring_grid (dict[str, dict[str, float]]): Scoring category short name -> {team id -> value}.
                Only real categories are included; the W/L/T/Pts summary columns are excluded.
            category_winners (dict[str, str | None]): Scoring category short name -> the id of the
                team that won that category, or ``None`` when the category was tied.

    """
    # Default to a 0.5-0.5 tie; the real result overwrites these from the "Pts" (Category
    # points) column. A no-contest/bye matchup keeps the tie default (see no_contest).
    home_score = 0.5
    away_score = 0.5

    def __init__(self, scoring_period: ScoringPeriodResult, matchup_key: str, data: dict, home_data: dict, away_data: dict) -> None:
        FantraxBaseObject.__init__(self, scoring_period.league, data)
        self.scoring_period: ScoringPeriodResult = scoring_period
        self.matchup_key: str = matchup_key
        self.scoring_grid: dict[str, dict[str, float]] = dict()
        self.category_winners: dict[str, str | None] = dict()
        self.no_contest: bool = False
        bye_data = {"name": "Bye", "shortName": "BYE", "logoUrl128": ""}
        # This shape always resolves both sides to a Team (a missing side becomes a Bye
        # Team), unlike the base Matchup which also allows a raw str name. A bye side means
        # there's no real opponent, so the matchup is a non-contest.
        self.away: Team
        self.home: Team
        try:
            self.away = self.league.team(away_data['fixedCells'][0]["teamId"])
        except NotTeamInLeague:
            self.away = Team(self.league, "bye", bye_data)
            self.no_contest = True
        try:
            self.home = self.league.team(home_data['fixedCells'][0]["teamId"])
        except NotTeamInLeague:
            self.home = Team(self.league, "bye", bye_data)
            self.no_contest = True

        self.home_categories: dict[str, str | float] = {'opponent': self.away.id}
        self.away_categories: dict[str, str | float] = {'opponent': self.home.id}

        headers =  self._header_translator(data["header"]['cells'])
        self._scoreboard_builder(home_data['cells'], away_data['cells'], headers)

    @staticmethod
    def _header_translator(headers: list[dict]) -> list[tuple[str, str | None]]:
        # Preserve column order and carry each column's key so the scoreboard builder can
        # tell real scoring categories (key "scip") from summary columns (win/loss/tie/cp).
        return [(h["shortName"], h.get("key")) for h in headers]

    def _scoreboard_builder(self, home_cells: list[dict], away_cells: list[dict], headers: list[tuple[str, str | None]]) -> None:
        for i, (short_name, key) in enumerate(headers):
            if home_cells[i].get('toolTip'):
                h = parse_float(home_cells[i].get('toolTip'))
                a = parse_float(away_cells[i].get('toolTip'))
            else:
                h = parse_float(home_cells[i]['content'])
                a = parse_float(away_cells[i]['content'])

            # "cp" (Category points) is the matchup total that decides the winner. A
            # bye/non-contest has no real result, so leave the scores at the tie default.
            if key == "cp" and not self.no_contest:
                self.home_score = h
                self.away_score = a

            # Only "scip" columns are real scoring categories; W/L/T/Pts (win/loss/tie/cp)
            # are per-matchup summaries and must not be treated as categories.
            if key != "scip":
                continue

            self.scoring_grid[short_name] = {self.home.id: h, self.away.id: a}
            self.home_categories[short_name] = h
            self.away_categories[short_name] = a
            # Fantrax flags the category winner with gainColor == 1 and the loser with -1;
            # a tie is 0 on both sides. Since only real categories reach here, a None winner
            # now unambiguously means the category was tied (or has no result yet).
            if home_cells[i].get('gainColor') == 1:
                self.category_winners[short_name] = self.home.id
            elif away_cells[i].get('gainColor') == 1:
                self.category_winners[short_name] = self.away.id
            else:
                self.category_winners[short_name] = None

    def __str__(self) -> str:
        if self.no_contest:
            return f"{self.scoring_period.title} {self.away} vs {self.home} (No Contest)"
        return super().__str__()


class H2hPointsBased3(Matchup):
    """Represents a H2H Points Based Matchup.

    Its scoring period table is a pre-paired row whose cells are
    ``[away_team, away_score, home_team, home_score]``, so this is also the shape used
    as the generic fallback for unrecognised table types. Scores are kept as exact
    :class:`~decimal.Decimal` values internally and exposed as floats.

    Attributes:
            league (League): The League instance this object belongs to.
            scoring_period (ScoringPeriodResult): Scoring Period result this instance belongs to.
            matchup_key (str): Matchup Key.
            away (Team | str): Away Team (or its raw name when not a league member).
            away_score (float): Away Team Score.
            home (Team | str): Home Team (or its raw name when not a league member).
            home_score (float): Home Team Score.

    """

    def __init__(self, scoring_period: ScoringPeriodResult, matchup_key: str, data: dict) -> None:
        super().__init__(scoring_period.league, data)
        self.scoring_period: ScoringPeriodResult = scoring_period
        self.matchup_key: str = matchup_key
        try:
            self.away: Team | str = self.league.team(self._data[0]["teamId"])
        except NotTeamInLeague:
            self.away = self._data[0]["content"]
        self._away_score: Decimal = parse_decimal(self._data[1]["content"])
        try:
            self.home: Team | str = self.league.team(self._data[2]["teamId"])
        except NotTeamInLeague:
            self.home = self._data[2]["content"]
        self._home_score: Decimal = parse_decimal(self._data[3]["content"])

    # This shape derives its scores from exact Decimals, so they are read-only here even
    # though the base Matchup (and the sibling H2HRotisserie2) treat them as writable.
    @property
    def away_score(self) -> float:  # type: ignore[override]
        return float(self._away_score)

    @property
    def home_score(self) -> float:  # type: ignore[override]
        return float(self._home_score)

    def difference(self) -> float:
        # Subtract as Decimals to preserve exact scores before narrowing to float.
        return float(abs(self._away_score - self._home_score))
