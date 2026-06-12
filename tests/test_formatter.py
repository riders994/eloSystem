"""Tests for elo_system.tools.formatter (fantrax_formatter and roto_calc)."""
import numpy as np
import pandas as pd
import pytest

from elo_system.tools.basics import ROTO_COLS
from elo_system.tools.formatter import fantrax_formatter, roto_calc

from tests.mocks.fantrax import (
    NBA_CATEGORIES,
    make_category_stats,
    make_matchup,
    make_scoring_period,
    make_team,
)

# ---------------------------------------------------------------------------
# Hand-built 4-team week: 2 matchups, no ties in any category.
# ---------------------------------------------------------------------------

STATS = {
    # owner:  FG%    FT%   3PTM  PTS  REB  AST  ST  BLK  TO   Pts
    'alice':  (0.500, 0.850, 40, 500, 200, 110, 30, 20, 50, 6.0),
    'bob':    (0.480, 0.800, 35, 450, 180, 100, 25, 15, 60, 3.0),
    'carol':  (0.460, 0.900, 30, 400, 220,  90, 35, 25, 40, 5.0),
    'dave':   (0.440, 0.750, 45, 350, 160, 120, 20, 10, 70, 4.0),
}

# Hand-computed roto for the table above (higher = better except TO, which is
# inverted -- lower TO earns more rank points). 9 categories x ranks 1..4.
EXPECTED_ROTO = {'alice': 29, 'bob': 20, 'carol': 26, 'dave': 15}
EXPECTED_ROTO_RANK = {'alice': 1, 'carol': 2, 'bob': 3, 'dave': 4}


def _stats_for(owner):
    fg, ft, tpm, pts, reb, ast, st, blk, to, h2h_pts = STATS[owner]
    return make_category_stats(
        pts=h2h_pts,
        **{'FG%': fg, 'FT%': ft, '3PTM': tpm, 'PTS': pts, 'REB': reb,
           'AST': ast, 'ST': st, 'BLK': blk, 'TO': to},
    )


@pytest.fixture
def teams():
    return {owner: make_team(owner) for owner in STATS}


@pytest.fixture
def scoreboard(teams):
    m1 = make_matchup(teams['alice'], teams['bob'],
                      _stats_for('alice'), _stats_for('bob'), matchup_key='1')
    m2 = make_matchup(teams['carol'], teams['dave'],
                      _stats_for('carol'), _stats_for('dave'), matchup_key='2')
    return make_scoring_period({'1': m1, '2': m2})


# ---------------------------------------------------------------------------
# fantrax_formatter, NBA path
# ---------------------------------------------------------------------------

def test_nba_frame_indexed_by_owner_with_both_sides(scoreboard):
    board = fantrax_formatter('nba', scoreboard)
    assert isinstance(board, pd.DataFrame)
    # Both home and away sides of both matchups appear, keyed by owner string.
    assert set(board.index) == {'alice', 'bob', 'carol', 'dave'}
    assert len(board) == 4


def test_nba_frame_has_category_true_score_and_opponent_columns(scoreboard):
    board = fantrax_formatter('nba', scoreboard)
    for cat in NBA_CATEGORIES:
        assert cat in board.columns
    assert 'true_score' in board.columns
    assert 'opponent' in board.columns
    # 'Pts' is renamed away, not duplicated.
    assert 'Pts' not in board.columns


def test_nba_true_score_is_pts_over_nine(scoreboard):
    board = fantrax_formatter('nba', scoreboard)
    for owner, row in STATS.items():
        assert board.loc[owner, 'true_score'] == pytest.approx(row[-1] / 9)


def test_nba_opponent_column_points_at_other_side(scoreboard, teams):
    board = fantrax_formatter('nba', scoreboard)
    assert board.loc['alice', 'opponent'] == teams['bob'].id
    assert board.loc['bob', 'opponent'] == teams['alice'].id
    assert board.loc['carol', 'opponent'] == teams['dave'].id
    assert board.loc['dave', 'opponent'] == teams['carol'].id


def test_nba_category_values_carried_through(scoreboard):
    board = fantrax_formatter('nba', scoreboard)
    assert board.loc['alice', 'PTS'] == 500
    assert board.loc['dave', 'TO'] == 70
    assert board.loc['carol', 'FT%'] == pytest.approx(0.900)


