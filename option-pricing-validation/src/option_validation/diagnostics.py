"""Post-hoc descriptive analyses; original model results are never rewritten."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from option_validation.data import sha256, write_json

RECIPE = "fixed-cohort-rate-and-error-diagnostics-v1"
ALL = "ALL_BASE_STATUSES"
BANDS = ("K/S<=0.95", "0.95<K/S<=1.05", "K/S>1.05")
INPUTS = ("results.json", "predictions.csv", "groups.json", "validation.json", "validation_receipt.json")
COLS = ["quote_id", "quote_date", "expiration", "kind", "moneyness", "split", "group_status",
        "assignment", "rate_shift", "bid", "ask", "mid", "model_price"]


def verify_frozen_inputs(output: Path) -> dict:
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    validation = json.loads((output / "validation.json").read_text(encoding="utf-8"))
    receipt = json.loads((output / "validation_receipt.json").read_text(encoding="utf-8"))
    if receipt["validation_sha256"] != sha256(output / "validation.json") or validation["results_sha256"] != sha256(output / "results.json"):
        raise ValueError("Post-hoc analysis requires an unchanged validated result snapshot")
    if validation["software_validation"] != "PASS":
        raise ValueError("Post-hoc market diagnostics require a successful original software audit")
    if set(receipt.get("source_hashes", {})) != {"validation.py", "market_validation.py"}:
        raise ValueError("Validator source receipt is missing; rerun validate")
    for name, digest in receipt["source_hashes"].items():
        if sha256(Path(__file__).with_name(name)) != digest:
            raise ValueError("Validator source changed; rerun validate before diagnostics")
    for name, digest in results["files"].items():
        if sha256(output / name) != digest:
            raise ValueError(f"Frozen input changed before post-hoc analysis: {name}")
    return {name: sha256(output / name) for name in INPUTS}


def read_heldout(output: Path) -> pd.DataFrame:
    chunks = []
    for chunk in pd.read_csv(output / "predictions.csv", usecols=COLS, chunksize=50000):
        chunks.append(chunk[chunk["assignment"] == "holdout"])
    frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=COLS)
    if frame.duplicated(["quote_id", "rate_shift"]).any():
        raise ValueError("Duplicate held-out quote/scenario keys")
    if not set(frame["rate_shift"].unique()) <= {-0.01, 0.0, 0.01}:
        raise ValueError("Unexpected rate scenario")
    frame["error"] = frame["model_price"] - frame["mid"]
    frame["abs_error"] = frame["error"].abs()
    frame["covered"] = ((frame["bid"] <= frame["model_price"]) & (frame["model_price"] <= frame["ask"])).astype(float)
    frame["moneyness_band"] = pd.cut(frame["moneyness"], [0, .95, 1.05, np.inf], labels=BANDS).astype(str)
    return frame


def _counts(frame: pd.DataFrame) -> dict:
    return dict(quotes=len(frame), dates=int(frame["quote_date"].nunique()),
                groups=len(frame[["quote_date", "expiration"]].drop_duplicates()))


def _levels(frame: pd.DataFrame, columns: list[str]) -> dict:
    direct = frame[columns].mean()
    days = frame.groupby("quote_date")[columns].mean().mean()
    groups = frame.groupby(["quote_date", "expiration"])[columns].mean().mean()
    return {f"{prefix}{column}": float(values[column]) for prefix, values in
            (("", direct), ("equal_date_", days), ("equal_group_", groups)) for column in columns}


def _strata(frame: pd.DataFrame):
    for split, split_frame in frame.groupby("split", sort=True):
        for status in (ALL, *sorted(split_frame["group_status"].unique())):
            selected = split_frame if status == ALL else split_frame[split_frame["group_status"] == status]
            if not selected.empty:
                yield split, status, selected


def compute_diagnostics(frame: pd.DataFrame, input_hashes: dict) -> dict:
    base = frame[frame["rate_shift"] == 0].copy().set_index("quote_id", drop=False)
    scenarios = {shift: frame[frame["rate_shift"] == shift].set_index("quote_id", drop=False) for shift in (-.01, .01)}
    common = base.index
    for other in scenarios.values():
        common = common.intersection(other.index, sort=False)
    paired_base = base.loc[common].copy()
    invariant = ["quote_date", "expiration", "kind", "moneyness", "split", "bid", "ask", "mid"]
    for other in scenarios.values():
        aligned = other.loc[common]
        for column in invariant:
            if not np.array_equal(paired_base[column].to_numpy(), aligned[column].to_numpy()):
                raise ValueError(f"Paired rate scenarios changed the observed quote: {column}")
    population = dict(base_holdout_quotes=len(base), base_holdout_groups=_counts(base)["groups"],
                      common_quotes=len(common), common_groups=_counts(paired_base)["groups"],
                      common_dates=_counts(paired_base)["dates"],
                      excluded_base_quotes=len(base) - len(common),
                      excluded_base_groups=_counts(base)["groups"] - _counts(paired_base)["groups"],
                      scope="Intersection of the exact held-out quote IDs under all three rate assumptions; all paired summaries use this single cohort.")
    exclusions = []
    for quote_id in base.index.difference(common):
        row = base.loc[quote_id]
        missing = [shift for shift, other in scenarios.items() if quote_id not in other.index]
        exclusions.append(dict(quote_id=quote_id, quote_date=row["quote_date"], expiration=row["expiration"],
                               missing_rate_shifts=missing))
    matched, daily_paired, transitions = [], [], []
    for shift, other in scenarios.items():
        paired = paired_base.copy()
        alternate = other.loc[common]
        paired["base_mae_points"] = paired["abs_error"]
        paired["shift_mae_points"] = alternate["abs_error"]
        paired["delta_mae_points"] = alternate["abs_error"] - paired["abs_error"]
        paired["base_coverage"] = paired["covered"]
        paired["shift_coverage"] = alternate["covered"]
        paired["delta_coverage_pp"] = (alternate["covered"] - paired["covered"]) * 100
        paired["mean_abs_price_change_points"] = (alternate["model_price"] - paired["model_price"]).abs()
        paired["shifted_group_status"] = alternate["group_status"]
        measures = ["base_mae_points", "shift_mae_points", "delta_mae_points", "base_coverage",
                    "shift_coverage", "delta_coverage_pp", "mean_abs_price_change_points"]
        for split, status, selected in _strata(paired):
            row = dict(split=split, base_group_status=status, rate_shift=shift,
                       common_quotes=len(selected), common_groups=_counts(selected)["groups"], dates=_counts(selected)["dates"])
            row.update(_levels(selected, measures))
            matched.append(row)
            for date, daily in selected.groupby("quote_date", sort=True):
                record = dict(quote_date=date, split=split, base_group_status=status, rate_shift=shift,
                              quotes=len(daily), groups=_counts(daily)["groups"])
                record.update({column: float(daily[column].mean()) for column in measures})
                daily_paired.append(record)
        for keys, selected in paired.groupby(["split", "group_status", "shifted_group_status"], sort=True):
            transitions.append(dict(split=keys[0], base_group_status=keys[1], shifted_group_status=keys[2],
                                    rate_shift=shift, **_counts(selected)))
    daily_base, slices = [], []
    base["mae_points"], base["mean_error_points"], base["coverage"] = base["abs_error"], base["error"], base["covered"]
    for split, status, selected in _strata(base):
        for date, daily in selected.groupby("quote_date", sort=True):
            daily_base.append(dict(quote_date=date, split=split, base_group_status=status,
                                   quotes=len(daily), groups=_counts(daily)["groups"],
                                   mae_points=float(daily["mae_points"].mean()),
                                   mean_error_points=float(daily["mean_error_points"].mean()), coverage=float(daily["coverage"].mean())))
        for kind in ("all", "call", "put"):
            by_kind = selected if kind == "all" else selected[selected["kind"] == kind]
            for band in ("all", *BANDS):
                sliced = by_kind if band == "all" else by_kind[by_kind["moneyness_band"] == band]
                if not sliced.empty:
                    record = dict(split=split, base_group_status=status, call_put=kind, moneyness_band=band,
                                  **_counts(sliced))
                    record.update(_levels(sliced, ["mae_points", "mean_error_points", "coverage"]))
                    slices.append(record)
    return dict(schema_version=1, recipe=RECIPE, analysis_kind="post_hoc_descriptive", input_hashes=input_hashes,
                population=population, matched_rate=matched, status_transitions=transitions,
                daily_base=daily_base, daily_paired=daily_paired, error_slices=slices, pair_exclusions=exclusions,
                interpretations=[
                    "Matched rate effects use the same quote IDs under all three assumptions and fixed base-rate status strata. The alternative status is a reported outcome, never a cohort selector.",
                    "Forward and common volatility were refitted on the original training quotes at each discount assumption. Paired differences describe this full recalibrated scenario; they are not partial rho or causal interest-rate effects.",
                    "Quote-weighted, equal-date and equal-date/expiry-group means describe different weightings. Equal-date/group summaries do not make observations independent.",
                    "These diagnostics were selected after the original results were inspected. They add no p-values, confidence intervals, significance claim, fresh holdout or re-tuned model.",
                    "A changed parity status can confound the original scenario-specific status tables. Those tables are retained as composition descriptions, not directly matched sensitivity estimates."])


def generate_diagnostics(output: Path) -> dict:
    input_hashes = verify_frozen_inputs(output)
    payload = compute_diagnostics(read_heldout(output), input_hashes)
    write_json(output / "diagnostics.json", payload)
    return payload
