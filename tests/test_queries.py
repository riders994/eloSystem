"""Tests for elo_system.tools.basics.queries.

Guards the LOAD_ELO / LOAD_ROTO SQL templates against missing or renamed
``{}`` placeholders and against accidental edits to their table names,
WHERE clauses and the ``rating`` alias.
"""
import pytest

from elo_system.tools.basics.queries import LOAD_ELO, LOAD_ROTO


def norm(sql):
    return ' '.join(sql.split())


# ---------------------------------------------------------------------------
# LOAD_ELO
# ---------------------------------------------------------------------------

def test_load_elo_formats_with_expected_kwargs():
    sql = LOAD_ELO.format(
        schema='fantasy_sports',
        is_dynasty='TRUE',
        league_id=42,
        year_end='AND league_year = 2024',
    )
    flat = norm(sql)
    assert 'FROM fantasy_sports.fact_elos' in flat
    assert 'is_dynasty = TRUE' in flat
    assert 'league_id = 42' in flat
    assert 'AND league_year = 2024' in flat
    # the rating alias is part of the contract for downstream score_unpivot
    assert 'elo AS rating' in flat
    assert 'team_id' in flat
    assert 'week' in flat


def test_load_elo_year_end_optional_empty():
    sql = LOAD_ELO.format(
        schema='s', is_dynasty='FALSE', league_id=1, year_end=''
    )
    flat = norm(sql)
    # An empty year_end must leave a well-formed WHERE clause.
    assert flat.endswith('league_id = 1')


def test_load_elo_requires_all_placeholders():
    # Missing any of the four named fields must raise (guards renames).
    for missing in ('schema', 'is_dynasty', 'league_id', 'year_end'):
        kwargs = {
            'schema': 's', 'is_dynasty': 'TRUE',
            'league_id': 1, 'year_end': '',
        }
        del kwargs[missing]
        with pytest.raises(KeyError):
            LOAD_ELO.format(**kwargs)


def test_load_elo_has_exactly_expected_fields():
    import string
    fields = {
        name for _, name, _, _ in string.Formatter().parse(LOAD_ELO)
        if name
    }
    assert fields == {'schema', 'is_dynasty', 'league_id', 'year_end'}


# ---------------------------------------------------------------------------
# LOAD_ROTO
# ---------------------------------------------------------------------------

def test_load_roto_formats_with_expected_kwargs():
    sql = LOAD_ROTO.format(
        schema='fantasy_sports',
        league_id=7,
        year_end='AND league_year = 2023',
    )
    flat = norm(sql)
    assert 'FROM fantasy_sports.fact_rotos' in flat
    assert 'league_id = 7' in flat
    assert 'AND league_year = 2023' in flat
    assert 'score AS rating' in flat
    assert 'team_id' in flat
    assert 'week' in flat


def test_load_roto_requires_all_placeholders():
    for missing in ('schema', 'league_id', 'year_end'):
        kwargs = {'schema': 's', 'league_id': 1, 'year_end': ''}
        del kwargs[missing]
        with pytest.raises(KeyError):
            LOAD_ROTO.format(**kwargs)


def test_load_roto_has_exactly_expected_fields():
    import string
    fields = {
        name for _, name, _, _ in string.Formatter().parse(LOAD_ROTO)
        if name
    }
    assert fields == {'schema', 'league_id', 'year_end'}


def test_load_roto_does_not_filter_on_is_dynasty():
    # fact_rotos has no is_dynasty column; the template must not reference it.
    assert 'is_dynasty' not in LOAD_ROTO
