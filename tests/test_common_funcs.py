"""Tests for elo_system.tools.basics.common_funcs."""
import math

import pandas as pd
import pytest

from elo_system.tools.basics.common_funcs import (
    elo_share,
    elo_expected,
    score_elo_calc,
    bin_elo_calc,
    trin_elo_calc,
    median_elo_calc,
    week_formatter,
)


# ---------------------------------------------------------------------------
# elo_share
# ---------------------------------------------------------------------------

def test_elo_share_known_values():
    assert elo_share(0) == pytest.approx(1.0)
    assert elo_share(400) == pytest.approx(10.0)
    assert elo_share(800) == pytest.approx(100.0)
    assert elo_share(-400) == pytest.approx(0.1)


def test_elo_share_is_exponential_in_rating():
    # share(a + 400) == 10 * share(a) for any rating
    for elo in (1200.0, 1500.0, 1777.5):
        assert elo_share(elo + 400) == pytest.approx(10 * elo_share(elo))


# ---------------------------------------------------------------------------
# elo_expected
# ---------------------------------------------------------------------------

def test_elo_expected_equal_ratings_is_half_each():
    s = elo_share(1500)
    expected = elo_expected(s, s)
    assert expected[0] == pytest.approx(0.5)
    assert expected[1] == pytest.approx(0.5)


def test_elo_expected_sums_to_one():
    pairs = [(1500, 1500), (1700, 1500), (1234, 1876), (1500, 900)]
    for r1, r2 in pairs:
        expected = elo_expected(elo_share(r1), elo_share(r2))
        assert expected.sum() == pytest.approx(1.0)


def test_elo_expected_200_point_gap_hand_computed():
    # 1700 vs 1500: E = 1 / (1 + 10^(-200/400)) ~= 0.7597469266479578
    expected = elo_expected(elo_share(1700), elo_share(1500))
    assert expected[0] == pytest.approx(1 / (1 + 10 ** (-0.5)))
    assert expected[0] == pytest.approx(0.7597469266479578)
    assert expected[1] == pytest.approx(0.2402530733520422)


def test_elo_expected_favors_higher_rating():
    expected = elo_expected(elo_share(1600), elo_share(1400))
    assert expected[0] > 0.5 > expected[1]


# ---------------------------------------------------------------------------
# score_elo_calc (continuous score shares)
# ---------------------------------------------------------------------------

def test_score_elo_equal_ratings_full_win():
    new = score_elo_calc([1500, 1.0], [1500, 0.0], k=60)
    assert new[0] == pytest.approx(1530.0)
    assert new[1] == pytest.approx(1470.0)


def test_score_elo_equal_ratings_score_share():
    # share 0.6 vs 0.4 with expected 0.5 each -> +/- k * 0.1
    new = score_elo_calc([1500, 0.6], [1500, 0.4], k=60)
    assert new[0] == pytest.approx(1506.0)
    assert new[1] == pytest.approx(1494.0)


def test_score_elo_hand_computed_200_point_gap():
    # favorite wins: gains k * (1 - 0.7597469266) = 14.4151844...
    new = score_elo_calc([1700, 1.0], [1500, 0.0], k=60)
    assert new[0] == pytest.approx(1714.4151844011226)
    assert new[1] == pytest.approx(1485.5848155988774)


def test_score_elo_zero_sum_when_scores_sum_to_one():
    cases = [
        ([1500, 0.55], [1500, 0.45]),
        ([1700, 0.3], [1500, 0.7]),
        ([1234, 1.0], [1876, 0.0]),
    ]
    for p1, p2 in cases:
        new = score_elo_calc(p1, p2, k=60)
        assert new[0] + new[1] == pytest.approx(p1[0] + p2[0])


def test_score_elo_k_scaling():
    base = score_elo_calc([1500, 1.0], [1500, 0.0], k=60)
    double = score_elo_calc([1500, 1.0], [1500, 0.0], k=120)
    assert double[0] - 1500 == pytest.approx(2 * (base[0] - 1500))
    assert double[1] - 1500 == pytest.approx(2 * (base[1] - 1500))


def test_score_elo_proba_returns_ratings_and_expectations():
    (new1, new2), (e1, e2) = score_elo_calc([1700, 1.0], [1500, 0.0], k=60, proba=True)
    assert new1 == pytest.approx(1714.4151844011226)
    assert new2 == pytest.approx(1485.5848155988774)
    assert e1 == pytest.approx(0.7597469266479578)
    assert e2 == pytest.approx(0.2402530733520422)
    assert e1 + e2 == pytest.approx(1.0)


