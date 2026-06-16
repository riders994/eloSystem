"""Tests for elo_system.tools.basics.constants.

Asserts the public names exist with their intended types and values.

``ROTO_SCORING`` is the set of NBA roto category abbreviations (used by
formatter.roto_calc); ``ROTO_COLS`` is the list of fact-table column names
(used by elo_data.EloSQL). They are distinct names with distinct purposes.
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
        'score',
    ]


def test_roto_scoring_is_the_category_set():
    # The roto category abbreviations live under ROTO_SCORING, kept distinct
    # from the ROTO_COLS column list (formerly a name collision).
    assert isinstance(constants.ROTO_SCORING, set)
    assert constants.ROTO_SCORING == {
        'FG%', 'FT%', '3PTM', 'PTS', 'REB', 'AST', 'ST', 'BLK', 'TO'
    }
    assert 'FG%' not in constants.ROTO_COLS
