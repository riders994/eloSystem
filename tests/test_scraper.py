"""Tests for elo_system.tools.scraper (LeagueScraper, FantraxScraper,
SleeperScraper).

FantraxScraper.login() is wired to ft.League and SleeperScraper's to the
sleeper.api functions; both are monkeypatched so no test touches the network.
"""
import pytest

from elo_system.tools.helpers import scraper as scraper_mod
from elo_system.tools.helpers.scraper import (
    PLAYOFF_START,
    FantraxScraper,
    LeagueScraper,
    SleeperScraper,
)

from tests.mocks.fantrax import (
    make_default_teams,
    make_mock_league_cls,
    make_season,
    make_standings,
)
from tests.mocks.sleeper import (
    LEAGUE_ID as SLEEPER_LEAGUE_ID,
    make_league,
    make_matchups,
    make_user,
    patch_sleeper_api,
)
from tests.mocks.sleeper import make_season as make_sleeper_season

LEAGUE_ID = 'lg123abc'


class _ConcreteScraper(LeagueScraper):
    """Minimal concrete scraper for exercising the shared base plumbing."""

    def login(self):
        pass

    def get_members(self):
        return {}

    def get_league_name(self):
        return None

    def get_scoreboard(self, week):
        return None

    def get_playoff_start(self):
        return PLAYOFF_START

    def get_current_season_length(self):
        return 0


def _make_config(**overrides):
    config = {'league_id': LEAGUE_ID, 'members': {}}
    config.update(overrides)
    return config


def _patch_ft_league(monkeypatch, playoff_flags, teams=None):
    """Patch the ft.League name used by scraper.py; return the mock class."""
    if teams is None:
        teams = make_default_teams(4)
    periods = make_season(teams, playoff_flags)
    mock_cls = make_mock_league_cls(scoring_periods=periods, teams=teams)
    monkeypatch.setattr(scraper_mod.ft, 'League', mock_cls)
    return mock_cls, periods, teams


# ---------------------------------------------------------------------------
# LeagueScraper base behavior
# ---------------------------------------------------------------------------

def test_base_scraper_is_abstract():
    # LeagueScraper defines the platform interface; it cannot be instantiated
    # directly, and every platform method is abstract.
    with pytest.raises(TypeError):
        LeagueScraper(_make_config())
    assert LeagueScraper.__abstractmethods__ == {
        'login', 'get_members', 'get_league_name', 'get_scoreboard',
        'get_playoff_start', 'get_current_season_length',
    }


def test_base_scraper_load_reads_league_id_and_playoff_start():
    scraper = _ConcreteScraper(_make_config(playoff_start=7))
    scraper.load()
    assert scraper.league_id == LEAGUE_ID
    assert scraper.playoff_start == 7
    assert scraper.loaded is True


def test_base_scraper_load_defaults_playoff_start():
    scraper = _ConcreteScraper(_make_config())
    scraper.load()
    assert scraper.playoff_start == PLAYOFF_START


def test_base_scraper_dump_merges_managers_and_playoff_start():
    config = _make_config(members={'owner_a': {'curr_name': 'Old'}})
    scraper = _ConcreteScraper(config)
    scraper.load()
    scraper.playoff_start = 9
    scraper.managers = {'owner_b': {'curr_name': 'New'}}
    dumped = scraper.dump()
    assert dumped is scraper.config
    assert dumped['members'] == {
        'owner_a': {'curr_name': 'Old'},
        'owner_b': {'curr_name': 'New'},
    }
    assert dumped['playoff_start'] == 9


# ---------------------------------------------------------------------------
# FantraxScraper.login wiring
# ---------------------------------------------------------------------------

def test_login_instantiates_ft_league_with_config_league_id(monkeypatch):
    mock_cls, periods, _ = _patch_ft_league(monkeypatch, [False] * 3)
    scraper = FantraxScraper(_make_config())
    wrapper = scraper.login()

    assert len(mock_cls.instances) == 1
    assert mock_cls.instances[0].league_id == LEAGUE_ID
    assert wrapper is scraper.league_wrapper
    assert isinstance(wrapper, mock_cls)
    assert scraper.loaded is True
    # scoring periods fetched eagerly at login
    assert scraper.scoring_periods == periods


