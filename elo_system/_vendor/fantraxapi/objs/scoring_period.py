from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Self

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

    def __init__(self, league: "League", data: dict) -> None:
        super().__init__(league, data)
        self.start: date
        self.end: date
        self.start, self.end = parse_date_range(self._data["name"], "%b %d/%y")
        self.number: int = self._data["value"]

    @property
    def range(self) -> str:
        return f"{self.start.strftime('%Y-%m-%d')} - {self.end.strftime('%Y-%m-%d')}"

    def __eq__(self, other: str | int | Self) -> bool:
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

    def __init__(self, league: "League", data: dict, other_data: list[tuple[str, dict]] = None, playoffs: bool | None = None) -> None:
        super().__init__(league, data)
        self.name: str = self._data["caption"]

        self.matchup_types = {
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

        if self.playoffs:
            self.period: ScoringPeriod = self.league.scoring_periods_lookup[self.range]
        else:
            self.period: ScoringPeriod = self.league.scoring_periods[period_number(self.name)]

        self.next: date = self.end + timedelta(days=1)
        self.days: int = (self.next - self.start).days
        now = datetime.today().date()
        self.complete: bool = now > self.next
        self.current: bool = self.start < now < self.next
        self.future: bool = now < self.start
        self.matchups: dict[str, Matchup] = self._matchup_factory(data)
        self.other_brackets: dict[str, dict[str, Matchup]] = {}
        if other_data:
            for name, obj in other_data:
                self.other_brackets.setdefault(name, {}).update(self._matchup_factory(obj))

    def _matchup_factory(self, data) -> dict[str, Matchup]:
        if matchup_method := self.matchup_types.get(self.matchup_type):
            return matchup_method(data)
        else:
            return {str(i): Matchup(self, str(i), matchup["cells"]) for i, matchup in enumerate(data["rows"], 1)}

    def _h2h_rot_2_factory(self, data) -> dict[str, H2HRotisserie2]:
        res = dict()
        matchup_dict = dict()
        for row in data["rows"]:
            muid = row['matchupId']
            if other_row := matchup_dict.get(muid):
                res.update({muid: H2HRotisserie2(self, muid, data, row, other_row)})
            else:
                matchup_dict.update({muid: row})
        return res

    def _h2h_points_based_3_factory(self, data) -> dict[str, H2hPointsBased3]:
        return {str(i): H2hPointsBased3(self, str(i), matchup["cells"]) for i, matchup in enumerate(data["rows"], 1)}

    def add_matchups(self, data):
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
    """Represents a single Matchup.

    Attributes:
        league (League): The League instance this object belongs to.
        scoring_period (ScoringPeriodResult): Scoring Period result this instance belongs to.
        matchup_key (str): Matchup Key.
        away (Team): Away Team.
        away_score (float): Away Team Score.
        home (Team): Home Team.
        home_score (float): Home Team Score.
        composite_key (str): "<home_team_id>_<away_team_id>" key built from this Matchup's two sides.

    """

    def __init__(self, scoring_period: ScoringPeriodResult, matchup_key: str, data: dict) -> None:
        super().__init__(scoring_period.league, data)
        self.scoring_period: ScoringPeriodResult = scoring_period
        self.matchup_key: str = matchup_key
        try:
            self.away: Team | str = self.league.team(self._data[0]["teamId"])
        except NotTeamInLeague:
            self.away: Team | str = self._data[0]["content"]
        self._away_score: Decimal = parse_decimal(self._data[1]["content"])
        try:
            self.home: Team | str = self.league.team(self._data[2]["teamId"])
        except NotTeamInLeague:
            self.home: Team | str = self._data[2]["content"]
        self._home_score: Decimal = parse_decimal(self._data[3]["content"])

    @property
    def away_score(self) -> float:
        return float(self._away_score)

    @property
    def home_score(self) -> float:
        return float(self._home_score)

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
        if self.away_score > self.home_score:
            return float(self._away_score - self._home_score)
        elif self.away_score < self.home_score:
            return float(self._home_score - self._away_score)
        else:
            return 0.0

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

    """
    home_score = 0.5
    away_score = 0.5

    def __init__(self, scoring_period: ScoringPeriodResult, matchup_key: str, data: dict, home_data: dict, away_data: dict):
        FantraxBaseObject.__init__(self, scoring_period.league, data)
        self.scoring_period = scoring_period
        self.matchup_key = matchup_key
        self.scoring_grid = dict()
        bye_data = {"name": "Bye", "shortName": "BYE", "logoUrl128": ""}
        try:
            self.away = self.league.team(away_data['fixedCells'][0]["teamId"])
        except NotTeamInLeague:
            self.away = Team(self.league, "bye", bye_data)
        try:
            self.home = self.league.team(home_data['fixedCells'][0]["teamId"])
        except NotTeamInLeague:
            self.home = Team(self.league, "bye", bye_data)

        self.home_categories = {'opponent': self.away.id}
        self.away_categories = {'opponent': self.home.id}

        headers =  self._header_translator(data["header"]['cells'])
        self._scoreboard_builder(home_data['cells'], away_data['cells'], headers)

    @staticmethod
    def _header_translator(headers: list[dict]):
        return {
            h['shortName']: h['name'] for h in headers
        }

    def _scoreboard_builder(self, home_cells, away_cells, headers):
        for i, category in enumerate(headers):
            if home_cells[i].get('toolTip'):
                h = parse_float(home_cells[i].get('toolTip'))
                a = parse_float(away_cells[i].get('toolTip'))
            else:
                h = parse_float(home_cells[i]['content'])
                a = parse_float(away_cells[i]['content'])

            self.scoring_grid.update({
                category: {
                    self.home.id: h,
                    self.away.id: a,
                }
            })
            self.home_categories.update({
                category: h
            })
            self.away_categories.update({
                category: a
            })
            if category == 'Pts':
                self.home_score = h
                self.away_score = a


class H2hPointsBased3(Matchup):
    """ Represents a H2H Points Based Matchup.
    Attributes:
            league (League): The League instance this object belongs to.
            scoring_period (ScoringPeriodResult): Scoring Period result this instance belongs to.
            matchup_key (str): Matchup Key.
            away (:class:`~Team`): Away Team.
            away_score (float): Away Team Score.
            home (:class:`~Team`): Home Team.
            home_score (float): Home Team Score.

    """