def test_score_elo_draw_at_equal_ratings_no_change():
    new = score_elo_calc([1500, 0.5], [1500, 0.5], k=60)
    assert new[0] == pytest.approx(1500.0)
    assert new[1] == pytest.approx(1500.0)


# ---------------------------------------------------------------------------
# bin_elo_calc (binary win/loss; draws are explicitly demoted to losses)
# ---------------------------------------------------------------------------

def test_bin_elo_rounds_score_shares_to_win_loss():
    # 0.6 / 0.4 rounds to 1 / 0 -> full win/loss update
    new = bin_elo_calc([1500, 0.6], [1500, 0.4], k=60)
    assert new[0] == pytest.approx(1530.0)
    assert new[1] == pytest.approx(1470.0)


def test_bin_elo_zero_sum_for_win_loss():
    new = bin_elo_calc([1700, 1], [1500, 0], k=60)
    assert new[0] + new[1] == pytest.approx(3200.0)
    assert new[0] == pytest.approx(1714.4151844011226)
    assert new[1] == pytest.approx(1485.5848155988774)


def test_bin_elo_draw_treated_as_double_loss():
    # Actual (and explicit) behavior: a 0.5 score is set to 0 for BOTH
    # players before rounding (common_funcs.py:40-43), so a draw costs each
    # equally-rated player k * 0.5. Defensible for a "binary" scorer where a
    # tie is "not a win"; documented here as actual behavior.
    new = bin_elo_calc([1500, 0.5], [1500, 0.5], k=60)
    assert new[0] == pytest.approx(1470.0)
    assert new[1] == pytest.approx(1470.0)


def test_bin_elo_k_scaling():
    base = bin_elo_calc([1500, 1], [1500, 0], k=60)
    triple = bin_elo_calc([1500, 1], [1500, 0], k=180)
    assert triple[0] - 1500 == pytest.approx(3 * (base[0] - 1500))


def test_bin_elo_proba_returns_expectations():
    (_, _), (e1, e2) = bin_elo_calc([1700, 1], [1500, 0], k=60, proba=True)
    assert e1 == pytest.approx(0.7597469266479578)
    assert e1 + e2 == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# trin_elo_calc (trinary: win/draw/loss; draws should keep their 0.5 score)
# ---------------------------------------------------------------------------

def test_trin_elo_win_loss_matches_binary():
    new = trin_elo_calc([1500, 0.7], [1500, 0.3], k=60)
    assert new[0] == pytest.approx(1530.0)
    assert new[1] == pytest.approx(1470.0)


def test_trin_elo_zero_sum_for_win_loss():
    new = trin_elo_calc([1700, 1], [1500, 0], k=60)
    assert new[0] + new[1] == pytest.approx(3200.0)


def test_trin_elo_draw_preserved_equal_ratings():
    # Intended: a 0.5/0.5 draw between equally rated players changes nothing.
    new = trin_elo_calc([1500, 0.5], [1500, 0.5], k=60)
    assert new[0] == pytest.approx(1500.0)
    assert new[1] == pytest.approx(1500.0)


def test_trin_elo_draw_zero_sum_unequal_ratings():
    # Intended: with scores 0.5 + 0.5 = 1 the update is zero-sum, and the
    # favorite loses ground on a draw: 1700 + 60*(0.5 - 0.759747) = 1684.415...
    new = trin_elo_calc([1700, 0.5], [1500, 0.5], k=60)
    assert new[0] + new[1] == pytest.approx(3200.0)
    assert new[0] == pytest.approx(1684.4151844011226)
    assert new[1] == pytest.approx(1515.5848155988774)


# ---------------------------------------------------------------------------
# median_elo_calc
# ---------------------------------------------------------------------------

@pytest.fixture
def ten_team_elos():
    ids = [f"team_{i}" for i in range(10)]
    return pd.Series([1500.0] * 10, index=ids)


@pytest.fixture
def ten_team_scores(ten_team_elos):
    # Distinct scores, descending: team_0 best, team_9 worst.
    return pd.Series(
        [150.0, 140.0, 130.0, 120.0, 110.0, 100.0, 90.0, 80.0, 70.0, 60.0],
        index=ten_team_elos.index,
    )


