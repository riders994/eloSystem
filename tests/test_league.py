"""Tests for elo_system.tools.league (League / FantraxLeague).

A League is constructed with a year and a config dict keyed by year (the
``league_years`` mapping from the resource yml). Loading a FantraxLeague
builds a FantraxScraper and logs in, so ft.League is monkeypatched on the
scraper module's imported name -- no network access.
"""
import pytest

from elo_system.tools.helpers import scraper as scraper_mod
from elo_system.tools.helpers.league import FantraxLeague
from elo_system.tools.helpers.scraper import FantraxScraper

from tests.mocks.fantrax import (
    make_default_teams,
    make_mock_league_cls,
    make_season,
)

YEAR = 2025
LEAGUE_ID = 'lgabc999'

# 6-week season: weeks 1-4 regular, weeks 5-6 playoffs.
PLAYOFF_FLAGS = [False, False, False, False, True, True]


def make_year_config(**overrides):
    cfg = {'league_id': LEAGUE_ID, 'members': {}}
    cfg.update(overrides)
    return {YEAR: cfg}


@pytest.fixture
def teams():
    return make_default_teams(4)


@pytest.fixture
def patched_ft(monkeypatch, teams):
    periods = make_season(teams, PLAYOFF_FLAGS)
    mock_cls = make_mock_league_cls(scoring_periods=periods, teams=teams)
    monkeypatch.setattr(scraper_mod.ft, 'League', mock_cls)
    return mock_cls, periods


# ---------------------------------------------------------------------------
# Config handling
# ---------------------------------------------------------------------------

def test_year_selects_config_level(patched_ft):
    other = {'league_id': 'oldid', 'members': {}}
    cfg_2025 = {'league_id': LEAGUE_ID, 'members': {}}
    league = FantraxLeague(YEAR, {2024: other, YEAR: cfg_2025})
    assert league.config is cfg_2025


def test_load_reads_config_values(patched_ft):
    config = make_year_config(
        consolation_elo=False,
        current_season_length=24,
        dynasty_start_week=3,
        last_scored_week=20,
        league_members={'owner_x': {'curr_name': 'X'}},
        playoff_start=22,
    )
    league = FantraxLeague(YEAR, config)
    league.load()

    assert league.league_id == LEAGUE_ID
    assert league.consolation_elo is False
    assert league.current_season_length == 24
    assert league.dynasty_start_week == 3
    assert league.last_scored_week == 20
    assert league.league_members == {'owner_x': {'curr_name': 'X'}}
    assert league.playoff_start == 22
    assert league.loaded is True


def test_load_defaults_when_config_minimal(patched_ft):
    league = FantraxLeague(YEAR, make_year_config())
    league.load()
    assert league.current_season_length == 1
    assert league.dynasty_start_week == 0
    assert league.last_scored_week is None
    assert league.league_members == {}


def test_dump_round_trips_attributes_into_config(patched_ft):
    config = make_year_config()
    league = FantraxLeague(YEAR, config)
    league.load()

    league.current_season_length = 30
    league.dynasty_start_week = 4
    league.last_scored_week = 12
    league.playoff_start = 21
    league.league_members = {'owner_y': {'curr_name': 'Y'}}
    dumped = league.dump()

    assert dumped is league.config is config[YEAR]
    assert dumped['current_season_length'] == 30
    assert dumped['dynasty_start_week'] == 4
    assert dumped['last_scored_week'] == 12
    assert dumped['playoff_start'] == 21
    assert dumped['league_id'] == LEAGUE_ID
    assert dumped['league_members'] == {'owner_y': {'curr_name': 'Y'}}


# ---------------------------------------------------------------------------
# Scraper generation
# ---------------------------------------------------------------------------

def test_load_generates_logged_in_fantrax_scraper(patched_ft):
    mock_cls, periods = patched_ft
    league = FantraxLeague(YEAR, make_year_config(playoff_start=22))
    league.load()

    assert isinstance(league.scraper, FantraxScraper)
    assert league.scraper.league_id == LEAGUE_ID
    # login happened against the (mocked) ft.League
    assert len(mock_cls.instances) == 1
    assert league.scraper.league_wrapper is mock_cls.instances[0]
    assert league.scraper.scoring_periods == periods
    # scraper config seeded from league config
    assert league.scraper.config['league_id'] == LEAGUE_ID
    assert league.scraper.config['playoff_start'] == 22


def test_construction_does_not_hit_scraper(patched_ft):
    mock_cls, _ = patched_ft
    FantraxLeague(YEAR, make_year_config())
    # Only load()/scrape() should log in.
    assert mock_cls.instances == []


# ---------------------------------------------------------------------------
# scrape()
# ---------------------------------------------------------------------------

