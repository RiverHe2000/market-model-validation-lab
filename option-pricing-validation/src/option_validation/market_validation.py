"""External quote-result audit. No imports from either pricing or fitting code."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


def _close(a, b, tolerance=1e-9):
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) <= tolerance * max(1, abs(float(b)))


def audit_market(ql, output: Path, frozen: dict, failures: list) -> dict:
    groups = json.loads((output / "groups.json").read_text(encoding="utf-8"))["groups"]
    if not groups:
        count = sum(len(c) for c in pd.read_csv(output / "predictions.csv", chunksize=40000))
        if count:
            failures.append(dict(check="unexpected_predictions_without_groups", error=count))
        return dict(predictions_checked=count, note="No fitted market groups; no market result imputed.")
    quotes = pd.read_csv(output / "ingested_quotes.csv", keep_default_na=False).set_index("quote_id")
    if quotes.index.duplicated().any():
        failures.append(dict(check="duplicate_source_quote_id"))
        return dict(predictions_checked=0)
    positions = quotes.groupby(["quote_date", "expiration"], sort=False).indices
    shifts = (-0.01, 0.0, 0.01)
    catalogue = {}
    expected = np.zeros((3, len(quotes)), dtype=bool)
    seen = np.zeros_like(expected)
    for group in groups:
        key = (group["quote_date"], group["expiration"], group["rate_shift"])
        if key in catalogue:
            failures.append(dict(check="duplicate_fitted_group", item=str(key)))
        catalogue[key] = group
        source_key = key[:2]
        if source_key not in positions or key[2] not in shifts:
            failures.append(dict(check="unexpected_fitted_group", item=str(key)))
            continue
        source = quotes.iloc[positions[source_key]]
        train = source[source["assignment"] == "train"]
        holdout = source[source["assignment"] == "holdout"]
        if group["status"] == "REJECTED":
            if not group.get("reason"):
                failures.append(dict(check="group_rejection_without_reason", item=str(key)))
            continue
        expected[shifts.index(key[2]), positions[source_key]] = True
        if set(group["training_quote_ids"]) != set(train.index) or set(group["holdout_quote_ids"]) != set(holdout.index):
            failures.append(dict(check="complete_source_train_holdout_membership", item=str(key)))
        for assignment_name, rows in (("train", train), ("holdout", holdout)):
            for quote_id, row in rows.iterrows():
                hashed = f"option-protocol-v1|{row['quote_date']}|{row['expiration']}|{row['strike']:.8f}"
                bucket = int(hashlib.sha256(hashed.encode()).hexdigest()[:8], 16) % 10
                if assignment_name != ("train" if bucket < 7 else "holdout"):
                    failures.append(dict(check="paired_hash_assignment", item=quote_id))
        first = source.iloc[0]
        rate = float(first["rate"]) + key[2]
        time = int(first["days"]) / 365
        discount = math.exp(-rate * time)
        for name, value in dict(rate=rate, time=time, discount=discount, days=int(first["days"]),
                                rows=len(source), training_rows=len(train), holdout_rows=len(holdout)).items():
            if not _close(group[name], value):
                failures.append(dict(check="fitted_group_input_contract", item=str(key), field=name))
        calls, puts = train[train["kind"] == "call"].set_index("strike"), train[train["kind"] == "put"].set_index("strike")
        paired = calls.index.intersection(puts.index).sort_values()
        if len(paired) < 3:
            failures.append(dict(check="insufficient_training_pairs_accepted", item=str(key)))
            continue
        strikes = paired.to_numpy(dtype=float)
        low = strikes + (calls.loc[paired, "bid"].to_numpy() - puts.loc[paired, "ask"].to_numpy()) / discount
        high = strikes + (calls.loc[paired, "ask"].to_numpy() - puts.loc[paired, "bid"].to_numpy()) / discount
        mid = strikes + (calls.loc[paired, "mid"].to_numpy() - puts.loc[paired, "mid"].to_numpy()) / discount
        lower, upper = float(low.max()), float(high.min())
        forward = float(np.median(mid))
        status = "EXPLORATORY_INCONSISTENT_QUOTES"
        if lower <= upper:
            forward = min(max(forward, lower), upper)
            status = "PARITY_COMPATIBLE_DAILY_PROXY"
        if not _close(group["forward"], forward) or group["status"] != status:
            failures.append(dict(check="forward_training_only_reconstruction", item=str(key)))
        parity_expected = dict(intersection_lower=lower, intersection_upper=upper,
                               intersection_gap=max(lower - upper, 0),
                               intersection_gap_fraction=max(lower - upper, 0) / forward,
                               pair_interval_satisfaction=float(np.mean((low <= forward) & (forward <= high))),
                               pairs=len(paired))
        for name, value in parity_expected.items():
            if not _close(group["parity"][name], value):
                failures.append(dict(check="parity_bounds_external_recalculation", item=str(key), field=name))
        training_rows = train.to_dict("records")
        def objective(sigma):
            total = 0.0
            for row in training_rows:
                kind = ql.Option.Call if row["kind"] == "call" else ql.Option.Put
                price = ql.blackFormula(kind, row["strike"], forward, sigma * math.sqrt(time), discount)
                total += ((price - row["mid"]) / max(row["spread"] / 2, 0.05))**2
            return total / len(training_rows)
        centre = objective(group["sigma"])
        if not _close(group["training_objective"], centre, 1e-6):
            failures.append(dict(check="training_objective_external_recalculation", item=str(key)))
        for shifted in (max(group["sigma"] - 0.001, 0.01), min(group["sigma"] + 0.001, 3.0)):
            if objective(shifted) < centre - 1e-6 * max(1, centre):
                failures.append(dict(check="common_sigma_local_optimality", item=str(key)))
    expected_keys = {(date, expiry, shift) for date, expiry in positions for shift in shifts}
    if set(catalogue) != expected_keys:
        failures.append(dict(check="complete_date_expiry_shift_group_inventory", detail=f"Missing {len(expected_keys - set(catalogue))}; extra {len(set(catalogue) - expected_keys)}"))
    source_columns = ("kind", "strike", "bid", "ask", "mid", "spread", "spot", "days", "time", "moneyness",
                      "quote_date", "expiration", "assignment", "quality_flags", "rate_date", "split")
    sources = {key: quotes[key].to_numpy() for key in source_columns}
    totals = {}
    count, max_error = 0, 0.0
    for chunk in pd.read_csv(output / "predictions.csv", chunksize=40000):
        indices = quotes.index.get_indexer(chunk["quote_id"])
        for row, index in zip(chunk.to_dict("records"), indices, strict=True):
            count += 1
            if index < 0 or row["rate_shift"] not in shifts:
                failures.append(dict(check="prediction_without_source_or_shift", item=row["quote_id"]))
                continue
            key = (row["quote_date"], row["expiration"], row["rate_shift"])
            group = catalogue.get(key)
            if group is None or group["status"] == "REJECTED":
                failures.append(dict(check="prediction_without_fitted_group", item=row["quote_id"]))
                continue
            shift_index = shifts.index(row["rate_shift"])
            if seen[shift_index, index]:
                failures.append(dict(check="duplicate_prediction_key", item=row["quote_id"]))
            seen[shift_index, index] = True
            for name in source_columns:
                if not _close(row[name], sources[name][index]):
                    failures.append(dict(check="prediction_source_lineage", item=row["quote_id"], field=name))
            for name in ("forward", "discount", "time", "sigma", "rate", "rate_date", "split"):
                if not _close(row[name], group[name]):
                    failures.append(dict(check="prediction_frozen_group_parameter_binding", item=row["quote_id"], field=name))
            if row["group_status"] != group["status"]:
                failures.append(dict(check="prediction_frozen_group_status", item=row["quote_id"]))
            date, rate_date = pd.Timestamp(row["quote_date"]), pd.Timestamp(row["rate_date"])
            if not 0 < (date - rate_date).days <= 7:
                failures.append(dict(check="strictly_prior_rate_available", item=row["quote_id"]))
            if row["split"] != ("development" if date.month <= 8 else "temporal_test"):
                failures.append(dict(check="frozen_temporal_split", item=row["quote_id"]))
            kind = ql.Option.Call if row["kind"] == "call" else ql.Option.Put
            calculator = ql.BlackCalculator(ql.PlainVanillaPayoff(kind, row["strike"]),
                                            group["forward"], group["sigma"] * math.sqrt(group["time"]), group["discount"])
            reference = calculator.value()
            difference = abs(reference - row["model_price"])
            max_error = max(max_error, difference)
            if difference > 1e-9 * group["forward"] or not math.isfinite(difference):
                failures.append(dict(check="quote_price_vs_quantlib_frozen_group", item=row["quote_id"], error=difference))
            for name, value in dict(forward_delta=calculator.deltaForward(), forward_gamma=calculator.gammaForward(), vega_1pct=calculator.vega(group["time"]) / 100).items():
                if not _close(row[name], value, 1e-7):
                    failures.append(dict(check="forward_greek_vs_quantlib", item=row["quote_id"], field=name))
            error = row["model_price"] - row["mid"]
            scaled = error / max(row["spread"] / 2, 0.05)
            covered = row["bid"] <= row["model_price"] <= row["ask"]
            for name, value in dict(error=error, absolute_error=abs(error), spread_scaled_error=scaled).items():
                if not _close(row[name], value):
                    failures.append(dict(check="prediction_error_recalculation", item=row["quote_id"], field=name))
            if bool(row["within_spread"]) != covered:
                failures.append(dict(check="prediction_coverage_recalculation", item=row["quote_id"]))
            for side in ("bid", "ask"):
                vol = row[f"iv_{side}"]
                if pd.notna(vol):
                    value = ql.blackFormula(kind, row["strike"], group["forward"], vol * math.sqrt(group["time"]), group["discount"])
                    if abs(value - row[side]) > 1e-8 * group["forward"]:
                        failures.append(dict(check="iv_interval_endpoint_vs_quantlib", item=row["quote_id"], side=side))
            if row["assignment"] == "holdout":
                band = "K/S<=0.95" if row["moneyness"] <= 0.95 else ("0.95<K/S<=1.05" if row["moneyness"] <= 1.05 else "K/S>1.05")
                for metric_key in ((row["split"], row["group_status"], row["rate_shift"], None), (row["split"], row["group_status"], row["rate_shift"], band)):
                    acc = totals.setdefault(metric_key, dict(n=0, covered=0, absolute=0.0, squared=0.0, scaled=[], dates=set(), groups=set()))
                    acc["n"] += 1
                    acc["covered"] += int(covered)
                    acc["absolute"] += abs(error)
                    acc["squared"] += error**2
                    acc["scaled"].append(abs(scaled))
                    acc["dates"].add(row["quote_date"])
                    acc["groups"].add((row["quote_date"], row["expiration"]))
    if not np.array_equal(seen, expected):
        failures.append(dict(check="complete_prediction_membership", detail=f"Missing {int((expected & ~seen).sum())}; unexpected {int((seen & ~expected).sum())}"))
    summary_keys = set()
    for summary in frozen["market"]["summaries"]:
        key = (summary["split"], summary["group_status"], summary["rate_shift"], summary.get("moneyness_band"))
        if key in summary_keys or key not in totals:
            failures.append(dict(check="duplicate_or_unknown_summary", item=str(key)))
            continue
        summary_keys.add(key)
        acc = totals[key]
        calculated = dict(quotes=acc["n"], dates=len(acc["dates"]), expiry_date_groups=len(acc["groups"]),
                          spread_coverage=acc["covered"] / acc["n"], mae_points=acc["absolute"] / acc["n"],
                          rmse_points=math.sqrt(acc["squared"] / acc["n"]),
                          median_absolute_spread_scaled_error=float(np.median(acc["scaled"])))
        for name, value in calculated.items():
            if not _close(summary[name], value, 1e-8):
                failures.append(dict(check="heldout_statistic_recalculation", item=str(key), field=name))
    if summary_keys != set(totals):
        failures.append(dict(check="complete_summary_inventory"))
    return dict(predictions_checked=count, fitted_groups_checked=sum(g["status"] != "REJECTED" for g in groups),
                maximum_quantlib_price_error=max_error,
                input_lineage="Full source/group membership, common-parameter binding, independent parity bounds, external prices/Greeks/IV, and all published heldout statistics checked")
