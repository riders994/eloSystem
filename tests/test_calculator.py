"""Tests for elo_system.tools.calculator."""
import numpy as np
import pandas as pd
import pytest

from helpers.calculator import (
    offseason_adjustment,
    nba_calculator,
    nfl_calculator,
)


# ---------------------------------------------------------------------------
# offseason_adjustment
# ---------------------------------------------------------------------------

def test_offseason_adjustment_regresses_to_mean():
    ratings = pd.Series({"a": 1700.0, "b": 1300.0, "c": 1500.0})
    adjusted = offseason_adjustment(ratings, factor=0.4)
    # (elo - 1500) * (1 - 0.4) + 1500
    assert adjusted["a"] == pytest.approx(1620.0)
    assert adjusted["b"] == pytest.approx(1380.0)
    assert adjusted["c"] == pytest.approx(1500.0)


def test_offseason_adjustment_1500_is_fixed_point_for_any_factor():
    ratings = pd.Series([1500.0, 1500.0])
    for factor in (0.1, 0.4, 0.9):
        assert offseason_adjustment(ratings, factor=factor).tolist() == \
            pytest.approx([1500.0, 1500.0])


def test_offseason_adjustment_preserves_total_distance_ordering():
    ratings = pd.Series({"a": 1800.0, "b": 1600.0, "c": 1400.0})
    adjusted = offseason_adjustment(ratings, factor=0.5)
    # everyone moves halfway back to 1500, order preserved
    assert adjusted.tolist() == pytest.approx([1650.0, 1550.0, 1450.0])
    assert (adjusted - 1500).abs().lt((ratings - 1500).abs()).all()


@pytest.mark.parametrize("bad_factor", [0, 0.0, 1, 1.0, -0.5, 1.5, 2])
def test_offseason_adjustment_rejects_factor_outside_open_interval(bad_factor):
    ratings = pd.Series([1600.0])
    with pytest.raises(ValueError):
        offseason_adjustment(ratings, factor=bad_factor)


@pytest.mark.parametrize("ok_factor", [1e-9, 0.5, 1 - 1e-9])
def test_offseason_adjustment_accepts_interior_factors(ok_factor):
    ratings = pd.Series([1600.0])
    out = offseason_adjustment(ratings, factor=ok_factor)
    assert 1500.0 <= out.iloc[0] <= 1600.0


# ---------------------------------------------------------------------------
# nba_calculator fixtures
# ---------------------------------------------------------------------------

MEMBERS = ["a", "b", "c", "d", "e"]


@pytest.fixture
def elo_frame():
    return pd.DataFrame({"week_0": [1500.0] * 5}, index=MEMBERS)


@pytest.fixture
def score_frame():
    # Matchups: a vs b (score shares 0.6/0.4), c vs d (1.0/0.0), e on bye
    # (opponent NaN -> not a str -> skipped and carried forward).
    return pd.DataFrame(
        {
            "true_score": [0.6, 0.4, 1.0, 0.0, 0.7],
            "opponent": ["b", "a", "d", "c", np.nan],
        },
        index=MEMBERS,
    )


# ---------------------------------------------------------------------------
# nba_calculator
# ---------------------------------------------------------------------------

def test_nba_default_scoring_hand_computed(elo_frame, score_frame):
    out = nba_calculator(elo_frame, score_frame, week=1)
    assert "week_1" in out.columns
    # equal ratings: delta = k * (score - 0.5)
    assert out.loc["a", "week_1"] == pytest.approx(1506.0)
    assert out.loc["b", "week_1"] == pytest.approx(1494.0)
    assert out.loc["c", "week_1"] == pytest.approx(1530.0)
    assert out.loc["d", "week_1"] == pytest.approx(1470.0)


def test_nba_bye_carries_rating_forward(elo_frame, score_frame):
    elo_frame.loc["e", "week_0"] = 1612.5
    out = nba_calculator(elo_frame, score_frame, week=1)
    assert out.loc["e", "week_1"] == pytest.approx(1612.5)


def test_nba_returns_same_frame_object_mutated(elo_frame, score_frame):
    out = nba_calculator(elo_frame, score_frame, week=1)
    assert out is elo_frame


def test_nba_zero_sum_per_matchup(elo_frame, score_frame):
    elo_frame["week_0"] = [1700.0, 1450.0, 1500.0, 1550.0, 1600.0]
    out = nba_calculator(elo_frame, score_frame, week=1)
    for p1, p2 in (("a", "b"), ("c", "d")):
        before = out.loc[p1, "week_0"] + out.loc[p2, "week_0"]
        after = out.loc[p1, "week_1"] + out.loc[p2, "week_1"]
        assert after == pytest.approx(before)


