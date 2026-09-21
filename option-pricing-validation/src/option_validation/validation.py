"""Read-only validation of frozen predictions against an external implementation.

This module deliberately does not import pricing.py or study.py. QuantLib is a
third-party code oracle for a shared model, not evidence the model fits markets.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from option_validation.data import sha256, write_json
from option_validation.market_validation import audit_market


def _finish(output: Path, payload: dict) -> dict:
    write_json(output / "validation.json", payload)
    write_json(output / "validation_receipt.json", dict(
        validation_sha256=sha256(output / "validation.json"),
        results_sha256=payload["results_sha256"], protocol=payload["protocol"],
        source_hashes={name: sha256(Path(__file__).with_name(name)) for name in ("validation.py", "market_validation.py")},
        note="Integrity receipt, not a cryptographic signature or a security boundary."))
    return payload


def _finite_or_none(value: float):
    return value if math.isfinite(value) else None


def _ql_option(ql, p: dict, days: int):
    today = ql.Date(1, 7, 2022)
    ql.Settings.instance().evaluationDate = today
    daycount = ql.Actual365Fixed()
    process = ql.BlackScholesMertonProcess(
        ql.QuoteHandle(ql.SimpleQuote(p["spot"])),
        ql.YieldTermStructureHandle(ql.FlatForward(today, p["dividend"], daycount)),
        ql.YieldTermStructureHandle(ql.FlatForward(today, p["rate"], daycount)),
        ql.BlackVolTermStructureHandle(ql.BlackConstantVol(today, ql.NullCalendar(), p["volatility"], daycount)))
    kind = ql.Option.Call if p["kind"] == "call" else ql.Option.Put
    option = ql.VanillaOption(ql.PlainVanillaPayoff(kind, p["strike"]), ql.EuropeanExercise(today + days))
    option.setPricingEngine(ql.AnalyticEuropeanEngine(process))
    return option


def validate(output: Path) -> dict:
    result_path = output / "results.json"
    frozen = json.loads(result_path.read_text(encoding="utf-8"))
    failures, numerical = [], []
    for name, expected in frozen["files"].items():
        if not (output / name).exists() or sha256(output / name) != expected:
            failures.append(dict(check="frozen_file_hash", item=name, detail="File missing or changed after run"))
    payload = dict(results_sha256=sha256(result_path), protocol=frozen["protocol"],
                   oracle="QuantLib.AnalyticEuropeanEngine and QuantLib.blackFormula",
                   failures=failures, numerical_checks=numerical, market_checks={},
                   software_validation="FAIL", market_validation="NOT_ESTABLISHED")
    # This is the independently declared protocol inventory, not a case list
    # obtained from the implementation-under-test or inferred from its output.
    expected = {}
    for kind in ("call", "put"):
        for strike in (50.0, 80.0, 95.0, 100.0, 105.0, 120.0, 200.0):
            for days in (1, 30, 90, 365):
                for sigma in (0.05, 0.2, 0.6):
                    for rate in (-0.01, 0.05):
                        expected[f"case-{len(expected):04d}"] = dict(kind=kind, spot=100.0, strike=strike,
                            time=days / 365, volatility=sigma, rate=rate, dividend=0.02)
    for kind in ("call", "put"):
        for days, sigma in ((0, 0.2), (90, 0.0)):
            for strike in (80.0, 100.0, 120.0):
                expected[f"boundary-{len(expected):04d}"] = dict(kind=kind, spot=100.0, strike=strike,
                    time=days / 365, volatility=sigma, rate=0.03, dividend=0.01)
    ids = [row["case_id"] for row in frozen["numerical"]]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        failures.append(dict(check="complete_numerical_protocol_inventory", detail=f"Expected {len(expected)} unique fixed cases; found {len(ids)} rows"))
    for row in frozen["numerical"]:
        if row["case_id"] not in expected:
            continue
        if row["parameters"] != expected[row["case_id"]]:
            failures.append(dict(check="fixed_numerical_parameter_contract", item=row["case_id"]))
        p = expected[row["case_id"]]
        boundary = row["case_id"].startswith("boundary")
        gated = not boundary and p["strike"] in (80, 100, 120) and p["time"] >= 30 / 365 and p["volatility"] >= 0.2
        expected_steps = [128] if boundary else ([128, 256, 512, 1024, 2048] if gated else [])
        if row["crr_gate"] != gated or [tree["steps"] for tree in row["crr"]] != expected_steps:
            failures.append(dict(check="complete_crr_protocol_inventory", item=row["case_id"]))
    try:
        import QuantLib as ql
    except ImportError:
        failures.append(dict(check="independent_oracle", detail="QuantLib unavailable; independent validation not performed"))
        return _finish(output, payload)
    payload["quantlib_version"] = ql.__version__
    previous_date = ql.Settings.instance().evaluationDate
    try:
        for row in frozen["numerical"]:
            p = row["parameters"]
            try:
                if abs(p["time"] - row["days"] / 365) > 1e-12:
                    raise ValueError("ACT/365 benchmark time inconsistent with integer days")
                if p["time"] == 0 or p["volatility"] == 0:
                    sign = 1 if p["kind"] == "call" else -1
                    terminal = p["spot"] * math.exp((p["rate"] - p["dividend"]) * p["time"])
                    reference = math.exp(-p["rate"] * p["time"]) * max(sign * (terminal - p["strike"]), 0.0)
                    if row["greeks"]["status"] != "nonregular_boundary":
                        raise ValueError("Boundary Greeks must not be fabricated")
                    references = {}
                else:
                    option = _ql_option(ql, p, row["days"])
                    reference = option.NPV()
                    references = dict(delta=option.delta(), gamma=option.gamma(), vega_1pct=option.vega() / 100,
                                      theta_day=option.theta() / 365, rho_1pct=option.rho() / 100)
                error = abs(row["price"] - reference)
                if not math.isfinite(error) or error > 1e-9 * p["spot"]:
                    failures.append(dict(check="analytic_price_vs_quantlib", item=row["case_id"], error=_finite_or_none(error)))
                greek_errors = {}
                for key, expected in references.items():
                    actual = row["greeks"][key]
                    difference = abs(actual - expected)
                    greek_errors[key] = _finite_or_none(difference)
                    if not math.isfinite(difference) or difference > 1e-7 * max(1.0, abs(expected)):
                        failures.append(dict(check=f"{key}_vs_quantlib", item=row["case_id"], error=_finite_or_none(difference)))
                iv = row.get("iv")
                if iv and iv["status"] == "ok" and abs(iv["volatility"] - p["volatility"]) > 1e-5:
                    failures.append(dict(check="well_conditioned_iv_roundtrip", item=row["case_id"]))
                crr_errors = []
                for tree in row["crr"]:
                    difference = abs(tree["price"] - reference)
                    crr_errors.append(dict(steps=tree["steps"], absolute_error=_finite_or_none(difference)))
                    if not math.isfinite(difference):
                        failures.append(dict(check="crr_price_must_be_finite", item=row["case_id"]))
                    if row["crr_gate"] and tree["steps"] == 2048 and difference > 2e-4 * p["spot"]:
                        failures.append(dict(check="crr_2048_price_vs_quantlib", item=row["case_id"], error=difference))
                numerical.append(dict(case_id=row["case_id"], reference_price=reference, absolute_error=_finite_or_none(error),
                                      greek_errors=greek_errors, crr_errors=crr_errors))
            except (ValueError, RuntimeError, OverflowError, TypeError) as exc:
                failures.append(dict(check="numerical_case_exception", item=row["case_id"], detail=str(exc)))
        payload["market_checks"] = audit_market(ql, output, frozen, failures)
        try:
            payload["shock_checks"] = _validate_shocks(ql, frozen["shocks"], failures)
        except (ValueError, RuntimeError, OverflowError, TypeError, KeyError) as exc:
            failures.append(dict(check="shock_case_exception", detail=str(exc)))
            payload["shock_checks"] = dict(scenarios_checked=0)
    finally:
        ql.Settings.instance().evaluationDate = previous_date
    payload["software_validation"] = "PASS" if not failures else "FAIL"
    payload["numerical_cases_checked"] = len(numerical)
    payload["market_validation"] = "NOT_ESTABLISHED_DAILY_QUOTES_AND_DISCOUNT_PROXY"
    payload["conclusion"] = ("External code agreement and input/holdout checks are distinct from market model adequacy. "
                             "No acceptance floor was selected for empirical spread coverage. Poor or inconsistent quote fit remains visible.")
    return _finish(output, payload)


def _validate_shocks(ql, shock: dict, failures: list) -> dict:
    fixed_base = dict(spot=100.0, time=90 / 365, volatility=0.2, rate=0.03, dividend=0.01)
    fixed_legs = [dict(kind="call", strike=100.0, quantity=2), dict(kind="call", strike=110.0, quantity=-1),
                  dict(kind="put", strike=90.0, quantity=3), dict(kind="put", strike=100.0, quantity=-2)]
    if shock["base"] != fixed_base or shock["legs"] != fixed_legs or shock["multiplier"] != 100:
        failures.append(dict(check="frozen_shock_portfolio_contract"))
    required = {(s, v, 1) for s in (-5, -1, 0, 1, 5) for v in (-0.01, 0.0, 0.01)}
    actual = [(r["spot_change_pct"], r["volatility_change"], r["days_elapsed"]) for r in shock["scenarios"]]
    if len(actual) != len(set(actual)) or set(actual) != required:
        failures.append(dict(check="complete_shock_protocol_inventory", detail=f"Expected 15 unique scenarios; found {len(actual)}"))
    def value(base):
        total = 0.0
        for leg in fixed_legs:
            p = dict(base, kind=leg["kind"], strike=leg["strike"])
            option = _ql_option(ql, p, round(p["time"] * 365))
            total += leg["quantity"] * 100 * option.NPV()
        return total
    baseline = value(fixed_base)
    baseline_error = abs(baseline - shock["base_value"])
    if not math.isfinite(baseline_error) or baseline_error > 1e-6:
        failures.append(dict(check="shock_base_value_vs_quantlib"))
    greek_reference = dict(delta=0.0, gamma=0.0, vega_1pct=0.0, theta_day=0.0)
    for leg in fixed_legs:
        option = _ql_option(ql, dict(fixed_base, kind=leg["kind"], strike=leg["strike"]), 90)
        values = dict(delta=option.delta(), gamma=option.gamma(), vega_1pct=option.vega() / 100, theta_day=option.theta() / 365)
        for name, number in values.items():
            greek_reference[name] += leg["quantity"] * 100 * number
    for name, number in greek_reference.items():
        difference = abs(number - shock["greeks"][name])
        if not math.isfinite(difference) or difference > 1e-7:
            failures.append(dict(check="shock_portfolio_greeks_vs_quantlib", field=name))
    max_error = 0.0
    for row in shock["scenarios"]:
        p = dict(fixed_base, spot=fixed_base["spot"] * (1 + row["spot_change_pct"] / 100),
                 time=fixed_base["time"] - row["days_elapsed"] / 365,
                 volatility=fixed_base["volatility"] + row["volatility_change"])
        difference = abs(value(p) - baseline - row["full_revaluation_pnl"])
        if math.isfinite(difference):
            max_error = max(max_error, difference)
        if not math.isfinite(difference) or difference > 1e-6:
            failures.append(dict(check="portfolio_full_revaluation_vs_quantlib", item=str(row), error=_finite_or_none(difference)))
        ds = fixed_base["spot"] * row["spot_change_pct"] / 100
        approximation = (greek_reference["delta"] * ds + .5 * greek_reference["gamma"] * ds**2
                         + greek_reference["vega_1pct"] * row["volatility_change"] * 100
                         + greek_reference["theta_day"] * row["days_elapsed"])
        for name, expected in dict(greek_approximation_pnl=approximation,
                                   residual=value(p) - baseline - approximation).items():
            difference = abs(expected - row[name])
            if not math.isfinite(difference) or difference > 1e-6:
                failures.append(dict(check="shock_approximation_recalculation", field=name))
    return dict(scenarios_checked=len(shock["scenarios"]), maximum_quantlib_pnl_error=max_error)
