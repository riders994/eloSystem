"""Mock payloads emulating the Sleeper read API (https://api.sleeper.app).

Unlike the Fantrax fork, the ``sleeper`` client returns plain decoded JSON,
so these factories build dicts rather than objects. The shapes below were
taken from live responses for a real 10-team NFL league.

The endpoints elo_system touches:

- ``get_league(league_id=...)`` -> a dict with ``name``, ``season``,
  ``status``, ``previous_league_id``, ``total_rosters`` and a ``settings``
  sub-dict carrying ``playoff_week_start``, ``leg`` and ``last_scored_leg``.
  ``last_scored_leg`` is the number of weeks actually scored and comes back
  ``None`` before a season has played any; ``leg`` is the week the league is
  on, which during the preseason is 1 with nothing played.
- ``get_rosters(league_id=...)`` -> a list of dicts with ``roster_id`` (int,
  1-based), ``owner_id`` (the user id) and a ``settings`` sub-dict of
  ``wins`` / ``losses`` / ``ties`` / ``fpts`` / ``fpts_decimal``. Sleeper
  splits points-for across the last two as integers, so 1634.02 arrives as
  ``fpts=1634, fpts_decimal=2``.
- ``get_users_in_league(league_id=...)`` -> a list of dicts with ``user_id``,
  ``display_name``, ``is_owner`` (True for the commissioner, but ``None``
  rather than False for most members) and a ``metadata`` sub-dict that
  carries ``team_name`` only once a manager has set one.
- ``get_matchups_for_week(league_id=..., week=...)`` -> one flat dict per
  roster with ``roster_id``, ``points`` and ``matchup_id``. Two rosters
  share a ``matchup_id``; a roster idle that week (playoff byes, and
  everyone eliminated) gets ``matchup_id: None``.

Sleeper's read API needs no auth, so there is no session/login to fake --
``patch_sleeper_api`` just swaps the four module-level functions
``SleeperScraper`` imports.
"""

#: A stand-in league id, shaped like Sleeper's (a numeric string).
LEAGUE_ID = '1063131085976006656'

#: (user_id, display_name, team_name, roster_id, wins, losses, fpts)
_DEFAULT_MEMBERS = (
    ('738089321269194752', 'GeneralH', 'Waiting for Jamot', 1, 6, 8, 1634.02),
    ('859993191833767936', 'Votto', 'Night Vale Scorpions', 2, 10, 4, 1810.26),
    ('74842634216423424', 'tyransosaura', 'Defying Jakobity', 3, 7, 7, 1854.84),
    ('860003302220337152', 'MinorityWhip', 'The Pence of Egypt', 4, 7, 7, 1786.44),
    ('860373697800835072', 'jordanm69', 'I Am the Liquor', 5, 9, 5, 1873.68),
    ('859950573120794624', 'seireikhaan', 'Expeditions : Rome', 6, 8, 6, 1745.78),
)


def make_league(
        league_id=LEAGUE_ID,
        name='League Free, Die Nasty',
        season='2024',
        status='complete',
        playoff_week_start=15,
        leg=17,
        last_scored_leg=17,
        previous_league_id='920833359809437696',
        total_rosters=len(_DEFAULT_MEMBERS),
        **settings,
):
    """Mock of get_league(). Extra kwargs land in the settings sub-dict."""
    league_settings = {
        'playoff_week_start': playoff_week_start,
        'leg': leg,
        'last_scored_leg': last_scored_leg,
        'num_teams': total_rosters,
        'playoff_teams': 6,
        'start_week': 1,
    }
    league_settings.update(settings)
    return {
        'league_id': league_id,
        'name': name,
        'season': season,
        'status': status,
        'sport': 'nfl',
        'previous_league_id': previous_league_id,
        'total_rosters': total_rosters,
        'settings': league_settings,
    }


def make_roster(roster_id, owner_id, wins=0, losses=0, ties=0, fpts=0.0):
    """Mock of one get_rosters() entry.

    ``fpts`` is given as a normal float and split the way Sleeper splits it.
    """
    whole = int(fpts)
    return {
        'roster_id': roster_id,
        'owner_id': owner_id,
        'league_id': LEAGUE_ID,
        'co_owners': None,
        'settings': {
            'wins': wins,
            'losses': losses,
            'ties': ties,
            'fpts': whole,
            'fpts_decimal': round((fpts - whole) * 100),
        },
    }


