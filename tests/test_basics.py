"""Tests for elo_system.tools.basics: LeagueBase, week_formatter, and constants."""
import time

import pytest

from elo_system.tools.basics import common_classes
from elo_system.tools.basics.common_classes import LeagueBase
from elo_system.tools.basics.common_funcs import week_formatter
from elo_system.tools.basics import constants


def freeze_localtime(monkeypatch, year, month):
    """Pin time.localtime() (as used inside common_classes) to a fixed date."""
    frozen = time.struct_time((year, month, 15, 12, 0, 0, 0, 165, 0))
    monkeypatch.setattr(common_classes.time, 'localtime', lambda: frozen)


# ---------------------------------------------------------------------------
# LeagueBase: config loading
# ---------------------------------------------------------------------------

def test_init_without_config_leaves_defaults():
    b = LeagueBase()
    assert b.current_sports_year is None
    assert b.league_type is None
    assert b.loaded is False


def test_load_config_no_level_keeps_whole_dict():
    cfg = {'a': 1, 'b': 2}
    b = LeagueBase(cfg)
    # level is None -> the config is taken as-is (same object).
    assert b.config is cfg
    assert b.config == {'a': 1, 'b': 2}


def test_load_config_with_level_indexes_sub_config():
    class Leveled(LeagueBase):
        level = 'inner'

    cfg = {'inner': {'x': 1}, 'other': {'y': 2}}
    obj = Leveled(cfg)
    assert obj.config == {'x': 1}
    assert obj.config is cfg['inner']


def test_load_config_public_method():
    b = LeagueBase()
    b.load_config({'k': 60})
    assert b.config == {'k': 60}


def test_load_config_explicit_level_parameter():
    b = LeagueBase()
    b._load_config({'sub': {'x': 1}}, level='sub')
    assert b.config == {'x': 1}


def test_update_config_merges_and_returns():
    cfg = {'a': 1}
    b = LeagueBase(cfg)
    out = b.update_config({'b': 2, 'a': 3})
    assert out is b.config
    assert b.config == {'a': 3, 'b': 2}
    # Intentional: config is held by reference, not copied, so one EloLeague
    # config dict can be loaded by every component and receive their dumps.
    assert cfg == {'a': 3, 'b': 2}


def test_instances_do_not_share_config_state():
    a = LeagueBase()
    b = LeagueBase()
    a.update_config({'marker': 1})
    assert b.config == {}


# ---------------------------------------------------------------------------
# LeagueBase: sports-year logic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    'league_type, year, month, expected',
    [
        # NBA season year flips in July: before July it is still last year's season.
        ('nba', 2025, 6, 2024),
        ('nba', 2025, 7, 2025),
        ('nba', 2025, 1, 2024),
        ('nba', 2025, 12, 2025),
        # NFL season year flips in March.
        ('nfl', 2026, 2, 2025),
        ('nfl', 2026, 3, 2026),
        ('nfl', 2026, 12, 2026),
        # Unknown league type -> plain calendar year.
        (None, 2025, 1, 2025),
        ('mlb', 2025, 2, 2025),
    ],
)
def test_get_current_sports_year(monkeypatch, league_type, year, month, expected):
    freeze_localtime(monkeypatch, year, month)
    b = LeagueBase()
    b.league_type = league_type
    assert b.get_current_sports_year() == expected


def test_set_current_sports_year_explicit():
    b = LeagueBase()
    b.set_current_sports_year(2019)
    assert b.current_sports_year == 2019


def test_set_current_sports_year_none_computes(monkeypatch):
    freeze_localtime(monkeypatch, 2025, 8)
    b = LeagueBase()
    b.league_type = 'nba'
    b.set_current_sports_year(None)
    assert b.current_sports_year == 2025


# ---------------------------------------------------------------------------
# LeagueBase: load / dump / publish round trip
# ---------------------------------------------------------------------------

def test_load_reads_year_from_config():
    b = LeagueBase({'current_sports_year': 2023})
    out = b.load()
    assert b.current_sports_year == 2023
    assert b.loaded is True
    assert out is b.config


def test_load_falls_back_to_computed_year(monkeypatch):
    freeze_localtime(monkeypatch, 2025, 8)
    b = LeagueBase({})
    b.league_type = 'nba'
    b.load()
    assert b.current_sports_year == 2025


def test_dump_writes_year_back():
    b = LeagueBase({'current_sports_year': 2023})
    b.load()
    b.current_sports_year = 2030
    out = b.dump()
    assert out['current_sports_year'] == 2030
    assert out is b.config


def test_load_dump_round_trip():
    cfg = {'current_sports_year': 2024, 'extra': 'kept'}
    b = LeagueBase(cfg)
    b.load()
    dumped = b.dump()
    assert dumped == {'current_sports_year': 2024, 'extra': 'kept'}


def test_publish_returns_config_payload():
    cfg = {'current_sports_year': 2024}
    b = LeagueBase(cfg)
    payload = b.publish()
    assert payload == {'config': cfg}
    assert payload['config'] is cfg


# ---------------------------------------------------------------------------
# week_formatter
# ---------------------------------------------------------------------------

def test_week_formatter_single_int_string():
    out = week_formatter('7')
    assert isinstance(out, int)
    assert out == 7


def test_week_formatter_zero():
    assert week_formatter('0') == 0


def test_week_formatter_range_is_inclusive():
    out = week_formatter('1:4')
    assert isinstance(out, range)
    assert list(out) == [1, 2, 3, 4]


def test_week_formatter_range_from_zero():
    assert list(week_formatter('0:3')) == [0, 1, 2, 3]


def test_week_formatter_multi_colon_uses_first_and_last():
    # 'a:b:c' takes the first and last components.
    assert list(week_formatter('1:3:5')) == [1, 2, 3, 4, 5]


@pytest.mark.parametrize('bad', ['abc', '', '1:b', ':', '3:'])
def test_week_formatter_invalid_strings_raise_value_error(bad):
    with pytest.raises(ValueError):
        week_formatter(bad)


def test_week_formatter_rejects_raw_int():
    # Current behavior: the function is string-only (callers such as
    # EloLeague.run guard with isinstance before calling it).
    with pytest.raises(AttributeError):
        week_formatter(7)


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

def test_week_str_template():
    assert constants.WEEK_STR == 'week_{}'
    assert constants.WEEK_STR.format(0) == 'week_0'
    assert constants.WEEK_STR.format(12) == 'week_12'


def test_playoff_start():
    assert constants.PLAYOFF_START == 3


def test_roto_cols():
    assert isinstance(constants.ROTO_COLS, set)
    assert constants.ROTO_COLS == {
        'FG%', 'FT%', '3PTM', 'PTS', 'REB', 'AST', 'ST', 'BLK', 'TO'
    }
    assert len(constants.ROTO_COLS) == 9
