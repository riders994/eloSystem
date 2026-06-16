"""Tests for elo_system.tools.basics.constants.

Asserts the public names exist with their intended types and values.

NOTE: constants.py defines ``ROTO_COLS`` twice -- first as a set of roto
category abbreviations, then (lower in the file) as a list of fact-table
column names. The second definition shadows the first, so the set of
category abbreviations is unreachable. See test_roto_cols_collision below.
"""
import elo_system.tools.basics.constants as constants


def test_elo_dims_value_and_type():
    assert isinstance(constants.ELO_DIMS, set)
    assert constants.ELO_DIMS == {'league', 'manager', 'team'}


def test_elo_cols_value_and_type():
    assert isinstance(constants.ELO_COLS, list)
    assert constants.ELO_COLS == [
        'team_id',
        'league_id',
        'league_year',
        'manager_id',
        'manager_name',
        'is_dynasty',
        'week',
        'elo',
    ]


def test_approved_sql_flavors():
    assert isinstance(constants.APPROVED_SQL_FLAVORS, set)
    assert constants.APPROVED_SQL_FLAVORS == {'postgresql', None}


def test_week_str_and_playoff_start():
    assert constants.WEEK_STR == 'week_{}'
    assert constants.WEEK_STR.format(3) == 'week_3'
    assert constants.PLAYOFF_START == 3


def test_roto_cols_is_the_column_list():
    # elo_data.EloSQL._roto_frame_prep uses ROTO_COLS as a list of column
    # names to select, so the active definition must be the list.
    assert isinstance(constants.ROTO_COLS, list)
    assert constants.ROTO_COLS == [
        'team_id',
        'league_id',
        'league_year',
        'manager_id',
        'manager_name',
        'week',
        'roto',
    ]


def test_roto_cols_collision():
    """ROTO_COLS is defined twice; the category-abbreviation set is lost.

    This documents the name collision flagged in the module docstring. The
    list shadows the earlier set, so the abbreviations ('FG%', 'PTS', ...)
    are not accessible under ROTO_COLS.
    """
    assert not isinstance(constants.ROTO_COLS, set)
    assert 'FG%' not in constants.ROTO_COLS
