"""Mock objects/factories emulating the shapes of the fantraxapi fork
(riders994/FantraxAPI@stable) that elo_system actually touches.

The real objects of interest:

- ``fantraxapi.objs.team.Team``: ``.id``, ``.name``, ``.short``,
  ``.commissioner`` (bool), ``.owners`` (str -- owner account name, the
  cross-season-stable identifier elo_system keys everything on).
- ``fantraxapi.objs.scoring_period.H2HRotisserie2`` (a ``Matchup``):
  ``.home`` / ``.away`` Team objects, plus ``.home_categories`` /
  ``.away_categories`` dicts of ``{'opponent': <other team id>,
  '<category short name>': float, ..., 'Pts': float}``.
- ``fantraxapi.objs.scoring_period.ScoringPeriodResult``: ``.playoffs``
  (bool), ``.name``, and ``.matchups`` -- a dict keyed by matchup id.
- ``fantraxapi.League``: constructed as ``League(league_id=...)``;
  ``.scoring_period_results()`` returns ``dict[int, ScoringPeriodResult]``
  keyed by 1-based period number; ``.teams`` is a list of Team objects.

Everything here is built from SimpleNamespace / tiny classes carrying only
the attributes the elo_system code reads, so other parts of the suite can
reuse these factories without dragging in network-backed fixtures.
"""
from types import SimpleNamespace

#: The 9 NBA category short-names elo_system's roto logic expects
#: (matches elo_system.tools.basics.constants.ROTO_SCORING).
NBA_CATEGORIES = ('FG%', 'FT%', '3PTM', 'PTS', 'REB', 'AST', 'ST', 'BLK', 'TO')

_DEFAULT_STATS = {
    'FG%': 0.450,
    'FT%': 0.800,
    '3PTM': 30.0,
    'PTS': 400.0,
    'REB': 150.0,
    'AST': 90.0,
    'ST': 25.0,
    'BLK': 15.0,
    'TO': 45.0,
}


def make_category_stats(pts=4.5, **overrides):
    """Return a fresh 9-cat NBA stat dict plus the H2H 'Pts' score.

    ``pts`` is the head-to-head category points ('Pts' key, what
    fantrax_formatter turns into true_score by dividing by 9).
    Category values can be overridden by short name, e.g.
    ``make_category_stats(pts=6, TO=38.0, **{'FG%': 0.51})``.
    """
    stats = dict(_DEFAULT_STATS)
    stats.update(overrides)
    stats['Pts'] = pts
    return stats


def make_team(owners, team_id=None, name=None, short=None, commissioner=False):
    """Mock of fantraxapi Team with only the attributes elo_system reads."""
    if team_id is None:
        team_id = f"id_{owners}"
    if name is None:
        name = f"Team {owners}"
    if short is None:
        short = owners[:3].upper()
    return SimpleNamespace(
        id=team_id,
        name=name,
        short=short,
        commissioner=commissioner,
        owners=owners,
    )


def make_default_teams(n=4):
    """n teams with distinct owners/ids; the first is the commissioner."""
    return [
        make_team(f"owner_{i}", team_id=f"team{i}id", name=f"Team {i}",
                  short=f"T{i:02d}", commissioner=(i == 0))
        for i in range(n)
    ]


def make_matchup(home, away, home_stats=None, away_stats=None, matchup_key='1'):
    """Mock of an H2HRotisserie2 matchup.

    ``home_stats``/``away_stats`` are stat dicts as built by
    :func:`make_category_stats` (category short names + 'Pts').
    The 'opponent' key is injected here exactly like the real class does
    (it maps to the *other* side's team id).
    """
    home_categories = {'opponent': away.id}
    home_categories.update(home_stats if home_stats is not None else make_category_stats())
    away_categories = {'opponent': home.id}
    away_categories.update(away_stats if away_stats is not None else make_category_stats())
    return SimpleNamespace(
        matchup_key=matchup_key,
        home=home,
        away=away,
        home_categories=home_categories,
        away_categories=away_categories,
        home_score=home_categories.get('Pts'),
        away_score=away_categories.get('Pts'),
    )


def make_scoring_period(matchups, playoffs=False, name=None):
    """Mock of ScoringPeriodResult.

    ``matchups`` may be a dict keyed by matchup id (like the real
    ``.matchups``) or an iterable, which gets keyed '1', '2', ...
    """
    if not isinstance(matchups, dict):
        matchups = {str(i): m for i, m in enumerate(matchups, 1)}
    if name is None:
        name = 'Playoffs - Round 1' if playoffs else 'Scoring Period 1'
    return SimpleNamespace(
        matchups=matchups,
        playoffs=playoffs,
        name=name,
        other_brackets={},
    )


def make_season(teams, playoff_flags):
    """Build ``dict[int, scoring_period]`` keyed by 1-based week number,
    mirroring ``fantraxapi.League.scoring_period_results()``.

    ``playoff_flags`` is one bool per week (True => playoff week).
    Each week pairs teams[0] vs teams[1], teams[2] vs teams[3], ...
    """
    periods = {}
    for week, playoffs in enumerate(playoff_flags, 1):
        matchups = [
            make_matchup(teams[i], teams[i + 1], matchup_key=str(i // 2 + 1))
            for i in range(0, len(teams) - 1, 2)
        ]
        name = f"Playoffs - Round {week}" if playoffs else f"Scoring Period {week}"
        periods[week] = make_scoring_period(matchups, playoffs=playoffs, name=name)
    return periods


def make_mock_league_cls(scoring_periods=None, teams=None):
    """Return a class suitable for monkeypatching ``fantraxapi.League``
    (the ``ft.League`` name imported by elo_system.tools.scraper) so that
    ``FantraxScraper.login()`` never touches the network.

    Every instantiation is recorded in ``cls.instances`` so tests can
    assert on the wiring (e.g. the league_id passed in).
    """
    scoring_periods = scoring_periods if scoring_periods is not None else {}
    teams = teams if teams is not None else []

    class MockFantraxLeague:
        instances = []

        def __init__(self, league_id=None, **kwargs):
            self.league_id = league_id
            self.init_kwargs = kwargs
            self.teams = list(teams)
            type(self).instances.append(self)

        def scoring_period_results(self, season=True, playoffs=True):
            return dict(scoring_periods)

    return MockFantraxLeague
