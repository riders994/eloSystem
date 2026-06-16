"""Tests for the non-DB logic of elo_system.tools.elo_data.EloSQL.

No real database is touched: a fake connector object is passed to the
constructor and pandas' read functions are monkeypatched.
"""
import pandas as pd
import pytest

import elo_system.tools.elo_data as elo_data
from elo_system.tools.elo_data import EloSQL
from elo_system.tools.basics.constants import ELO_COLS


VALID_CONN = {
    'dbname': 'mydb',
    'user': 'alice',
    'password': 'secret',
    'port': 5432,
    'host': 'localhost',
}


class FakeConn:
    """Stand-in for a psycopg2 connection; never actually used by these tests
    because all read/write paths are monkeypatched."""
    pass


@pytest.fixture
def patch_read_sql(monkeypatch):
    """Make reset_dims()/pull_dims() return empty frames instead of hitting a DB.
    Records the dim table names ('dim_team', ...) parsed from each query."""
    requested = []

    def fake_read_sql_query(sql, con, index_col=None):
        # _pull_dim issues 'SELECT * FROM <schema>.dim_<dim>'.
        requested.append(sql.split('.')[-1].strip())
        return pd.DataFrame()

    monkeypatch.setattr(elo_data.pd, 'read_sql_query', fake_read_sql_query)
    return requested


def make_elosql(monkeypatch, patch_read_sql, config):
    return EloSQL(config, connector=FakeConn())


# ---------------------------------------------------------------------------
# __init__ connection resolution
# ---------------------------------------------------------------------------

def test_init_with_conn_dict(monkeypatch, patch_read_sql):
    obj = make_elosql(monkeypatch, patch_read_sql, {'conn_dict': VALID_CONN})
    assert obj.conn_dict == VALID_CONN
    assert isinstance(obj.conn, FakeConn)


def test_init_with_conn_uri(monkeypatch, patch_read_sql):
    uri = 'postgresql://alice:secret@localhost:5432/mydb'
    obj = make_elosql(monkeypatch, patch_read_sql, {'conn_uri': uri})
    assert obj.conn_dict == {
        'dbname': 'mydb',
        'user': 'alice',
        'password': 'secret',
        'port': 5432,
        'host': 'localhost',
    }


def test_init_no_connection_details_raises(monkeypatch, patch_read_sql):
    with pytest.raises(KeyError, match='No connection details supplied'):
        EloSQL({}, connector=FakeConn())


def test_init_default_schema(monkeypatch, patch_read_sql):
    obj = make_elosql(monkeypatch, patch_read_sql, {'conn_dict': VALID_CONN})
    assert obj.schema == 'fantasy_sports'


def test_init_schema_override_from_config(monkeypatch, patch_read_sql):
    obj = make_elosql(
        monkeypatch, patch_read_sql,
        {'conn_dict': VALID_CONN, 'schema': 'custom_schema'},
    )
    assert obj.schema == 'custom_schema'


def test_init_calls_reset_dims_for_all_elo_dims(monkeypatch, patch_read_sql):
    make_elosql(monkeypatch, patch_read_sql, {'conn_dict': VALID_CONN})
    # reset_dims pulls every ELO_DIM as dim_<name>
    assert set(patch_read_sql) == {'dim_league', 'dim_manager', 'dim_team'}


def test_init_does_not_call_connect_when_connector_given(monkeypatch, patch_read_sql):
    def boom(*a, **k):
        raise AssertionError('connect() should not be called when connector given')

    monkeypatch.setattr(elo_data, 'connect', boom)
    obj = make_elosql(monkeypatch, patch_read_sql, {'conn_dict': VALID_CONN})
    assert isinstance(obj.conn, FakeConn)


# ---------------------------------------------------------------------------
# _pull_dim caching behaviour
# ---------------------------------------------------------------------------

def test_pull_dim_skips_when_present_and_not_overwrite(monkeypatch, patch_read_sql):
    obj = make_elosql(monkeypatch, patch_read_sql, {'conn_dict': VALID_CONN})
    patch_read_sql.clear()

    # 'team' is already cached by reset_dims, so overwrite=False must skip it.
    assert obj._pull_dim('team', overwrite=False) is True
    assert patch_read_sql == []


def test_pull_dim_reads_when_overwrite(monkeypatch, patch_read_sql):
    obj = make_elosql(monkeypatch, patch_read_sql, {'conn_dict': VALID_CONN})
    patch_read_sql.clear()

    assert obj._pull_dim('team', overwrite=True) is True
    assert patch_read_sql == ['dim_team']


def test_pull_dim_reads_when_absent(monkeypatch, patch_read_sql):
    obj = make_elosql(monkeypatch, patch_read_sql, {'conn_dict': VALID_CONN})
    patch_read_sql.clear()
    obj.dim_tables.pop('manager')

    assert obj._pull_dim('manager', overwrite=False) is True
    assert patch_read_sql == ['dim_manager']


# ---------------------------------------------------------------------------
# _elo_publish_prep sets the is_dynasty column
# ---------------------------------------------------------------------------

def _seed_dims_for_publish(obj):
    """Minimal manager/team dims so the inner merge yields one row."""
    obj.dim_tables['manager'] = pd.DataFrame(
        {
            'manager_id': [1],
            'discord_id': [100],
            'manager_name': ['Alice'],
        }
    )
    obj.dim_tables['team'] = pd.DataFrame(
        {
            'manager_id': [1],
            'platform_team_id': ['T1'],
            'league_year': [2024],
            'team_id': [10],
            'league_id': [5],
        }
    )


def test_elo_publish_prep_sets_is_dynasty_false(monkeypatch, patch_read_sql):
    obj = make_elosql(monkeypatch, patch_read_sql, {'conn_dict': VALID_CONN})
    _seed_dims_for_publish(obj)
    obj.curr_league_config = {'is_dynasty': False}
    obj.current_frame = pd.DataFrame(
        {
            'platform_team_id': ['T1'],
            'league_year': [2024],
            'week': [1],
            'elo': [1500.0],
        }
    )

    obj._elo_publish_prep()

    assert 'is_dynasty' in obj.current_frame.columns
    assert list(obj.current_frame['is_dynasty']) == [False]
    # final projection is exactly ELO_COLS
    assert list(obj.current_frame.columns) == ELO_COLS


def test_elo_publish_prep_dynasty_calls_set_dynasty_season(monkeypatch, patch_read_sql):
    obj = make_elosql(monkeypatch, patch_read_sql, {'conn_dict': VALID_CONN})
    _seed_dims_for_publish(obj)
    obj.curr_league_config = {'is_dynasty': True}
    obj.current_frame = pd.DataFrame(
        {
            'platform_team_id': ['T1'],
            'league_year': [9999],  # will be overwritten by _set_dynasty_season
            'week': [0],
            'elo': [1500.0],
        }
    )

    called = {'n': 0}
    real_set = obj._set_dynasty_season

    def spy():
        called['n'] += 1
        return real_set()

    # provide seasons so _set_dynasty_season can run
    obj.curr_league_config['seasons'] = {2024: {'current_season_length': 0}}
    monkeypatch.setattr(obj, '_set_dynasty_season', spy)

    obj._elo_publish_prep()

    assert called['n'] == 1
    assert list(obj.current_frame['is_dynasty']) == [True]
