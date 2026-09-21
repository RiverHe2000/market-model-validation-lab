from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_risk.data import CURRENCIES, DataError, ingest, read_fx, sha256_file
from market_risk.models import empirical_risk, ewma_states, forecast_models


def test_ingest_preserves_quotes_and_provenance(fx_file, tmp_path):
    destination = tmp_path / "canonical.csv"
    result = ingest(fx_file, destination)
    np.testing.assert_allclose(read_fx(fx_file), read_fx(destination), rtol=1e-14)
    assert result["source_sha256"] == sha256_file(fx_file)
    assert result["canonical_sha256"] == sha256_file(destination)
    assert result["quote_convention"] == "foreign_currency_units_per_EUR"


@pytest.mark.parametrize(
    "fault", ["duplicate", "reversed_dates", "missing", "negative", "nonnumeric"]
)
def test_input_faults_are_not_silently_repaired(fx_file, fault):
    data = pd.read_csv(fx_file)
    if fault == "duplicate":
        data.loc[1, "date"] = data.loc[0, "date"]
    elif fault == "reversed_dates":
        data = data.iloc[::-1]
    elif fault == "missing":
        data.loc[0, "CHF"] = np.nan
    elif fault == "negative":
        data.loc[0, "JPY"] = -1
    else:
        data["USD"] = data["USD"].astype(object)
        data.loc[0, "USD"] = "broken"
    data.to_csv(fx_file, index=False)
    with pytest.raises((DataError, ValueError)):
        read_fx(fx_file)


def test_official_long_format_and_reversed_denominator(tmp_path):
    rows = [
        {
            "TIME_PERIOD": day,
            "CURRENCY": currency,
            "OBS_VALUE": 1.1 + i,
            "FREQ": "D",
            "CURRENCY_DENOM": "EUR",
            "EXR_TYPE": "SP00",
        }
        for i, currency in enumerate(CURRENCIES)
        for day in ("2024-01-02", "2024-01-03")
    ]
    file = tmp_path / "long.csv"
    pd.DataFrame(rows).to_csv(file, index=False)
    assert read_fx(file).shape == (2, 5)
    rows[0]["CURRENCY_DENOM"] = "USD"
    pd.DataFrame(rows).to_csv(file, index=False)
    with pytest.raises(DataError, match="reversed"):
        read_fx(file)


def test_empirical_es_probability_mass_not_threshold_averaging():
    values = np.array([0.0, 1.0, 2.0, 3.0])
    var, es = empirical_risk(values, 0.6)
    assert var == 2
    assert es == pytest.approx((3 + 0.6 * 2) / 1.6)
    assert empirical_risk(np.array([1.0, 2.0, 2.0, 2.0]), 0.6) == (2.0, 2.0)
    # Regression: tiny positive tail mass must not round to zero.
    assert empirical_risk(values, 1 - 1e-12) == (3.0, 3.0)


def test_empirical_es_positive_homogeneity_and_order():
    rng = np.random.default_rng(7)
    losses = rng.standard_t(4, size=1000)
    for alpha in (0.975, 0.99):
        v, e = empirical_risk(losses, alpha)
        v2, e2 = empirical_risk(2 * losses, alpha)
        assert e >= v
        assert (v2, e2) == pytest.approx((2 * v, 2 * e))


def test_ewma_forecast_and_residuals_use_their_own_past():
    returns = np.random.default_rng(3).normal(0, 0.01, (120, 5))
    covariance, residuals = ewma_states(returns, initial_window=20)
    changed = returns.copy()
    changed[80:] *= 20
    after, changed_residuals = ewma_states(changed, initial_window=20)
    np.testing.assert_array_equal(covariance[20:81], after[20:81])
    np.testing.assert_array_equal(residuals[20:80], changed_residuals[20:80])
    assert not np.allclose(covariance[81:], after[81:])
    expected_prior = returns[:20].T @ returns[:20] / 20
    np.testing.assert_allclose(covariance[20], expected_prior)
    np.testing.assert_allclose(residuals[20], returns[20] / np.sqrt(np.diag(expected_prior)))


def test_joint_fhs_keeps_offsetting_asset_moves_together():
    single = np.linspace(-0.03, 0.03, 100)
    history = np.column_stack([single, -single])
    covariance = np.array([[0.0004, -0.0004], [-0.0004, 0.0004]])
    result = forecast_models(history, history / 0.02, covariance, np.array([100.0, 100.0]))
    for forecast in result.values():
        assert forecast.var_975 == pytest.approx(0, abs=1e-9)
        assert forecast.es_975 == pytest.approx(0, abs=1e-9)


def test_cash_returns_and_exact_repricing_agree():
    previous_quote = np.array([1.2, 0.8, 130.0, 1.4, 1.5])
    next_quote = previous_quote * np.array([1.1, 0.98, 1.03, 0.85, 1.0])
    units = 1_000_000 * previous_quote
    eur_holding = units / previous_quote
    exact = units @ (1 / next_quote - 1 / previous_quote)
    via_simple_asset_returns = eur_holding @ ((1 / next_quote) / (1 / previous_quote) - 1)
    assert exact == pytest.approx(via_simple_asset_returns, abs=1e-8)
