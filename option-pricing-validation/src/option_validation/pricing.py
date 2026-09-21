"""Analytic BSM/Black, separately constructed European CRR, and bounded IV.

Rates and volatilities are annual decimals. Prices are index points. Spot theta
is calendar decay per ACT/365 day; vega and rho are per one percentage point.
Forward Greeks hold discount factor fixed and are not spot Greeks.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy.optimize import brentq
from scipy.special import ndtr
from scipy.stats import binom


def _check(kind: str, spot: float, strike: float, time: float, volatility: float) -> None:
    if kind not in {"call", "put"}:
        raise ValueError("kind must be call or put")
    if not all(math.isfinite(x) for x in (spot, strike, time, volatility)):
        raise ValueError("All model inputs must be finite")
    if spot <= 0 or strike <= 0 or time < 0 or volatility < 0:
        raise ValueError("Spot/forward and strike must be positive; time and volatility nonnegative")


def _phi(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def forward_price(kind: str, forward: float, strike: float, time: float,
                  volatility: float, discount: float) -> float:
    """Black price with independently specified forward F and discount D."""
    _check(kind, forward, strike, time, volatility)
    if not math.isfinite(discount) or discount <= 0:
        raise ValueError("discount must be positive and finite")
    if time == 0 or volatility == 0:
        return discount * max((forward - strike) * (1 if kind == "call" else -1), 0.0)
    width = volatility * math.sqrt(time)
    d1 = math.log(forward / strike) / width + 0.5 * width
    d2 = d1 - width
    # Evaluate the OTM leg directly, then use parity to avoid ITM cancellation.
    if forward >= strike:
        put = discount * (strike * ndtr(-d2) - forward * ndtr(-d1))
        return float(max(put, 0.0) + (discount * (forward - strike) if kind == "call" else 0.0))
    call = discount * (forward * ndtr(d1) - strike * ndtr(d2))
    return float(max(call, 0.0) + (discount * (strike - forward) if kind == "put" else 0.0))


def spot_price(kind: str, spot: float, strike: float, time: float, volatility: float,
               rate: float = 0.0, dividend: float = 0.0) -> float:
    _check(kind, spot, strike, time, volatility)
    if not all(math.isfinite(x) for x in (rate, dividend)):
        raise ValueError("rate and dividend must be finite")
    return forward_price(kind, spot * math.exp((rate - dividend) * time), strike,
                         time, volatility, math.exp(-rate * time))


def spot_greeks(kind: str, spot: float, strike: float, time: float, volatility: float,
                rate: float = 0.0, dividend: float = 0.0) -> dict:
    _check(kind, spot, strike, time, volatility)
    if not all(math.isfinite(x) for x in (rate, dividend)):
        raise ValueError("rate and dividend must be finite")
    if time == 0 or volatility == 0:
        return dict(status="nonregular_boundary", delta=None, gamma=None, vega_1pct=None,
                    theta_day=None, rho_1pct=None)
    root = math.sqrt(time)
    d1 = (math.log(spot / strike) + (rate - dividend + 0.5 * volatility**2) * time) / (volatility * root)
    d2 = d1 - volatility * root
    dq, dr = math.exp(-dividend * time), math.exp(-rate * time)
    sign = 1 if kind == "call" else -1
    theta = (-spot * dq * _phi(d1) * volatility / (2 * root)
             - sign * rate * strike * dr * ndtr(sign * d2)
             + sign * dividend * spot * dq * ndtr(sign * d1))
    return dict(status="regular", delta=float(sign * dq * ndtr(sign * d1)),
                gamma=dq * _phi(d1) / (spot * volatility * root),
                vega_1pct=spot * dq * _phi(d1) * root / 100,
                theta_day=float(theta / 365),
                rho_1pct=float(sign * strike * time * dr * ndtr(sign * d2) / 100))


def forward_greeks(kind: str, forward: float, strike: float, time: float,
                   volatility: float, discount: float) -> dict:
    _check(kind, forward, strike, time, volatility)
    if not math.isfinite(discount) or discount <= 0:
        raise ValueError("discount must be positive and finite")
    if time == 0 or volatility == 0:
        return dict(status="nonregular_boundary", forward_delta=None, forward_gamma=None, vega_1pct=None)
    width = volatility * math.sqrt(time)
    d1 = math.log(forward / strike) / width + width / 2
    sign = 1 if kind == "call" else -1
    return dict(status="regular", forward_delta=float(sign * discount * ndtr(sign * d1)),
                forward_gamma=discount * _phi(d1) / (forward * width),
                vega_1pct=discount * forward * _phi(d1) * math.sqrt(time) / 100)


def crr_price(kind: str, spot: float, strike: float, time: float, volatility: float,
              rate: float = 0.0, dividend: float = 0.0, steps: int = 1024) -> float:
    """Independent CRR terminal distribution; O(N) for a European payoff.