def make_user(user_id, display_name, team_name=None, is_owner=None):
    """Mock of one get_users_in_league() entry.

    ``team_name=None`` models a manager who never set one, which is why the
    scraper falls back to display_name.
    """
    metadata = {'avatar': 'https://sleepercdn.com/uploads/{}'.format(user_id)}
    if team_name is not None:
        metadata['team_name'] = team_name
    return {
        'user_id': user_id,
        'display_name': display_name,
        'league_id': LEAGUE_ID,
        'is_owner': is_owner,
        'is_bot': None,
        'metadata': metadata,
    }


def make_matchup(roster_id, points, matchup_id):
    """Mock of one get_matchups_for_week() entry."""
    return {
        'roster_id': roster_id,
        'points': points,
        'matchup_id': matchup_id,
        'custom_points': None,
        'starters': [],
        'players': [],
    }


def make_matchups(pairs, byes=()):
    """Build a week of matchups.

    Args:
        pairs: an iterable of ((roster_id, points), (roster_id, points))
               tuples; each pair gets the next matchup_id, 1-based.
        byes:  an iterable of (roster_id, points) for rosters not playing,
               which Sleeper hands back with a null matchup_id.
    """
    matchups = []
    for matchup_id, (home, away) in enumerate(pairs, start=1):
        matchups.append(make_matchup(home[0], home[1], matchup_id))
        matchups.append(make_matchup(away[0], away[1], matchup_id))
    for roster_id, points in byes:
        matchups.append(make_matchup(roster_id, points, None))
    return matchups


def make_season(members=_DEFAULT_MEMBERS):
    """Return (users, rosters) for a whole league.

    The first member is flagged as commissioner, and the last is given no
    team name, so a single fixture exercises both fallbacks.
    """
    users, rosters = [], []
    last = len(members) - 1
    for i, (user_id, display_name, team_name, roster_id, wins, losses, fpts) in enumerate(members):
        users.append(make_user(
            user_id,
            display_name,
            team_name=None if i == last else team_name,
            is_owner=True if i == 0 else None,
        ))
        rosters.append(make_roster(roster_id, user_id, wins, losses, fpts=fpts))
    return users, rosters


def make_default_week(members=_DEFAULT_MEMBERS):
    """A week pairing the members off in roster order, highest score first."""
    ids = [m[3] for m in members]
    pairs = [
        ((ids[i], 120.0 + i * 10), (ids[i + 1], 100.0 + i * 5))
        for i in range(0, len(ids) - 1, 2)
    ]
    return make_matchups(pairs)


def patch_sleeper_api(
        monkeypatch,
        league=None,
        users=None,
        rosters=None,
        matchups=None,
):
    """Point SleeperScraper's Sleeper client at canned payloads.

    ``SleeperScraper._api`` imports from ``sleeper.api`` on each call, so the
    patch has to land on that module rather than on the scraper's namespace.

    Args:
        matchups: either a single week's list (served for every week) or a
                  ``{week: list}`` mapping.

    Returns a ``calls`` dict recording the arguments each endpoint was
    handed, so tests can assert the league id and week were plumbed through.
    """
    import sleeper.api as sleeper_api

    if league is None:
        league = make_league()
    if users is None or rosters is None:
        default_users, default_rosters = make_season()
        users = default_users if users is None else users
        rosters = default_rosters if rosters is None else rosters
    if matchups is None:
        matchups = make_default_week()

    calls = {'league_id': [], 'rosters': [], 'users': [], 'weeks': []}

    def fake_get_league(*, league_id):
        calls['league_id'].append(league_id)
        return league

    def fake_get_rosters(*, league_id):
        calls['rosters'].append(league_id)
        return rosters

    def fake_get_users_in_league(*, league_id):
        calls['users'].append(league_id)
        return users

    def fake_get_matchups_for_week(*, league_id, week):
        calls['weeks'].append((league_id, week))
        if isinstance(matchups, dict):
            return matchups[week]
        return matchups

    monkeypatch.setattr(sleeper_api, 'get_league', fake_get_league)
    monkeypatch.setattr(sleeper_api, 'get_rosters', fake_get_rosters)
    monkeypatch.setattr(sleeper_api, 'get_users_in_league', fake_get_users_in_league)
    monkeypatch.setattr(sleeper_api, 'get_matchups_for_week', fake_get_matchups_for_week)

    return calls
