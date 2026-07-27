"""Tests for elo_system.tools.basics.constants.

Asserts the public names exist with their intended types and values.

``ROTO_COLS`` is the set of NBA roto category abbreviations (used by
formatter.roto_calc); ``ROTO_DB_COLS`` is the list of fact-table column names
(used by elo_data.EloSQL). They are distinct names with distinct purposes.
"""
import elo_system.tools.basics.constants as constants


def test_elo_dims_value_and_type():
    assert isinstance(constants.ELO_DIMS, set)
    assert constants.ELO_DIMS == {'league', 'manager', 'online_league', 'team'}


def test_elo_dim_cols_cover_every_dim():
    assert set(constants.ELO_DIM_COLS) == constants.ELO_DIMS
    for dim, cols in constants.ELO_DIM_COLS.items():
        # Each dim leads with its own surrogate key.
        assert cols[0] == '{}_id'.format(dim)


def test_rating_db_cols_is_the_seasonal_column_list():
    assert isinstance(constants.RATING_DB_COLS, list)
    assert constants.RATING_DB_COLS == [
        'team_id',
        'online_league_id',
        'manager_id',
        'manager_name',
        'week',
        'elo',
    ]


def test_dynasty_db_cols_hang_off_the_league_not_the_season():
    # Dynasty elos span seasons, so they carry league_id where the seasonal
    # table carries online_league_id.
    assert constants.DYNASTY_DB_COLS == [
        'team_id',
        'league_id',
        'manager_id',
        'manager_name',
        'week',
        'elo',
    ]
    assert 'online_league_id' not in constants.DYNASTY_DB_COLS


def test_approved_sql_flavors():
    assert isinstance(constants.APPROVED_SQL_FLAVORS, set)
    assert constants.APPROVED_SQL_FLAVORS == {'postgresql', None}


def test_week_str_and_playoff_start():
    assert constants.WEEK_STR == 'week_{}'
    assert constants.WEEK_STR.format(3) == 'week_3'
    assert constants.PLAYOFF_START == 3


def test_roto_db_cols_is_the_column_list():
    # elo_data.EloSQL projects onto ROTO_DB_COLS before writing, so the active
    # definition must be the list.
    assert isinstance(constants.ROTO_DB_COLS, list)
    assert constants.ROTO_DB_COLS == [
        'team_id',
        'online_league_id',
        'manager_id',
        'manager_name',
        'week',
        'score',
    ]


def test_fact_specs_cover_every_publish_destination():
    assert set(constants.FACT_SPECS) == {'dynasty_elo', 'seasonal_elo', 'roto_history'}
    for spec in constants.FACT_SPECS.values():
        assert spec['table'].startswith('fact_')
        assert spec['scope'] in spec['columns']
        assert spec['value'] == spec['columns'][-1]


def test_fact_specs_point_each_destination_at_its_own_table():
    tables = {name: spec['table'] for name, spec in constants.FACT_SPECS.items()}
    assert tables == {
        'dynasty_elo': 'fact_dynasty_elos',
        'seasonal_elo': 'fact_seasonal_elos',
        'roto_history': 'fact_rotos',
    }


def test_roto_cols_is_the_category_set():
    # The roto category abbreviations live under ROTO_COLS (the original public
    # name), kept distinct from the ROTO_DB_COLS column list.
    assert isinstance(constants.ROTO_COLS, set)
    assert constants.ROTO_COLS == {
        'FG%', 'FT%', '3PTM', 'PTS', 'REB', 'AST', 'ST', 'BLK', 'TO'
    }
    assert 'FG%' not in constants.ROTO_DB_COLS
