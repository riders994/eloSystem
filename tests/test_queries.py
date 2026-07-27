"""Tests for elo_system.tools.basics.queries.

Guards the LOAD_ELO / LOAD_ROTO SQL templates against missing or renamed
``{}`` placeholders and against accidental edits to their WHERE clause and the
``rating`` alias. The table and the scoping column are supplied by the caller
out of FACT_SPECS, so one template serves every elo fact table.
"""
import string

import pytest

from elo_system.tools.basics.constants import FACT_SPECS
from elo_system.tools.basics.queries import LOAD_ELO, LOAD_QUERIES, LOAD_ROTO


def norm(sql):
    return ' '.join(sql.split())


def fields(template):
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


# ---------------------------------------------------------------------------
# LOAD_ELO
# ---------------------------------------------------------------------------

def test_load_elo_formats_with_expected_kwargs():
    sql = LOAD_ELO.format(
        schema='fantasy_sports',
        table='fact_seasonal_elos',
        scope_col='online_league_id',
        scope_id=42,
    )
    flat = norm(sql)
    assert 'FROM fantasy_sports.fact_seasonal_elos' in flat
    assert flat.endswith('WHERE online_league_id = 42')
    # the rating alias is part of the contract for downstream score_unpivot
    assert 'elo AS rating' in flat
    assert 'team_id' in flat
    assert 'week' in flat


def test_load_elo_serves_the_dynasty_table_too():
    flat = norm(LOAD_ELO.format(
        schema='s', table='fact_dynasty_elos', scope_col='league_id', scope_id=7))
    assert 'FROM s.fact_dynasty_elos' in flat
    assert flat.endswith('WHERE league_id = 7')


def test_load_elo_requires_all_placeholders():
    # Missing any of the four named fields must raise (guards renames).
    for missing in ('schema', 'table', 'scope_col', 'scope_id'):
        kwargs = {
            'schema': 's', 'table': 'fact_seasonal_elos',
            'scope_col': 'online_league_id', 'scope_id': 1,
        }
        del kwargs[missing]
        with pytest.raises(KeyError):
            LOAD_ELO.format(**kwargs)


def test_load_elo_has_exactly_expected_fields():
    assert fields(LOAD_ELO) == {'schema', 'table', 'scope_col', 'scope_id'}


# ---------------------------------------------------------------------------
# LOAD_ROTO
# ---------------------------------------------------------------------------

def test_load_roto_formats_with_expected_kwargs():
    sql = LOAD_ROTO.format(
        schema='fantasy_sports',
        table='fact_rotos',
        scope_col='online_league_id',
        scope_id=7,
    )
    flat = norm(sql)
    assert 'FROM fantasy_sports.fact_rotos' in flat
    assert flat.endswith('WHERE online_league_id = 7')
    assert 'score AS rating' in flat
    assert 'team_id' in flat
    assert 'week' in flat


def test_load_roto_requires_all_placeholders():
    for missing in ('schema', 'table', 'scope_col', 'scope_id'):
        kwargs = {
            'schema': 's', 'table': 'fact_rotos',
            'scope_col': 'online_league_id', 'scope_id': 1,
        }
        del kwargs[missing]
        with pytest.raises(KeyError):
            LOAD_ROTO.format(**kwargs)


def test_load_roto_has_exactly_expected_fields():
    assert fields(LOAD_ROTO) == {'schema', 'table', 'scope_col', 'scope_id'}


def test_load_roto_does_not_filter_on_is_dynasty():
    # fact_rotos has no is_dynasty column; the template must not reference it.
    assert 'is_dynasty' not in LOAD_ROTO


# ---------------------------------------------------------------------------
# LOAD_QUERIES
# ---------------------------------------------------------------------------

def test_load_queries_are_keyed_by_the_value_column():
    # EloSQL._load_scoped picks its template by spec['value'], so every fact
    # spec must have a query keyed under it.
    assert LOAD_QUERIES == {'elo': LOAD_ELO, 'score': LOAD_ROTO}
    for spec in FACT_SPECS.values():
        assert spec['value'] in LOAD_QUERIES


def test_load_queries_alias_their_value_column_to_rating():
    for value, template in LOAD_QUERIES.items():
        assert '{} AS rating'.format(value) in norm(template)