# ---------------------------------------------------------------------------
# Season length
# ---------------------------------------------------------------------------

def test_get_current_season_length_counts_periods(monkeypatch):
    _patch_ft_league(monkeypatch, [False, False, False, True, True])
    scraper = FantraxScraper(_make_config())
    scraper.login()
    assert scraper.get_current_season_length() == 5


# ---------------------------------------------------------------------------
# Playoff start derivation
# ---------------------------------------------------------------------------

def test_get_playoff_start_walks_back_to_first_playoff_week(monkeypatch):
    # weeks 1-4 regular, weeks 5-6 playoffs -> playoffs start week 5
    _patch_ft_league(monkeypatch, [False, False, False, False, True, True])
    scraper = FantraxScraper(_make_config())
    scraper.login()
    assert scraper.get_playoff_start() == 5


def test_get_playoff_start_single_playoff_week(monkeypatch):
    _patch_ft_league(monkeypatch, [False, False, True])
    scraper = FantraxScraper(_make_config())
    scraper.login()
    assert scraper.get_playoff_start() == 3


def test_get_playoff_start_no_playoffs_is_week_after_season(monkeypatch):
    # No playoff week observed yet -> playoffs "start" after the last
    # scored week (season_length + 1).
    _patch_ft_league(monkeypatch, [False] * 4)
    scraper = FantraxScraper(_make_config())
    scraper.login()
    assert scraper.get_playoff_start() == 5


def test_get_playoff_start_all_playoffs_stops_at_week_two(monkeypatch):
    # Degenerate all-playoffs season: the walk is forcibly stopped at week 1
    # (guarding the index), so the earliest derivable start is week 2.
    _patch_ft_league(monkeypatch, [True] * 4)
    scraper = FantraxScraper(_make_config())
    scraper.login()
    assert scraper.get_playoff_start() == 2


def test_get_playoff_start_before_login_falls_back_to_constant():
    scraper = FantraxScraper(_make_config())
    assert scraper.loaded is False
    assert scraper.get_playoff_start() == PLAYOFF_START


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

def test_get_members_keyed_by_owner_with_team_details(monkeypatch):
    _, _, teams = _patch_ft_league(monkeypatch, [False, False])
    scraper = FantraxScraper(_make_config())
    scraper.login()

    members = scraper.get_members()
    assert set(members) == {team.owners for team in teams}
    first = teams[0]
    assert members[first.owners] == {
        'team_id': first.id,
        'curr_name': first.name,
        'curr_short': first.short,
        'commish': True,
        'standing': 1,
    }
    # Only the first default team is the commissioner.
    assert [info['commish'] for info in members.values()].count(True) == 1


def test_get_members_takes_standing_from_the_standings_order(monkeypatch):
    teams = make_default_teams(4)
    # Rank the teams in reverse, so standing cannot be mistaken for team order.
    mock_cls = make_mock_league_cls(
        scoring_periods=make_season(teams, [False, False]),
        teams=teams,
        standings=make_standings(list(reversed(teams))),
    )
    monkeypatch.setattr(scraper_mod.ft, 'League', mock_cls)
    scraper = FantraxScraper(_make_config())
    scraper.login()

    members = scraper.get_members()
    assert [members[team.owners]['standing'] for team in teams] == [4, 3, 2, 1]


def test_get_members_standing_falls_back_for_a_team_off_the_table(monkeypatch):
    teams = make_default_teams(4)
    # A placeholder team (e.g. a playoff Bye slot) never reaches the standings.
    mock_cls = make_mock_league_cls(
        scoring_periods=make_season(teams, [False, False]),
        teams=teams,
        standings=make_standings(teams[:3]),
    )
    monkeypatch.setattr(scraper_mod.ft, 'League', mock_cls)
    scraper = FantraxScraper(_make_config())
    scraper.login()

    members = scraper.get_members()
    assert members[teams[3].owners]['standing'] == 100


# ---------------------------------------------------------------------------
# Scoreboard access
# ---------------------------------------------------------------------------