def test_nba_skips_existing_week_without_overwrite(elo_frame, score_frame):
    sentinel = [1111.0, 2222.0, 3333.0, 4444.0, 5555.0]
    elo_frame["week_1"] = sentinel
    out = nba_calculator(elo_frame, score_frame, week=1)
    assert out is elo_frame
    assert out["week_1"].tolist() == pytest.approx(sentinel)


def test_nba_overwrite_recomputes_existing_week(elo_frame, score_frame):
    elo_frame["week_1"] = [1111.0] * 5
    out = nba_calculator(elo_frame, score_frame, week=1, overwrite=True)
    assert out.loc["a", "week_1"] == pytest.approx(1506.0)
    assert out.loc["d", "week_1"] == pytest.approx(1470.0)


def test_nba_default_week_is_latest_existing_column(elo_frame, score_frame):
    # week=None resolves to elo_frame.shape[1] - 1, i.e. the latest column
    # that already exists; without overwrite the frame is returned untouched.
    # Defensible-but-surprising actual behavior: the default never appends a
    # new week, it only matters with overwrite=True.
    out = nba_calculator(elo_frame, score_frame)
    assert list(out.columns) == ["week_0"]
    assert out["week_0"].tolist() == pytest.approx([1500.0] * 5)


def test_nba_default_week_with_overwrite_recomputes_latest(score_frame):
    frame = pd.DataFrame(
        {"week_0": [1500.0] * 5, "week_1": [0.0] * 5}, index=MEMBERS
    )
    out = nba_calculator(frame, score_frame, overwrite=True)
    assert list(out.columns) == ["week_0", "week_1"]
    assert out.loc["a", "week_1"] == pytest.approx(1506.0)


def test_nba_binary_scoring_rounds_shares(elo_frame, score_frame):
    out = nba_calculator(elo_frame, score_frame, week=1, scoring="binary")
    # 0.6/0.4 rounds to a full win/loss
    assert out.loc["a", "week_1"] == pytest.approx(1530.0)
    assert out.loc["b", "week_1"] == pytest.approx(1470.0)
    assert out.loc["c", "week_1"] == pytest.approx(1530.0)
    assert out.loc["d", "week_1"] == pytest.approx(1470.0)


def test_nba_binary_scoring_unequal_ratings_hand_computed(score_frame):
    frame = pd.DataFrame({"week_0": [1700.0, 1500.0, 1500.0, 1500.0, 1500.0]},
                         index=MEMBERS)
    out = nba_calculator(frame, score_frame, week=1, scoring="binary")
    # favorite wins: 1700 + 60 * (1 - 0.7597469266) = 1714.4151844...
    assert out.loc["a", "week_1"] == pytest.approx(1714.4151844011226)
    assert out.loc["b", "week_1"] == pytest.approx(1485.5848155988774)


def test_nba_trinary_scoring_win_loss(elo_frame, score_frame):
    out = nba_calculator(elo_frame, score_frame, week=1, scoring="trinary")
    assert out.loc["c", "week_1"] == pytest.approx(1530.0)
    assert out.loc["d", "week_1"] == pytest.approx(1470.0)


def test_nba_k_scaling(elo_frame, score_frame):
    out = nba_calculator(elo_frame.copy(), score_frame, week=1, k=120)
    # equal ratings, share 0.6: delta = 120 * 0.1
    assert out.loc["a", "week_1"] == pytest.approx(1512.0)
    assert out.loc["b", "week_1"] == pytest.approx(1488.0)


@pytest.mark.parametrize("bad", ["median", "score", "binaries", "", "DEFAULT"])
def test_nba_invalid_scoring_raises(elo_frame, score_frame, bad):
    with pytest.raises(ValueError):
        nba_calculator(elo_frame, score_frame, week=1, scoring=bad)


def test_nba_each_matchup_processed_once(elo_frame, score_frame):
    # Both rows of a matchup appear in score_frame; the calced-set guard must
    # apply exactly one update (values would double otherwise).
    out = nba_calculator(elo_frame, score_frame, week=1)
    assert out.loc["a", "week_1"] - 1500.0 == pytest.approx(6.0)