This sums the binomial terminal payoffs rather than calling Black or recursively
reusing analytic prices. Risk-neutral probabilities outside [0,1] are rejected.
"""
    _check(kind, spot, strike, time, volatility)
    if not isinstance(steps, int) or isinstance(steps, bool) or steps < 1:
        raise ValueError("steps must be a positive integer")
    if not all(math.isfinite(x) for x in (rate, dividend)):
        raise ValueError("rate and dividend must be finite")
    if time == 0:
        return max((spot - strike) * (1 if kind == "call" else -1), 0.0)
    if volatility == 0:
        terminal = spot * math.exp((rate - dividend) * time)
        return math.exp(-rate * time) * max((terminal - strike) * (1 if kind == "call" else -1), 0.0)
    dt = time / steps
    jump = volatility * math.sqrt(dt)
    up, down = math.exp(jump), math.exp(-jump)
    probability = (math.exp((rate - dividend) * dt) - down) / (up - down)
    if not 0 <= probability <= 1:
        raise ValueError("CRR probability outside [0,1]; increase steps or examine carry/volatility")
    count = np.arange(steps + 1)
    exponents = math.log(spot) + (2 * count - steps) * jump
    if np.max(exponents) > math.log(np.finfo(float).max):
        raise ValueError("CRR terminal grid overflows float64; requested parameter domain unsupported")
    terminal = np.exp(exponents)
    payoff = np.maximum((terminal - strike) * (1 if kind == "call" else -1), 0.0)
    value = float(math.exp(-rate * time) * np.dot(binom.pmf(count, steps, probability), payoff))
    if not math.isfinite(value):
        raise ValueError("CRR numerical result is not finite")
    return value


@dataclass(frozen=True)
class IVResult:
    status: str
    volatility: float | None
    residual: float | None = None
    vega_per_unit: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def implied_volatility(kind: str, price: float, forward: float, strike: float,
                       time: float, discount: float) -> IVResult:
    """Bracketed inversion with explicit failure states; no sentinel volatilities."""
    _check(kind, forward, strike, time, 0.0)
    if not math.isfinite(discount) or discount <= 0 or not math.isfinite(price):
        raise ValueError("discount and price must be finite; discount positive")
    if time == 0:
        return IVResult("expired_no_identifiable_iv", None)
    lower = discount * max((forward - strike) * (1 if kind == "call" else -1), 0.0)
    upper = discount * (forward if kind == "call" else strike)
    tolerance = 1e-12 * max(1.0, upper)
    if price < lower - tolerance or price > upper + tolerance:
        return IVResult("outside_no_arbitrage_bounds", None)
    if price <= lower + tolerance:
        return IVResult("at_lower_bound_not_identifiable", None)
    if price >= upper - tolerance:
        return IVResult("at_upper_bound_not_identifiable", None)

    def gap(vol: float) -> float:
        return forward_price(kind, forward, strike, time, vol, discount) - price

    high = 2.0
    while gap(high) < 0 and high < 16:
        high *= 2
    if gap(high) < 0:
        return IVResult("root_not_bracketed", None)
    vol = float(brentq(gap, 0.0, high, xtol=1e-12, rtol=1e-12))
    width = vol * math.sqrt(time)
    d1 = math.log(forward / strike) / width + width / 2
    vega = discount * forward * _phi(d1) * math.sqrt(time)
    status = "ill_conditioned_low_vega" if vega < 1e-6 * discount * forward else "ok"
    return IVResult(status, vol, gap(vol), vega)
