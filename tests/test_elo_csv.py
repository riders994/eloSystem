"""Tests for EloCSV publishing/loading round-trips.

EloCSV.load_frames is the inverse of EloData.publish: it reads the CSVs back
into the exact payload shape FrameManager.load_frames consumes
({'dynasty_elo': df, 'seasonal_elo': {year: df}, 'roto_history': {year: df}}).
"""
import pandas as pd
import pytest

from elo_system.elo_system import EloCSV
from elo_system.tools.helpers.frame_manager import FrameManager


def make_csv(tmp_path, **cfg):
    config = {'write_loc': 'ratings'}
    config.update(cfg)
    return EloCSV(config, tmp_path)


def _frame(members, weeks):
    return pd.DataFrame(
        {f'week_{w}': [1500.0 + w] * len(members) for w in range(weeks)},
        index=members,
    )


def test_publish_then_load_roundtrip(tmp_path):
    csv = make_csv(tmp_path)
    seasonal = {2024: _frame(['a', 'b'], 3), 2025: _frame(['a', 'c'], 2)}
    dynasty = _frame(['a', 'b', 'c'], 4)
    csv.publish({'seasonal_elo': seasonal, 'dynasty_elo': dynasty})

    loaded = csv.load_frames()
    assert set(loaded) == {'seasonal_elo', 'dynasty_elo'}
    assert set(loaded['seasonal_elo']) == {2024, 2025}
    pd.testing.assert_frame_equal(
        loaded['seasonal_elo'][2024], seasonal[2024], check_names=False)
    pd.testing.assert_frame_equal(
        loaded['seasonal_elo'][2025], seasonal[2025], check_names=False)
    pd.testing.assert_frame_equal(
        loaded['dynasty_elo'], dynasty, check_names=False)


def test_load_specific_frame_set(tmp_path):
    csv = make_csv(tmp_path)
    csv.publish({'seasonal_elo': {2024: _frame(['a', 'b'], 2)},
                 'dynasty_elo': _frame(['a', 'b'], 2)})
    only = csv.load_frames('seasonal_elo')
    assert set(only) == {'seasonal_elo'}
    assert set(only['seasonal_elo']) == {2024}


def test_load_roto_history(tmp_path):
    csv = make_csv(tmp_path)
    csv.publish({'roto_history': {2024: _frame(['a', 'b'], 2),
                                  2025: _frame(['a', 'b'], 2)}})
    loaded = csv.load_frames('roto_history')
    assert set(loaded['roto_history']) == {2024, 2025}


def test_load_missing_returns_empty(tmp_path):
    csv = make_csv(tmp_path)  # nothing published
    assert csv.load_frames() == {}
    assert csv.load_frames('dynasty_elo') == {}


def test_load_unknown_frame_set_raises(tmp_path):
    csv = make_csv(tmp_path)
    with pytest.raises(KeyError, match='Unknown frame set'):
        csv.load_frames('not_a_set')


def test_read_loc_distinct_from_write_loc(tmp_path):
    # Publish to write_loc, read from a separate read_loc that mirrors it.
    csv = make_csv(tmp_path, write_loc='out', read_loc='out')
    csv.publish({'seasonal_elo': {2024: _frame(['a', 'b'], 2)}})
    assert csv.in_dir == tmp_path / 'out'
    loaded = csv.load_frames('seasonal_elo')
    assert set(loaded['seasonal_elo']) == {2024}


def test_seasons_by_order_roundtrips_to_ordinal_keys(tmp_path):
    csv = make_csv(tmp_path, seasons_by='order')
    # Years 2024/2025 are written as ordinals 0/1; load recovers the ordinals.
    csv.publish({'seasonal_elo': {2024: _frame(['a', 'b'], 2),
                                  2025: _frame(['a', 'b'], 2)}})
    loaded = csv.load_frames('seasonal_elo')
    assert set(loaded['seasonal_elo']) == {0, 1}


def test_loaded_frames_consumable_by_frame_manager(tmp_path):
    csv = make_csv(tmp_path)
    seasonal = {2024: _frame(['a', 'b'], 2)}
    csv.publish({'seasonal_elo': seasonal})
    loaded = csv.load_frames('seasonal_elo')

    fm = FrameManager({
        'is_dynasty': False,
        'is_roto': False,
        'seasons': {2024: {'league_members': {'a': {}, 'b': {}},
                           'current_season_length': 1}},
    })
    fm.load_frames(loaded)
    assert 2024 in fm.seasonal_elo
    pd.testing.assert_frame_equal(
        fm.seasonal_elo[2024], seasonal[2024], check_names=False)