def test_nba_roto_true_adds_hand_computed_roto_columns(scoreboard):
    board = fantrax_formatter('nba', scoreboard, roto=True)
    assert 'roto' in board.columns
    assert 'roto_rank' in board.columns
    for owner in STATS:
        assert board.loc[owner, 'roto'] == EXPECTED_ROTO[owner]
        assert board.loc[owner, 'roto_rank'] == EXPECTED_ROTO_RANK[owner]


def test_nba_roto_false_adds_no_roto_columns(scoreboard):
    board = fantrax_formatter('nba', scoreboard, roto=False)
    assert 'roto' not in board.columns
    assert 'roto_rank' not in board.columns


@pytest.mark.parametrize('league_type', ['nfl', 'nhl', '', 'NBA'])
def test_unknown_league_type_returns_empty_frame(scoreboard, league_type):
    board = fantrax_formatter(league_type, scoreboard)
    assert isinstance(board, pd.DataFrame)
    assert board.empty


# ---------------------------------------------------------------------------
# roto_calc directly
# ---------------------------------------------------------------------------

@pytest.fixture
def small_cat_frame():
    # 3 teams, all 9 ROTO_COLS, no ties anywhere.
    return pd.DataFrame(
        {
            'FG%': [0.50, 0.40, 0.45],
            'FT%': [0.80, 0.90, 0.70],
            '3PTM': [10, 20, 30],
            'PTS': [300, 200, 100],
            'REB': [50, 60, 70],
            'AST': [30, 20, 10],
            'ST': [5, 10, 15],
            'BLK': [9, 6, 3],
            'TO': [10, 20, 30],
        },
        index=['A', 'B', 'C'],
    )


def test_roto_calc_hand_computed_totals(small_cat_frame):
    # Per-category rank points (1 = worst, 3 = best; TO inverted):
    #   FG%: B1 C2 A3 | FT%: C1 A2 B3 | 3PTM: A1 B2 C3 | PTS: C1 B2 A3
    #   REB: A1 B2 C3 | AST: C1 B2 A3 | ST:  A1 B2 C3 | BLK: C1 B2 A3
    #   TO (lower better): C1 B2 A3
    # Totals: A = 20, B = 18, C = 16
    result = roto_calc(small_cat_frame)
    assert result.loc['A', 'roto'] == 20
    assert result.loc['B', 'roto'] == 18
    assert result.loc['C', 'roto'] == 16


def test_roto_calc_to_inversion(small_cat_frame):
    # A has the *fewest* turnovers, so it must earn the *most* TO rank
    # points -- visible in the totals above only because TO is inverted.
    # Without inversion A would total 18 and C would total 18.
    result = roto_calc(small_cat_frame)
    assert result.loc['A', 'roto'] > result.loc['C', 'roto']


def test_roto_calc_rank_one_is_best(small_cat_frame):
    result = roto_calc(small_cat_frame)
    assert result.loc['A', 'roto_rank'] == 1
    assert result.loc['B', 'roto_rank'] == 2
    assert result.loc['C', 'roto_rank'] == 3


def test_roto_calc_total_points_conserved(small_cat_frame):
    # 9 categories, each handing out ranks 1+2+3 = 6 -> 54 total.
    result = roto_calc(small_cat_frame)
    assert result['roto'].sum() == len(ROTO_COLS) * 6


def test_roto_calc_mutates_and_returns_same_frame(small_cat_frame):
    result = roto_calc(small_cat_frame)
    assert result is small_cat_frame
    assert 'roto' in small_cat_frame.columns


def test_roto_calc_matches_independent_pandas_ranking():
    # Cross-check argsort-based ranking against pandas .rank on a bigger
    # tie-free frame.
    rng = np.random.default_rng(42)
    n = 8
    data = {col: rng.permutation(n) * 7 + 3 for col in ROTO_COLS}
    frame = pd.DataFrame(data, index=[f't{i}' for i in range(n)]).astype(float)

    expected = sum(
        frame[col].rank(ascending=(col != 'TO')) for col in ROTO_COLS
    )
    result = roto_calc(frame.copy())
    assert (result['roto'] == expected.astype(int)).all()
