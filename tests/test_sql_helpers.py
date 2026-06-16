"""Tests for elo_system.tools.sql_helpers.helpers.upsert_dataframe.

Uses a fake connection/cursor and stubs psycopg2.extras.execute_values (as
imported into the helpers module), so no database is ever touched.
"""
import numpy as np
import pandas as pd
import pytest

import elo_system.tools.helpers.helper_funcs as helpers
from elo_system.tools.helpers.helper_funcs import upsert_dataframe


class FakeCursor:
    def __init__(self):
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited = True
        return False


class FakeConn:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.commits = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1


@pytest.fixture
def conn():
    return FakeConn()


@pytest.fixture
def calls(monkeypatch):
    """Capture (cursor, sql, records) passed to execute_values."""
    recorded = []

    def fake_execute_values(cur, sql, records):
        recorded.append({'cur': cur, 'sql': sql, 'records': records})

    monkeypatch.setattr(helpers, 'execute_values', fake_execute_values)
    return recorded


def norm(sql):
    return ' '.join(sql.split())


# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------

def test_generated_sql_default_schema(conn, calls):
    df = pd.DataFrame({'id': [1, 2], 'score': [10.0, 20.0]})
    count = upsert_dataframe(conn, df, 'ratings', ['id'])

    assert count == 2
    assert len(calls) == 1
    sql = norm(calls[0]['sql'])
    assert 'INSERT INTO "public"."ratings" ("id", "score")' in sql
    assert 'VALUES %s' in sql
    assert 'ON CONFLICT ("id")' in sql
    assert 'DO UPDATE SET "score" = EXCLUDED."score"' in sql
    # The conflict-target column must not be in the update set.
    assert '"id" = EXCLUDED."id"' not in sql


def test_generated_sql_custom_schema(conn, calls):
    df = pd.DataFrame({'id': [1], 'score': [10.0]})
    upsert_dataframe(conn, df, 'elo_history', ['id'], schema='fantasy')
    sql = norm(calls[0]['sql'])
    assert 'INSERT INTO "fantasy"."elo_history"' in sql


def test_generated_sql_multiple_match_columns(conn, calls):
    df = pd.DataFrame({
        'member': ['a', 'b'],
        'week': [1, 1],
        'elo': [1530.0, 1470.0],
        'rank': [1, 2],
    })
    upsert_dataframe(conn, df, 'weekly', ['member', 'week'])
    sql = norm(calls[0]['sql'])
    assert 'ON CONFLICT ("member", "week")' in sql
    assert 'DO UPDATE SET "elo" = EXCLUDED."elo", "rank" = EXCLUDED."rank"' in sql


# ---------------------------------------------------------------------------
# record conversion
# ---------------------------------------------------------------------------

def test_records_passed_as_tuples(conn, calls):
    df = pd.DataFrame({'id': [1, 2], 'score': [10.0, 20.0]})
    upsert_dataframe(conn, df, 'ratings', ['id'])
    records = calls[0]['records']
    assert records == [(1, 10.0), (2, 20.0)]
    assert all(isinstance(r, tuple) for r in records)


def test_nan_converted_to_none(conn, calls):
    df = pd.DataFrame({
        'id': [1, 2, 3],
        'score': [10.0, np.nan, 30.0],
        'label': ['a', 'b', None],
    })
    count = upsert_dataframe(conn, df, 'ratings', ['id'])
    assert count == 3
    records = calls[0]['records']
    assert records[0] == (1, 10.0, 'a')
    assert records[1][1] is None
    assert records[1][2] == 'b'
    assert records[2][2] is None


def test_execute_uses_connection_cursor(conn, calls):
    df = pd.DataFrame({'id': [1], 'score': [1.0]})
    upsert_dataframe(conn, df, 'ratings', ['id'])
    assert calls[0]['cur'] is conn.cursor_obj
    assert conn.cursor_obj.exited is True


# ---------------------------------------------------------------------------
# return value / commit behavior
# ---------------------------------------------------------------------------

def test_returns_row_count_and_commits_once(conn, calls):
    df = pd.DataFrame({'id': list(range(5)), 'score': [1.0] * 5})
    assert upsert_dataframe(conn, df, 'ratings', ['id']) == 5
    assert conn.commits == 1


def test_no_commit_when_execute_raises(conn, monkeypatch):
    def boom(cur, sql, records):
        raise RuntimeError('db down')

    monkeypatch.setattr(helpers, 'execute_values', boom)
    df = pd.DataFrame({'id': [1], 'score': [1.0]})
    with pytest.raises(RuntimeError, match='db down'):
        upsert_dataframe(conn, df, 'ratings', ['id'])
    assert conn.commits == 0


# ---------------------------------------------------------------------------
# empty frame / validation errors
# ---------------------------------------------------------------------------

def test_empty_dataframe_returns_zero_without_touching_db(conn, calls):
    assert upsert_dataframe(conn, pd.DataFrame(), 'ratings', ['id']) == 0
    assert upsert_dataframe(
        conn, pd.DataFrame(columns=['id', 'score']), 'ratings', ['id']
    ) == 0
    assert calls == []
    assert conn.commits == 0


def test_missing_match_column_raises(conn, calls):
    df = pd.DataFrame({'id': [1], 'score': [1.0]})
    with pytest.raises(ValueError, match='nope'):
        upsert_dataframe(conn, df, 'ratings', ['nope'])
    assert calls == []


def test_all_columns_in_match_columns_does_nothing(conn, calls):
    # When every column is a match column there is nothing to update, so the
    # generated SQL uses ON CONFLICT ... DO NOTHING rather than raising.
    df = pd.DataFrame({'id': [1], 'week': [2]})
    count = upsert_dataframe(conn, df, 'ratings', ['id', 'week'])
    assert count == 1
    sql = norm(calls[0]['sql'])
    assert 'ON CONFLICT ("id", "week")' in sql
    assert 'DO NOTHING' in sql
    assert 'DO UPDATE' not in sql
