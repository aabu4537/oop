"""Unit tests for Phase 3 model helpers — no DB or network required."""
import numpy as np
import pandas as pd
import pytest

from src.models.features import brier_score_multiclass, encode_outcome


# ---------------------------------------------------------------------------
# encode_outcome
# ---------------------------------------------------------------------------

def test_home_win_encodes_to_2():
    home = pd.Series([3, 2, 1])
    away = pd.Series([0, 1, 0])
    result = encode_outcome(home, away)
    assert list(result) == [2, 2, 2]


def test_draw_encodes_to_1():
    home = pd.Series([0, 1, 2])
    away = pd.Series([0, 1, 2])
    result = encode_outcome(home, away)
    assert list(result) == [1, 1, 1]


def test_away_win_encodes_to_0():
    home = pd.Series([0, 1, 2])
    away = pd.Series([1, 3, 5])
    result = encode_outcome(home, away)
    assert list(result) == [0, 0, 0]


def test_encode_outcome_mixed():
    home = pd.Series([2, 1, 0])
    away = pd.Series([1, 1, 3])
    result = encode_outcome(home, away)
    assert list(result) == [2, 1, 0]


# ---------------------------------------------------------------------------
# brier_score_multiclass
# ---------------------------------------------------------------------------

def test_perfect_predictions_give_zero_brier():
    y_true = np.array([0, 1, 2])
    y_prob = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    assert brier_score_multiclass(y_true, y_prob) == pytest.approx(0.0)


def test_uniform_predictions_give_expected_brier():
    # Uniform 1/3 prediction for all classes
    y_true = np.array([0, 1, 2])
    y_prob = np.full((3, 3), 1 / 3)
    # Each sample: sum_k (1/3 - o_k)^2
    # True class: (1/3 - 1)^2 = (2/3)^2 = 4/9
    # Other two:  (1/3 - 0)^2 = (1/3)^2 = 1/9  (x2)
    # Per sample: 4/9 + 2*(1/9) = 6/9 = 2/3
    expected = 2 / 3
    assert brier_score_multiclass(y_true, y_prob) == pytest.approx(expected, rel=1e-5)


def test_worst_predictions_increase_brier():
    y_true = np.array([0, 1, 2])
    perfect = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    wrong   = np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    assert brier_score_multiclass(y_true, perfect) < brier_score_multiclass(y_true, wrong)


def test_brier_score_is_symmetric_to_class_labeling():
    # Swapping all labels consistently should not change the score
    y_true1 = np.array([0, 1, 2, 0])
    y_prob1 = np.array([
        [0.7, 0.2, 0.1],
        [0.1, 0.6, 0.3],
        [0.1, 0.2, 0.7],
        [0.5, 0.3, 0.2],
    ])
    # Relabel 0→2, 1→1, 2→0 and reorder probability columns accordingly
    y_true2 = np.array([2, 1, 0, 2])
    y_prob2 = y_prob1[:, ::-1]  # reverse column order
    assert brier_score_multiclass(y_true1, y_prob1) == pytest.approx(
        brier_score_multiclass(y_true2, y_prob2), rel=1e-5
    )


# ---------------------------------------------------------------------------
# build_feature_matrix (pure logic, no DB)
# ---------------------------------------------------------------------------

def test_encode_outcome_preserves_index():
    home = pd.Series([2, 0, 1], index=[10, 20, 30])
    away = pd.Series([1, 1, 1], index=[10, 20, 30])
    result = encode_outcome(home, away)
    assert list(result.index) == [10, 20, 30]
    assert list(result) == [2, 0, 1]
