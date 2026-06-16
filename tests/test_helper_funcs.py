"""Tests for elo_system.tools.helpers.helper_funcs:

  * uri_to_dict / dict_to_uri round-trip
  * validate_conn_dict (valid case + every invalid case)
"""
import pytest

from elo_system.tools.helpers.helper_funcs import (
    uri_to_dict,
    dict_to_uri,
    validate_conn_dict,
)


# ---------------------------------------------------------------------------
# uri_to_dict
# ---------------------------------------------------------------------------

def test_uri_to_dict_parses_all_fields():
    d = uri_to_dict('postgresql://alice:secret@db.example.com:5433/mydb')
    assert d == {
        'dbname': 'mydb',
        'user': 'alice',
        'password': 'secret',
        'port': 5433,
        'host': 'db.example.com',
    }


def test_uri_to_dict_port_is_int():
    d = uri_to_dict('postgresql://u:p@h:5432/db')
    assert isinstance(d['port'], int)


# ---------------------------------------------------------------------------
# dict_to_uri
# ---------------------------------------------------------------------------

def test_dict_to_uri_builds_expected_string():
    uri = dict_to_uri({
        'dbname': 'mydb',
        'user': 'alice',
        'password': 'secret',
        'port': 5433,
        'host': 'db.example.com',
    })
    assert uri == 'postgresql://alice:secret@db.example.com:5433/mydb'


def test_dict_to_uri_custom_dialect():
    uri = dict_to_uri(
        {
            'dbname': 'd', 'user': 'u', 'password': 'p',
            'port': 1, 'host': 'h',
        },
        dialect='postgresql+psycopg2',
    )
    assert uri.startswith('postgresql+psycopg2://')


def test_dict_to_uri_defaults_for_missing_keys():
    uri = dict_to_uri({})
    # host defaults to localhost, port to 5432
    assert uri == 'postgresql://:@localhost:5432/'


# ---------------------------------------------------------------------------
# round-trip
# ---------------------------------------------------------------------------

def test_uri_dict_round_trip():
    original = 'postgresql://alice:secret@db.example.com:5433/mydb'
    assert dict_to_uri(uri_to_dict(original)) == original


def test_dict_uri_round_trip():
    d = {
        'dbname': 'mydb',
        'user': 'alice',
        'password': 'secret',
        'port': 5433,
        'host': 'db.example.com',
    }
    assert uri_to_dict(dict_to_uri(d)) == d


# ---------------------------------------------------------------------------
# validate_conn_dict
# ---------------------------------------------------------------------------

def _valid_dict():
    return {
        'dbname': 'mydb',
        'user': 'alice',
        'password': 'secret',
        'port': 5432,
        'host': 'localhost',
    }


def test_validate_conn_dict_valid():
    assert validate_conn_dict(_valid_dict()) is True


@pytest.mark.parametrize('key', ['dbname', 'user', 'password', 'port', 'host'])
def test_validate_conn_dict_missing_required_field(key):
    d = _valid_dict()
    del d[key]
    assert validate_conn_dict(d) is False


@pytest.mark.parametrize('key', ['dbname', 'user', 'password', 'port', 'host'])
def test_validate_conn_dict_none_required_field(key):
    d = _valid_dict()
    d[key] = None
    assert validate_conn_dict(d) is False


def test_validate_conn_dict_disallowed_flavor():
    d = _valid_dict()
    d['conn_dict'] = 'mysql'  # not in APPROVED_SQL_FLAVORS
    assert validate_conn_dict(d) is False


def test_validate_conn_dict_allowed_flavor():
    d = _valid_dict()
    d['conn_dict'] = 'postgresql'
    assert validate_conn_dict(d) is True