def test_get_scoreboard_indexes_periods_by_week_number(monkeypatch):
    _, periods, _ = _patch_ft_league(monkeypatch, [False, False, True])
    scraper = FantraxScraper(_make_config())
    scraper.login()

    board = scraper.get_scoreboard(2)
    assert board is periods[2]
    assert scraper.current_matchup is board

    # Re-fetching another week replaces the cached matchup.
    board3 = scraper.get_scoreboard(3)
    assert board3 is periods[3]
    assert scraper.current_matchup is board3
    assert board3.playoffs is True


def test_get_league_name_reads_the_wrapper(monkeypatch):
    mock_cls = make_mock_league_cls(scoring_periods=make_season(make_default_teams(4), [False]),
                                    teams=make_default_teams(4), name="Mao's Macho Mandarins")
    monkeypatch.setattr(scraper_mod.ft, 'League', mock_cls)
    scraper = FantraxScraper(_make_config())
    scraper.login()
    assert scraper.get_league_name() == "Mao's Macho Mandarins"


def test_get_league_name_before_login_is_none():
    assert FantraxScraper(_make_config()).get_league_name() is None


# ---------------------------------------------------------------------------
# SleeperScraper
# ---------------------------------------------------------------------------

def _sleeper_config(**overrides):
    config = {'league_id': SLEEPER_LEAGUE_ID, 'members': {}}
    config.update(overrides)
    return config


def test_sleeper_login_fetches_league_rosters_and_users(monkeypatch):
    calls = patch_sleeper_api(monkeypatch)
    scraper = SleeperScraper(_sleeper_config())

    wrapper = scraper.login()

    assert wrapper['league_id'] == SLEEPER_LEAGUE_ID
    # Every endpoint is asked about the configured league exactly once.
    assert calls['league_id'] == [SLEEPER_LEAGUE_ID]
    assert calls['rosters'] == [SLEEPER_LEAGUE_ID]
    assert calls['users'] == [SLEEPER_LEAGUE_ID]
    assert scraper.loaded is True


def test_sleeper_standings_rank_by_wins_then_points(monkeypatch):
    # Two rosters tied at 8-6 must be split by points for, not roster order.
    users, rosters = make_sleeper_season((
        ('u1', 'alpha', 'Alpha', 1, 8, 6, 1700.0),
        ('u2', 'bravo', 'Bravo', 2, 10, 4, 1500.0),
        ('u3', 'charlie', 'Charlie', 3, 8, 6, 1900.0),
    ))
    patch_sleeper_api(monkeypatch, users=users, rosters=rosters)
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()

    # 10 wins first, then the 8-win pair ordered by points for.
    assert scraper.standings == {'2': 1, '3': 2, '1': 3}


def test_sleeper_get_members_shape(monkeypatch):
    users, rosters = make_sleeper_season((
        ('u1', 'alpha', 'Alpha Team', 1, 10, 4, 1800.0),
        ('u2', 'bravo', 'Bravo Team', 2, 4, 10, 1500.0),
    ))
    patch_sleeper_api(monkeypatch, users=users, rosters=rosters)
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()

    members = scraper.get_members()

    # Keyed by user_id -- the account id, stable across seasons -- while
    # team_id is the per-season roster id, as a string.
    assert set(members) == {'u1', 'u2'}
    assert members['u1'] == {
        'team_id': '1',
        'curr_name': 'Alpha Team',
        'curr_short': 'alpha',
        'commish': True,
        'standing': 1,
    }
    assert members['u2']['team_id'] == '2'
    assert members['u2']['standing'] == 2


def test_sleeper_get_members_falls_back_to_display_name(monkeypatch):
    # make_season drops the last member's team_name; Sleeper only stores one
    # once a manager sets it.
    patch_sleeper_api(monkeypatch)
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()

    members = scraper.get_members()
    last = members['859950573120794624']
    assert last['curr_name'] == 'seireikhaan'
    assert last['curr_short'] == 'seireikhaan'


def test_sleeper_get_members_marks_only_the_commissioner(monkeypatch):
    patch_sleeper_api(monkeypatch)
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()

    members = scraper.get_members()
    # is_owner comes back None rather than False for non-commissioners, so it
    # has to be coerced.
    assert members['738089321269194752']['commish'] is True
    assert all(m['commish'] is False for k, m in members.items()
               if k != '738089321269194752')


