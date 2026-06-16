"""Round-trip tests for elo_system.tools.helpers.helper_funcs.score_pivot /
score_unpivot.

score_pivot turns a wide ratings table (member index, ``week_{n}`` columns)
into long form (``member``, ``week``, ``rating``); score_unpivot is its
inverse. These tests assert the two compose back to the identity on both the
wide->long->wide and long->wide->long paths.
"""
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from elo_system.tools.helpers.helper_funcs import score_pivot, score_unpivot


@pytest.fixture
def wide():
    """A wide ratings frame in canonical form: members sorted, weeks ascending,
    no index name -- exactly what score_unpivot produces."""
    return pd.DataFrame(
        {
            'week_0': [1500.0, 1500.0, 1500.0],
            'week_1': [1513.5, 1496.5, 1500.0],
            'week_2': [1505.25, 1488.0, 1521.75],
        },
        index=['abrieff', 'fuzzard', 'nate'],
    )


@pytest.fixture
def long():
    """A long ratings frame in canonical form: exactly what score_pivot
    produces (sorted by member then week, RangeIndex, float ratings)."""
    return pd.DataFrame(
        {
            'member': ['abrieff', 'abrieff', 'fuzzard', 'fuzzard', 'nate', 'nate'],
            'week': [0, 1, 0, 1, 0, 1],
            'rating': [1500.0, 1513.5, 1500.0, 1496.5, 1500.0, 1500.0],
        }
    )


def test_wide_round_trip(wide):
    assert_frame_equal(score_unpivot(score_pivot(wide)), wide)


def test_long_round_trip(long):
    assert_frame_equal(score_pivot(score_unpivot(long)), long)


def test_pivot_shape_and_columns(wide):
    long = score_pivot(wide)
    assert list(long.columns) == ['member', 'week', 'rating']
    # 3 members x 3 weeks, no empty cells.
    assert len(long) == 9
    assert long['week'].dtype.kind == 'i'


def test_round_trip_preserves_missing_cells():
    """A member who joined late has NaN early weeks. score_pivot drops those
    cells; score_unpivot must bring them back as NaN."""
    wide = pd.DataFrame(
        {
            'week_0': [1500.0, np.nan],
            'week_1': [1510.0, 1500.0],
            'week_2': [1490.0, 1505.0],
        },
        index=['veteran', 'rookie'],
    ).sort_index()

    long = score_pivot(wide)
    # The NaN cell is dropped, not carried as a row.
    assert len(long) == 5
    assert_frame_equal(score_unpivot(long), wide)


def test_unpivot_orders_weeks_numerically():
    """Weeks must come back as week_0..week_10 in numeric order, not the
    lexicographic order that would put week_10 before week_2."""
    long = pd.DataFrame(
        {
            'member': ['a'] * 3,
            'week': [10, 2, 0],
            'rating': [1490.0, 1505.0, 1500.0],
        }
    )
    wide = score_unpivot(long)
    assert list(wide.columns) == ['week_0', 'week_2', 'week_10']
    assert wide.loc['a', 'week_10'] == 1490.0
