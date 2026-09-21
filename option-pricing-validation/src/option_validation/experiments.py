"""Deterministic numerical experiments and a small full-revaluation case."""

from __future__ import annotations

import math

from option_validation.pricing import crr_price, implied_volatility, spot_greeks, spot_price


def numerical_cases() -> list[dict]:
    rows = []
    for kind in ("call", "put"):
        for ratio in (0.5, 0.8, 0.95, 1.0, 1.05, 1.2, 2.0):
            for days in (1, 30, 90, 365):
                for sigma in (0.05, 0.2, 0.6):
                    for rate in (-0.01, 0.05):
                        p = dict(kind=kind, spot=100.0, strike=100 * ratio, time=days / 365,
                                 volatility=sigma, rate=rate, dividend=0.02)
                        price = spot_price(**p)
                        regular = ratio in (0.8, 1.0, 1.2) and days >= 30 and sigma >= 0.2
                        trees = []
                        if regular:
                            for n in (128, 256, 512, 1024, 2048):
                                tree = crr_price(**p, steps=n)
                                trees.append(dict(steps=n, price=tree, absolute_error=abs(tree - price)))
                        forward = p["spot"] * math.exp((rate - p["dividend"]) * p["time"])
                        iv = implied_volatility(kind, price, forward, p["strike"], p["time"], math.exp(-rate * p["time"]))
                        rows.append(dict(case_id=f"case-{len(rows):04d}", parameters=p, days=days,
                                         price=price, greeks=spot_greeks(**p), iv=iv.as_dict(),
                                         crr=trees, crr_gate=regular))
    # Deterministic boundaries are deliberately not given fabricated Greeks.
    for kind in ("call", "put"):
        for days, sigma in ((0, 0.2), (90, 0.0)):
            for strike in (80.0, 100.0, 120.0):
                p = dict(kind=kind, spot=100.0, strike=strike, time=days / 365,
                         volatility=sigma, rate=0.03, dividend=0.01)
                rows.append(dict(case_id=f"boundary-{len(rows):04d}", parameters=p, days=days,
                                 price=spot_price(**p), greeks=spot_greeks(**p), iv=None,
                                 crr=[dict(steps=128, price=crr_price(**p, steps=128))], crr_gate=False))
    return rows


def shock_experiment() -> dict:
    """Synthetic complete-input portfolio; no historical hedging claims."""
    base = dict(spot=100.0, time=90 / 365, volatility=0.2, rate=0.03, dividend=0.01)
    legs = [dict(kind="call", strike=100.0, quantity=2), dict(kind="call", strike=110.0, quantity=-1),
            dict(kind="put", strike=90.0, quantity=3), dict(kind="put", strike=100.0, quantity=-2)]
    multiplier = 100
    baseline = 0.0
    totals = {key: 0.0 for key in ("delta", "gamma", "vega_1pct", "theta_day")}
    for leg in legs:
        params = dict(base, kind=leg["kind"], strike=leg["strike"])
        baseline += leg["quantity"] * multiplier * spot_price(**params)
        greeks = spot_greeks(**params)
        for key in totals:
            totals[key] += leg["quantity"] * multiplier * greeks[key]
    rows = []
    for percent in (-5, -1, 0, 1, 5):
        for vol_change in (-0.01, 0.0, 0.01):
            ds = base["spot"] * percent / 100
            shocked = dict(base, spot=base["spot"] + ds, volatility=base["volatility"] + vol_change,
                           time=base["time"] - 1 / 365)
            value = sum(leg["quantity"] * multiplier * spot_price(**shocked, kind=leg["kind"], strike=leg["strike"]) for leg in legs)
            approximate = (totals["delta"] * ds + 0.5 * totals["gamma"] * ds**2
                           + totals["vega_1pct"] * vol_change * 100 + totals["theta_day"])
            rows.append(dict(spot_change_pct=percent, volatility_change=vol_change, days_elapsed=1,
                             full_revaluation_pnl=value - baseline, greek_approximation_pnl=approximate,
                             residual=value - baseline - approximate))
    return dict(base=base, legs=legs, multiplier=multiplier, base_value=baseline, greeks=totals,
                scenarios=rows, note="Synthetic model-consistent shocks; omitted cross/higher-order sensitivities explain approximation error. Not observed market P&L.")