def test_scrape_populates_season_length_playoffs_and_members(patched_ft, teams):
    league = FantraxLeague(YEAR, make_year_config())
    result = league.scrape()

    assert league.current_season_length == len(PLAYOFF_FLAGS)
    assert league.playoff_start == 5  # first playoff week in PLAYOFF_FLAGS

    assert set(league.league_members) == {t.owners for t in teams}
    first = teams[0]
    assert league.league_members[first.owners] == {
        'curr_name': first.name,
        'names': [first.name],
        'short_name': first.short,
        # The account's own name, carried through so the SQL side can file the
        # member under it in dim_manager_platform.
        'display_name': first.owners,
        'team_id': first.id,
        'is_commish': True,
        'standing': 1,
    }

    # scrape() returns the dumped config
    assert result is league.config
    assert result['current_season_length'] == len(PLAYOFF_FLAGS)
    assert result['playoff_start'] == 5
    assert result['league_members'] is league.league_members


def test_scrape_updates_existing_member_and_keeps_name_history(patched_ft, teams):
    first = teams[0]
    existing = {
        first.owners: {
            'curr_name': 'Original Name',
            'names': ['Original Name'],
            'short_name': 'OLD',
            'team_id': 'oldteamid',
            'is_commish': False,
        }
    }
    league = FantraxLeague(YEAR, make_year_config(league_members=existing))
    league.scrape()

    info = league.league_members[first.owners]
    # reset_members overwrites curr_name and appends to the name history
    assert info['curr_name'] == first.name
    assert info['names'] == ['Original Name', first.name]
    assert info['short_name'] == first.short
    assert info['team_id'] == first.id
    assert info['is_commish'] is True


def test_repeated_scrapes_do_not_duplicate_the_name_history(patched_ft, teams):
    first = teams[0]
    league = FantraxLeague(YEAR, make_year_config())
    league.scrape()
    league.scrape()
    league.scrape()

    # Every scrape reports the current name; only a new one belongs in history.
    assert league.league_members[first.owners]['names'] == [first.name]


def test_scrape_appends_a_genuinely_new_name_to_the_history(patched_ft, teams):
    first = teams[0]
    existing = {
        first.owners: {
            'curr_name': 'Original Name',
            'names': ['Original Name'],
            'short_name': 'OLD',
            'team_id': 'oldteamid',
            'is_commish': False,
            'standing': 100,
        }
    }
    league = FantraxLeague(YEAR, make_year_config(league_members=existing))
    league.scrape()
    league.scrape()

    assert league.league_members[first.owners]['names'] == ['Original Name', first.name]


def test_scrape_stores_the_standing_for_every_member(patched_ft, teams):
    league = FantraxLeague(YEAR, make_year_config())
    league.scrape()

    # make_standings ranks the mock teams in order, 1-based.
    standings = {owner: info['standing']
                 for owner, info in league.league_members.items()}
    assert standings == {team.owners: rank
                         for rank, team in enumerate(teams, 1)}


def test_scrape_refreshes_the_standing_of_an_existing_member(patched_ft, teams):
    first = teams[0]
    existing = {
        first.owners: {
            'curr_name': 'Original Name',
            'names': ['Original Name'],
            'short_name': 'OLD',
            'team_id': 'oldteamid',
            'is_commish': False,
            'standing': 100,
        }
    }
    league = FantraxLeague(YEAR, make_year_config(league_members=existing))
    league.scrape()

    # The stale placeholder is replaced by the scraped rank, so a finished
    # season's place_finish reaches the dims on the next sync.
    assert league.league_members[first.owners]['standing'] == 1


def test_set_overrides_take_explicit_values(patched_ft):
    league = FantraxLeague(YEAR, make_year_config())
    league.load()
    league.set_current_season_length(40)
    league.set_playoff_start(33)
    assert league.current_season_length == 40
    assert league.playoff_start == 33
    # None falls back to scraper-derived values
    league.set_current_season_length(None)
    league.set_playoff_start(None)
    assert league.current_season_length == len(PLAYOFF_FLAGS)
    assert league.playoff_start == 5


# ---------------------------------------------------------------------------
# get_week()
# ---------------------------------------------------------------------------

def test_get_week_explicit_delegates_to_scraper(patched_ft):
    _, periods = patched_ft
    league = FantraxLeague(YEAR, make_year_config())
    league.load()
    assert league.get_week(3) is periods[3]
    assert league.scraper.current_matchup is periods[3]


def test_get_week_defaults_to_last_scored_week(patched_ft):
    _, periods = patched_ft
    league = FantraxLeague(YEAR, make_year_config(last_scored_week=2))
    league.load()
    assert league.get_week() is periods[2]


def test_get_week_falls_back_to_current_season_length(patched_ft):
    _, periods = patched_ft
    league = FantraxLeague(YEAR, make_year_config(current_season_length=4))
    league.load()
    assert league.last_scored_week is None
    assert league.get_week() is periods[4]


def test_scrape_captures_the_platform_league_name(monkeypatch, teams):
    mock_cls = make_mock_league_cls(scoring_periods=make_season(teams, PLAYOFF_FLAGS),
                                    teams=teams, name="Mao's Macho Mandarins")
    monkeypatch.setattr(scraper_mod.ft, 'League', mock_cls)
    league = FantraxLeague(YEAR, make_year_config())
    dumped = league.scrape()

    assert league.league_name == "Mao's Macho Mandarins"
    assert dumped['league_name'] == "Mao's Macho Mandarins"