def test_sleeper_get_members_skips_users_without_a_roster(monkeypatch):
    users, rosters = make_sleeper_season((
        ('u1', 'alpha', 'Alpha', 1, 5, 5, 1500.0),
    ))
    users.append(make_user('spectator', 'watcher'))
    patch_sleeper_api(monkeypatch, users=users, rosters=rosters)
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()

    # A user in the league chat but not playing has no roster to rate.
    assert set(scraper.get_members()) == {'u1'}


def test_sleeper_season_length_and_playoff_start(monkeypatch):
    patch_sleeper_api(monkeypatch, league=make_league(playoff_week_start=15,
                                                     last_scored_leg=17))
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()

    assert scraper.get_current_season_length() == 17
    assert scraper.get_playoff_start() == 15


@pytest.mark.parametrize('absent', [0, None])
def test_sleeper_season_length_ignores_the_leg(monkeypatch, absent):
    # 'leg' is the week the league is on, not the number it has scored, so a
    # preseason league reports leg 1 with nothing played. Counting it would
    # rate a week that was never played.
    patch_sleeper_api(monkeypatch,
                      league=make_league(last_scored_leg=absent, leg=1))
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()
    assert scraper.get_current_season_length() == 0


def test_sleeper_season_length_counts_only_scored_weeks(monkeypatch):
    # Mid-season: week 5 is under way, four are on the books.
    patch_sleeper_api(monkeypatch, league=make_league(last_scored_leg=4, leg=5))
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()
    assert scraper.get_current_season_length() == 4


def test_sleeper_playoff_start_defaults_when_unset(monkeypatch):
    # Sleeper reports 0 until the schedule exists.
    patch_sleeper_api(monkeypatch, league=make_league(playoff_week_start=0))
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()
    assert scraper.get_playoff_start() == PLAYOFF_START


def test_sleeper_playoff_start_before_login_is_default():
    assert SleeperScraper(_sleeper_config()).get_playoff_start() == PLAYOFF_START


def test_sleeper_league_name(monkeypatch):
    patch_sleeper_api(monkeypatch, league=make_league(name='Die Nasty'))
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()
    assert scraper.get_league_name() == 'Die Nasty'


def test_sleeper_league_name_before_login_is_none():
    assert SleeperScraper(_sleeper_config()).get_league_name() is None


def test_sleeper_get_scoreboard_attaches_owner_ids(monkeypatch):
    users, rosters = make_sleeper_season((
        ('u1', 'alpha', 'Alpha', 1, 5, 5, 1500.0),
        ('u2', 'bravo', 'Bravo', 2, 5, 5, 1500.0),
    ))
    week = make_matchups([((1, 120.0), (2, 100.0))])
    calls = patch_sleeper_api(monkeypatch, users=users, rosters=rosters,
                              matchups=week)
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()

    board = scraper.get_scoreboard(3)

    assert calls['weeks'] == [(SLEEPER_LEAGUE_ID, 3)]
    # The formatter only receives the scoreboard, so the roster -> owner
    # mapping has to ride along on it.
    assert {entry['owner_id'] for entry in board} == {'u1', 'u2'}
    assert scraper.current_matchup is board


def test_sleeper_get_scoreboard_does_not_mutate_the_payload(monkeypatch):
    week = make_matchups([((1, 120.0), (2, 100.0))])
    users, rosters = make_sleeper_season((
        ('u1', 'alpha', 'Alpha', 1, 5, 5, 1500.0),
        ('u2', 'bravo', 'Bravo', 2, 5, 5, 1500.0),
    ))
    patch_sleeper_api(monkeypatch, users=users, rosters=rosters, matchups=week)
    scraper = SleeperScraper(_sleeper_config())
    scraper.login()

    scraper.get_scoreboard(1)

    assert all('owner_id' not in entry for entry in week)


def test_sleeper_missing_dependency_points_at_the_extra(monkeypatch):
    # The sleeper client is an optional extra, imported lazily, so a
    # Fantrax-only install must fail with a usable message rather than an
    # opaque ImportError at module scope.
    import sys
    monkeypatch.setitem(sys.modules, 'sleeper.api', None)
    with pytest.raises(ImportError, match=r'elo-system\[sleeper\]'):
        SleeperScraper(_sleeper_config()).login()