def test_nba_multi_week_progression(elo_frame, score_frame):
    out = nba_calculator(elo_frame, score_frame, week=1)
    rematch = pd.DataFrame(
        {
            "true_score": [0.4, 0.6, 0.5, 0.5, 0.5],
            "opponent": ["b", "a", "d", "c", np.nan],
        },
        index=MEMBERS,
    )
    out = nba_calculator(out, rematch, week=2)
    assert list(out.columns) == ["week_0", "week_1", "week_2"]
    # week_2 builds on week_1: a at 1506 vs b at 1494, a scores 0.4.
    # E_a = 1/(1+10^(-12/400)) = 0.5172565...
    e_a = 1 / (1 + 10 ** (-12 / 400))
    assert out.loc["a", "week_2"] == pytest.approx(1506.0 + 60 * (0.4 - e_a))
    # matchup still zero-sum across both weeks
    assert out.loc["a", "week_2"] + out.loc["b", "week_2"] == pytest.approx(3000.0)


# ---------------------------------------------------------------------------
# nfl_calculator (median-based, whole-league update)
# ---------------------------------------------------------------------------

@pytest.fixture
def nfl_elo_frame():
    return pd.DataFrame({"week_0": [1500.0] * 5}, index=MEMBERS)


@pytest.fixture
def nfl_score_frame():
    return pd.DataFrame({"scores": [100.0, 90.0, 80.0, 70.0, 60.0]},
                        index=MEMBERS)


def test_nfl_median_path_hand_computed(nfl_elo_frame, nfl_score_frame):
    out = nfl_calculator(nfl_elo_frame, nfl_score_frame, week=1)
    assert "week_1" in out.columns
    # top team: 1500 + 60 * 0.5 * ln(1.5) * 2.2 / 2.2 = 1512.16395...
    assert out.loc["a", "week_1"] == pytest.approx(1512.163953243245)
    # exact-median team unchanged
    assert out.loc["c", "week_1"] == pytest.approx(1500.0)
    # symmetric scores at equal elos -> symmetric loss for the bottom team
    assert out.loc["e", "week_1"] == pytest.approx(1487.836046756755)
    # above median gain, below median lose
    assert (out.loc[["a", "b"], "week_1"] > 1500.0).all()
    assert (out.loc[["d", "e"], "week_1"] < 1500.0).all()


def test_nfl_median_keyword_equals_default(nfl_elo_frame, nfl_score_frame):
    default = nfl_calculator(nfl_elo_frame.copy(), nfl_score_frame, week=1)
    median = nfl_calculator(nfl_elo_frame.copy(), nfl_score_frame, week=1,
                            scoring="median")
    assert default["week_1"].tolist() == pytest.approx(median["week_1"].tolist())


@pytest.mark.parametrize("bad", ["binary", "trinary", "score", "", "MEDIAN"])
def test_nfl_invalid_scoring_raises(nfl_elo_frame, nfl_score_frame, bad):
    with pytest.raises(ValueError):
        nfl_calculator(nfl_elo_frame, nfl_score_frame, week=1, scoring=bad)


def test_nfl_skips_existing_week_without_overwrite(nfl_elo_frame,
                                                   nfl_score_frame):
    sentinel = [1.0, 2.0, 3.0, 4.0, 5.0]
    nfl_elo_frame["week_1"] = sentinel
    out = nfl_calculator(nfl_elo_frame, nfl_score_frame, week=1)
    assert out is nfl_elo_frame
    assert out["week_1"].tolist() == pytest.approx(sentinel)


def test_nfl_overwrite_recomputes_existing_week(nfl_elo_frame,
                                                nfl_score_frame):
    nfl_elo_frame["week_1"] = [0.0] * 5
    out = nfl_calculator(nfl_elo_frame, nfl_score_frame, week=1,
                         overwrite=True)
    assert out.loc["a", "week_1"] == pytest.approx(1512.163953243245)


def test_nfl_default_week_from_score_frame_width(nfl_elo_frame,
                                                 nfl_score_frame):
    # week=None resolves to score_frame.shape[1] - 1. With a single 'scores'
    # column that is week 0, which already exists, so the frame is returned
    # untouched. Actual behavior, documented here.
    out = nfl_calculator(nfl_elo_frame, nfl_score_frame)
    assert list(out.columns) == ["week_0"]


def test_nfl_k_passthrough(nfl_elo_frame, nfl_score_frame):
    base = nfl_calculator(nfl_elo_frame.copy(), nfl_score_frame, week=1, k=60)
    double = nfl_calculator(nfl_elo_frame.copy(), nfl_score_frame, week=1,
                            k=120)
    for team in MEMBERS:
        assert double.loc[team, "week_1"] - 1500.0 == pytest.approx(
            2 * (base.loc[team, "week_1"] - 1500.0)
        )


def test_nfl_result_indexed_by_members(nfl_elo_frame, nfl_score_frame):
    out = nfl_calculator(nfl_elo_frame, nfl_score_frame, week=1)
    assert list(out.index) == MEMBERS
    assert out["week_1"].notna().all()
