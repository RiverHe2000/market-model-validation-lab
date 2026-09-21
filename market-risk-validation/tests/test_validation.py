from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import norm, t

from market_risk import validation
from market_risk.validation import (
    circular_block_means,
    es_backtest,
    fz0_scores,
    holm_adjust,
    pinball_scores,
    var_backtest,
)


def test_validator_does_not_import_forecasting_engine():
    tree = ast.parse(Path(validation.__file__).read_text(encoding="utf-8"))
    modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any("models" in module or "runner" in module for module in modules)


def test_clustered_exceptions_have_correct_count_but_fail_independence():
    loss = np.zeros(1000)
    loss[500:525] = 5.0
    result = var_backtest(loss, np.ones(1000), 0.975, simulations=199, seed=12)
    assert result["coverage_exact_p"] > 0.9
    assert result["independence_permutation_p"] <= 0.01


def test_no_hits_means_insufficient_independence_not_perfect_model():
    result = var_backtest(np.zeros(5000), np.ones(5000), 0.99, simulations=99)
    assert result["coverage_exact_p"] < 0.001
    assert result["independence_status"] == "insufficient"
    assert result["independence_permutation_p"] is None
    assert result["kupiec_lr"] > 0


def test_es_insufficient_tail_is_explicit():
    result = es_backtest(np.zeros(250), np.ones(250), np.full(250, 2.0), samples=99)
    assert result["status"] == "insufficient"
    assert result["underestimation_p"] is None


def test_es_only_underforecast_is_detected_with_unchanged_var():
    df, alpha = 5, 0.975
    loss = np.random.default_rng(95).standard_t(df, 30_000)
    quantile = t.ppf(alpha, df)
    expected_shortfall = (df + quantile**2) / (df - 1) * t.pdf(quantile, df) / (1 - alpha)
    var = np.full(len(loss), quantile)
    es = np.full(len(loss), 0.8 * expected_shortfall)
    assert es[0] > var[0]
    result = es_backtest(loss, var, es, samples=299, seed=41)
    assert result["moment"] > 0.15
    assert result["underestimation_p"] < 0.05


def test_five_times_risk_buffer_is_penalized_by_proper_scores():
    loss = np.random.default_rng(17).normal(size=100_000)
    v = np.full(len(loss), norm.ppf(0.975))
    e = np.full(len(loss), norm.pdf(v[0]) / 0.025)
    assert fz0_scores(loss, 5 * v, 5 * e).mean() > fz0_scores(loss, v, e).mean() + 0.5
    assert pinball_scores(loss, 5 * v, 0.975).mean() > pinball_scores(loss, v, 0.975).mean()


def test_fz0_true_forecast_wins_controlled_population_grid():
    loss = np.random.default_rng(22).normal(size=100_000)
    v = np.full(len(loss), norm.ppf(0.975))
    e = np.full(len(loss), norm.pdf(v[0]) / 0.025)
    correct = fz0_scores(loss, v, e).mean()
    for scale in (0.7, 1.5, 5.0):
        assert fz0_scores(loss, scale * v, scale * e).mean() > correct


def test_circular_bootstrap_is_reproducible_and_preserves_constants():
    np.testing.assert_array_equal(circular_block_means(np.ones(113), 99, 20, 5), np.ones(99))
    values = np.arange(113, dtype=float)
    np.testing.assert_array_equal(
        circular_block_means(values, 100, 20, 5), circular_block_means(values, 100, 20, 5)
    )
    assert abs(circular_block_means(values, 5000, 20, 5).mean() - values.mean()) < 1


def test_holm_preserves_step_down_monotonicity():
    assert holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03}) == pytest.approx(
        {"a": 0.03, "b": 0.06, "c": 0.06}
    )
