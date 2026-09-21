import math

import numpy as np
import pytest

from option_validation.pricing import (
    crr_price,
    forward_greeks,
    forward_price,
    implied_volatility,
    spot_greeks,
    spot_price,
)


def test_published_bsm_benchmark_and_put_call_parity():
    call = spot_price("call", 100, 100, 1, 0.2, 0.05)
    put = spot_price("put", 100, 100, 1, 0.2, 0.05)
    assert call == pytest.approx(10.450583572185565, abs=1e-10)
    assert put == pytest.approx(5.573526022256971, abs=1e-10)
    assert call - put == pytest.approx(100 - 100 * math.exp(-0.05), abs=1e-10)


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize("rate,dividend", [(-0.02, 0.0), (0.05, 0.03)])
def test_bounds_strike_monotonicity_convexity_and_forward_equivalence(kind, rate, dividend):
    strikes = np.linspace(50, 150, 31)
    prices = np.array([spot_price(kind, 100, k, 0.7, 0.32, rate, dividend) for k in strikes])
    assert np.all(prices >= 0)
    assert np.all(np.diff(prices) * (1 if kind == "put" else -1) >= -1e-12)
    assert np.all(np.diff(prices, n=2) >= -1e-12)
    for k, price in zip(strikes, prices, strict=True):
        f, d = 100 * math.exp((rate - dividend) * 0.7), math.exp(-rate * 0.7)
        assert price == pytest.approx(forward_price(kind, f, k, 0.7, 0.32, d))
        assert price <= (100 * math.exp(-dividend * 0.7) if kind == "call" else k * d) + 1e-12


@pytest.mark.parametrize("kind", ["call", "put"])
def test_spot_greeks_units_and_finite_difference(kind):
    args = dict(kind=kind, spot=100.0, strike=105.0, time=90 / 365, volatility=0.25, rate=0.03, dividend=0.01)
    greek = spot_greeks(**args)
    def price(**changes):
        return spot_price(**dict(args, **changes))
    h = 0.01
    assert greek["delta"] == pytest.approx((price(spot=100 + h) - price(spot=100 - h)) / (2 * h), abs=1e-7)
    assert greek["gamma"] == pytest.approx((price(spot=100 + h) - 2 * price() + price(spot=100 - h)) / h**2, abs=1e-7)
    eps = 1e-5
    assert greek["vega_1pct"] == pytest.approx((price(volatility=.25 + eps) - price(volatility=.25 - eps)) / (2 * eps) / 100, abs=1e-8)
    assert greek["rho_1pct"] == pytest.approx((price(rate=.03 + eps) - price(rate=.03 - eps)) / (2 * eps) / 100, abs=1e-8)
    assert greek["theta_day"] == pytest.approx(-(price(time=args["time"] + eps) - price(time=args["time"] - eps)) / (2 * eps) / 365, abs=1e-8)


def test_forward_delta_is_not_spot_delta():
    f, d, t, sigma = 102.0, 0.98, 0.5, 0.2
    g = forward_greeks("call", f, 100, t, sigma, d)
    h = 1e-3
    fd = (forward_price("call", f + h, 100, t, sigma, d) - forward_price("call", f - h, 100, t, sigma, d)) / (2 * h)
    assert g["forward_delta"] == pytest.approx(fd, abs=1e-8)


@pytest.mark.parametrize("kind", ["call", "put"])
def test_crr_independence_and_convergence(kind, monkeypatch):
    expected = spot_price(kind, 100, 110, 1, 0.2, 0.03, 0.01)
    monkeypatch.setattr("option_validation.pricing.forward_price", lambda *a, **k: (_ for _ in ()).throw(AssertionError("analytic dependency")))
    prices = [crr_price(kind, 100, 110, 1, 0.2, 0.03, 0.01, n) for n in (128, 512, 2048)]
    assert abs(prices[-1] - expected) < 0.02
    assert abs(prices[-1] - expected) < abs(prices[0] - expected)


def test_crr_probability_and_overflow_are_explicit_failures():
    with pytest.raises(ValueError, match="probability"):
        crr_price("call", 100, 100, 1, 0.001, 1.0, 0.0, 1)
    with pytest.raises(ValueError, match="overflow"):
        crr_price("call", 100, 100, 100, 2.0, 0.0, 0.0, 2048)


@pytest.mark.parametrize("kind", ["call", "put"])
def test_zero_time_zero_vol_limits_and_undefined_greeks(kind):
    sign = 1 if kind == "call" else -1
    assert spot_price(kind, 110, 100, 0, .2) == max(sign * 10, 0)
    expected = math.exp(-.03) * max(sign * (100 * math.exp(.02) - 105), 0)
    assert spot_price(kind, 100, 105, 1, 0, .03, .01) == pytest.approx(expected)
    assert crr_price(kind, 100, 105, 1, 0, .03, .01) == pytest.approx(expected)
    assert spot_greeks(kind, 100, 100, 0, .2)["status"] == "nonregular_boundary"
    assert spot_greeks(kind, 100, 100, 1, 0)["delta"] is None


@pytest.mark.parametrize("kind", ["call", "put"])
def test_iv_inversion_does_not_invent_a_value_for_invalid_quotes(kind):
    price = forward_price(kind, 100, 105, .5, .31, .98)
    result = implied_volatility(kind, price, 100, 105, .5, .98)
    assert result.status == "ok"
    assert result.volatility == pytest.approx(.31, abs=1e-9)
    assert implied_volatility(kind, -1, 100, 105, .5, .98).status == "outside_no_arbitrage_bounds"
    assert implied_volatility(kind, 1000, 100, 105, .5, .98).volatility is None
    assert implied_volatility(kind, price, 100, 105, 0, .98).volatility is None


def test_low_vega_and_extreme_cancellation_are_not_silent():
    price = forward_price("call", 100, 165, .1, .3, 1)
    iv = implied_volatility("call", price, 100, 165, .1, 1)
    assert iv.status == "ill_conditioned_low_vega"
    assert iv.vega_per_unit < 1e-4
    assert forward_price("put", 1e6, 1, 1e-6, .001, 1) >= 0


@pytest.mark.parametrize("args", [("call", 0, 100, 1, .2), ("call", 100, -1, 1, .2), ("put", 100, 100, -1, .2), ("call", 100, 100, 1, float("nan")), ("unknown", 100, 100, 1, .2)])
def test_invalid_inputs(args):
    with pytest.raises(ValueError):
        spot_price(*args)
