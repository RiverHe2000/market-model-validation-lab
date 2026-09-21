"""Independent reconstruction of descriptive analyses from frozen predictions.

No import of diagnostics.py: scalar accumulators independently reconstruct the
paired cohorts, fixed baseline strata, errors and date/group weightings.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from option_validation.data import sha256, write_json


class Moments:
    def __init__(self, names):
        self.names = names
        self.n = 0
        self.sums = [0.0] * len(names)
        self.days = {}
        self.groups = {}

    def add(self, date, expiry, values):
        self.n += 1
        for i, value in enumerate(values):
            self.sums[i] += value
        for mapping, key in ((self.days, date), (self.groups, (date, expiry))):
            item = mapping.setdefault(key, [0, *([0.0] * len(values))])
            item[0] += 1
            for i, value in enumerate(values, 1):
                item[i] += value

    def means(self, weighted=True):
        out = {name: self.sums[i] / self.n for i, name in enumerate(self.names)}
        if weighted:
            for prefix, mapping in (("equal_date_", self.days), ("equal_group_", self.groups)):
                for i, name in enumerate(self.names, 1):
                    out[prefix + name] = sum(item[i] / item[0] for item in mapping.values()) / len(mapping)
        return out


def reconstruct(output: Path) -> dict:
    columns = ["quote_id", "quote_date", "expiration", "kind", "moneyness", "split", "group_status",
               "assignment", "rate_shift", "bid", "ask", "mid", "model_price"]
    quotes = {-0.01: {}, 0.0: {}, 0.01: {}}
    for chunk in pd.read_csv(output / "predictions.csv", usecols=columns, chunksize=40000):
        for row in chunk.loc[chunk.assignment == "holdout"].itertuples(index=False):
            record = row._asdict()
            shift, quote_id = float(record["rate_shift"]), record["quote_id"]
            if shift not in quotes or quote_id in quotes[shift]:
                raise ValueError("Invalid/duplicate source quote scenario")
            quotes[shift][quote_id] = record
    base = quotes[0.0]
    common = set(base) & set(quotes[-0.01]) & set(quotes[0.01])
    paired_names = ["base_mae_points", "shift_mae_points", "delta_mae_points", "base_coverage",
                    "shift_coverage", "delta_coverage_pp", "mean_abs_price_change_points"]
    error_names = ["mae_points", "mean_error_points", "coverage"]
    matched, daily_paired, daily_base, slices, transitions = {}, {}, {}, {}, {}
    for quote_id, row in base.items():
        date, expiry, split, status = row["quote_date"], row["expiration"], row["split"], row["group_status"]
        error = float(row["model_price"] - row["mid"])
        covered = float(row["bid"] <= row["model_price"] <= row["ask"])
        values = (abs(error), error, covered)
        band = "K/S<=0.95" if row["moneyness"] <= .95 else ("0.95<K/S<=1.05" if row["moneyness"] <= 1.05 else "K/S>1.05")
        for label in ("ALL_BASE_STATUSES", status):
            daily_base.setdefault((date, split, label), Moments(error_names)).add(date, expiry, values)
            for kind in ("all", row["kind"]):
                for selected_band in ("all", band):
                    slices.setdefault((split, label, kind, selected_band), Moments(error_names)).add(date, expiry, values)
        if quote_id not in common:
            continue
        for shift in (-0.01, 0.01):
            other = quotes[shift][quote_id]
            for name in ("quote_date", "expiration", "kind", "moneyness", "split", "bid", "ask", "mid"):
                if row[name] != other[name]:
                    raise ValueError(f"Scenario altered source quote field {name}")
            other_error = other["model_price"] - row["mid"]
            other_covered = float(row["bid"] <= other["model_price"] <= row["ask"])
            measures = (abs(error), abs(other_error), abs(other_error) - abs(error), covered,
                        other_covered, (other_covered - covered) * 100, abs(other["model_price"] - row["model_price"]))
            for label in ("ALL_BASE_STATUSES", status):
                matched.setdefault((split, label, shift), Moments(paired_names)).add(date, expiry, measures)
                daily_paired.setdefault((date, split, label, shift), Moments(paired_names)).add(date, expiry, measures)
            transitions.setdefault((split, status, other["group_status"], shift), Moments([])).add(date, expiry, [])
    def rows(mapping, keys, mode):
        result = []
        for values, moment in sorted(mapping.items()):
            row = dict(zip(keys, values, strict=True))
            if mode == "matched":
                row.update(common_quotes=moment.n, common_groups=len(moment.groups), dates=len(moment.days))
            elif mode == "daily":
                row.update(quotes=moment.n, groups=len(moment.groups))
            else:
                row.update(quotes=moment.n, dates=len(moment.days), groups=len(moment.groups))
            row.update(moment.means(weighted=mode in {"matched", "slice"}))
            result.append(row)
        return result
    base_groups = {(r["quote_date"], r["expiration"]) for r in base.values()}
    common_groups = {(base[i]["quote_date"], base[i]["expiration"]) for i in common}
    return dict(population=dict(base_holdout_quotes=len(base), base_holdout_groups=len(base_groups),
                    common_quotes=len(common), common_groups=len(common_groups), common_dates=len({base[i]["quote_date"] for i in common}),
                    excluded_base_quotes=len(base) - len(common), excluded_base_groups=len(base_groups) - len(common_groups)),
                matched_rate=rows(matched, ("split", "base_group_status", "rate_shift"), "matched"),
                daily_paired=rows(daily_paired, ("quote_date", "split", "base_group_status", "rate_shift"), "daily"),
                daily_base=rows(daily_base, ("quote_date", "split", "base_group_status"), "daily"),
                error_slices=rows(slices, ("split", "base_group_status", "call_put", "moneyness_band"), "slice"),
                status_transitions=rows(transitions, ("split", "base_group_status", "shifted_group_status", "rate_shift"), "slice"),
                pair_exclusions=[dict(quote_id=i, quote_date=base[i]["quote_date"], expiration=base[i]["expiration"],
                                      missing_rate_shifts=[s for s in (-.01, .01) if i not in quotes[s]]) for i in sorted(set(base) - common)])


def validate_diagnostics(output: Path) -> dict:
    actual = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))
    failures = []
    for name in ("results.json", "predictions.csv", "groups.json", "validation.json", "validation_receipt.json"):
        if actual.get("input_hashes", {}).get(name) != sha256(output / name):
            failures.append(dict(check="diagnostic_input_hash", item=name))
    if actual.get("analysis_kind") != "post_hoc_descriptive" or actual.get("recipe") != "fixed-cohort-rate-and-error-diagnostics-v1":
        failures.append(dict(check="diagnostic_analysis_classification"))
    reference = reconstruct(output)
    for name, value in reference["population"].items():
        if actual["population"].get(name) != value:
            failures.append(dict(check="fixed_population_reconstruction", field=name))
    keys = dict(matched_rate=("split", "base_group_status", "rate_shift"),
                daily_paired=("quote_date", "split", "base_group_status", "rate_shift"),
                daily_base=("quote_date", "split", "base_group_status"),
                error_slices=("split", "base_group_status", "call_put", "moneyness_band"),
                status_transitions=("split", "base_group_status", "shifted_group_status", "rate_shift"),
                pair_exclusions=("quote_id",))
    for table, columns in keys.items():
        expected = {tuple(row[k] for k in columns): row for row in reference[table]}
        observed = {tuple(row[k] for k in columns): row for row in actual[table]}
        if len(observed) != len(actual[table]) or set(observed) != set(expected):
            failures.append(dict(check="complete_diagnostic_table_inventory", table=table))
        for key in set(expected) & set(observed):
            for column, target in expected[key].items():
                value = observed[key].get(column)
                if isinstance(target, float):
                    good = isinstance(value, (float, int)) and math.isfinite(value) and abs(value - target) <= 1e-9 * max(1, abs(target))
                else:
                    good = value == target
                if not good:
                    failures.append(dict(check="independent_descriptive_recalculation", table=table, key=str(key), field=column))
    result = dict(schema_version=1, status="PASS" if not failures else "FAIL", failures=failures,
                  diagnostics_sha256=sha256(output / "diagnostics.json"),
                  input_hashes=actual["input_hashes"], common_quotes=reference["population"]["common_quotes"],
                  audited_tables={name: len(reference[name]) for name in keys},
                  approach="Independent scalar accumulators; fixed base-status cohorts; same quote IDs; descriptive date/group means only")
    write_json(output / "diagnostics_validation.json", result)
    write_json(output / "diagnostics_validation_receipt.json", dict(
        diagnostics_sha256=sha256(output / "diagnostics.json"),
        validation_sha256=sha256(output / "diagnostics_validation.json"),
        source_hashes={name: sha256(Path(__file__).with_name(name)) for name in ("diagnostics.py", "diagnostics_validation.py")}))
    return result


def checked_diagnostics(output: Path) -> dict:
    payload = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))
    assessment = json.loads((output / "diagnostics_validation.json").read_text(encoding="utf-8"))
    receipt = json.loads((output / "diagnostics_validation_receipt.json").read_text(encoding="utf-8"))
    if receipt["diagnostics_sha256"] != sha256(output / "diagnostics.json") or receipt["validation_sha256"] != sha256(output / "diagnostics_validation.json"):
        raise ValueError("Post-hoc diagnostics or assessment changed after its receipt")
    if set(receipt.get("source_hashes", {})) != {"diagnostics.py", "diagnostics_validation.py"}:
        raise ValueError("Post-hoc diagnostic source receipt is incomplete; run diagnose again")
    expected_inputs = {"results.json", "predictions.csv", "groups.json", "validation.json", "validation_receipt.json"}
    if set(payload.get("input_hashes", {})) != expected_inputs or assessment.get("input_hashes") != payload["input_hashes"]:
        raise ValueError("Post-hoc diagnostic input inventory or assessment binding is incomplete")
    if assessment.get("diagnostics_sha256") != sha256(output / "diagnostics.json"):
        raise ValueError("Post-hoc diagnostic assessment is bound to a different payload")
    for name, digest in receipt["source_hashes"].items():
        if sha256(Path(__file__).with_name(name)) != digest:
            raise ValueError("Post-hoc diagnostic source changed; run diagnose again")
    for name, digest in payload["input_hashes"].items():
        if sha256(output / name) != digest:
            raise ValueError("Post-hoc diagnostics are stale; run diagnose again")
    if assessment["status"] != "PASS":
        raise ValueError("Post-hoc diagnostics did not pass independent reconstruction")
    return payload
