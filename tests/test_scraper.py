"""Tests for elo_system.tools.scraper (LeagueScraper and FantraxScraper).

FantraxScraper.login() is wired to ft.League, which we monkeypatch on the
module's imported name so no test ever touches the network.
"""
import pytest

from elo_system.tools.helpers import scraper as scraper_mod
from elo_system.tools.helpers.scraper import PLAYOFF_START, FantraxScraper, LeagueScraper

from tests.mocks.fantrax import (
    make_default_teams,
    make_mock_league_cls,
    make_season,
)

LEAGUE_ID = 'lg123abc'


class _ConcreteScraper(LeagueScraper):
    """Minimal concrete scraper for exercising the shared base plumbing."""

    def login(self):
        pass

    def get_members(self):
        return {}

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
        'login', 'get_members', 'get_scoreboard',
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
    }
    # Only the first default team is the commissioner.
    assert [info['commish'] for info in members.values()].count(True) == 1


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