def test_median_elo_above_median_gain_below_lose(ten_team_elos, ten_team_scores):
    new = median_elo_calc(ten_team_scores, ten_team_elos, k=60)
    delta = new - ten_team_elos
    median_score = ten_team_scores.median()
    for team in ten_team_scores.index:
        if ten_team_scores[team] > median_score:
            assert delta[team] > 0, team
        else:
            assert delta[team] < 0, team


def test_median_elo_better_score_never_worse_delta(ten_team_elos, ten_team_scores):
    new = median_elo_calc(ten_team_scores, ten_team_elos, k=60)
    deltas = (new - ten_team_elos).values
    # scores are sorted descending, so deltas must be non-increasing
    assert all(d1 >= d2 - 1e-12 for d1, d2 in zip(deltas, deltas[1:]))


def test_median_elo_exact_median_team_unchanged():
    # Odd team count -> the middle team sits exactly at the median and its
    # update term is k * 0 * log(1) -> exactly zero.
    ids = list("abcde")
    scores = pd.Series([100.0, 90.0, 80.0, 70.0, 60.0], index=ids)
    elos = pd.Series([1500.0] * 5, index=ids)
    new = median_elo_calc(scores, elos, k=60)
    assert new["c"] == pytest.approx(1500.0)


def test_median_elo_hand_computed_top_team():
    # 5 teams, equal elos. Normed scores are [1, .75, .5, .25, 0], median .5.
    # Top team: delta = k*(1-.5)*ln(1+(1-.5))*2.2 / (2.2 + 0) = 30*ln(1.5)
    ids = list("abcde")
    scores = pd.Series([100.0, 90.0, 80.0, 70.0, 60.0], index=ids)
    elos = pd.Series([1500.0] * 5, index=ids)
    new = median_elo_calc(scores, elos, k=60)
    assert new["a"] - 1500 == pytest.approx(30 * math.log(1.5))
    assert new["a"] == pytest.approx(1512.163953243245)
    # symmetric scores + equal elos -> symmetric deltas (zero-sum here)
    assert new["e"] - 1500 == pytest.approx(-(new["a"] - 1500))
    assert new.sum() == pytest.approx(elos.sum())


def test_median_elo_k_scaling(ten_team_elos, ten_team_scores):
    base = median_elo_calc(ten_team_scores, ten_team_elos, k=60) - ten_team_elos
    double = median_elo_calc(ten_team_scores, ten_team_elos, k=120) - ten_team_elos
    for team in ten_team_scores.index:
        assert double[team] == pytest.approx(2 * base[team])


def test_median_elo_dampens_gains_for_high_rated_winners():
    ids = list("abcde")
    scores = pd.Series([100.0, 90.0, 80.0, 70.0, 60.0], index=ids)
    elos_even = pd.Series([1500.0] * 5, index=ids)
    elos_high = pd.Series([1800.0, 1500.0, 1500.0, 1500.0, 1500.0], index=ids)
    gain_at_1500 = median_elo_calc(scores, elos_even, k=60)["a"] - 1500.0
    gain_at_1800 = median_elo_calc(scores, elos_high, k=60)["a"] - 1800.0
    assert 0 < gain_at_1800 < gain_at_1500


def test_median_elo_dampens_losses_for_low_rated_losers():
    ids = list("abcde")
    scores = pd.Series([100.0, 90.0, 80.0, 70.0, 60.0], index=ids)
    elos_even = pd.Series([1500.0] * 5, index=ids)
    elos_low = pd.Series([1500.0, 1500.0, 1500.0, 1500.0, 1200.0], index=ids)
    loss_at_1500 = median_elo_calc(scores, elos_even, k=60)["e"] - 1500.0
    loss_at_1200 = median_elo_calc(scores, elos_low, k=60)["e"] - 1200.0
    assert loss_at_1500 < loss_at_1200 < 0


def test_median_elo_preserves_index(ten_team_elos, ten_team_scores):
    new = median_elo_calc(ten_team_scores, ten_team_elos, k=60)
    assert isinstance(new, pd.Series)
    assert list(new.index) == list(ten_team_elos.index)


# ---------------------------------------------------------------------------
# week_formatter (small helper exercised for completeness)
# ---------------------------------------------------------------------------

def test_week_formatter_single_week():
    assert week_formatter("5") == 5


def test_week_formatter_range_is_inclusive():
    assert week_formatter("2:5") == range(2, 6)
