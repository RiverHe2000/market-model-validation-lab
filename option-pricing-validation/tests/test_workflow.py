import json
import shutil

import numpy as np
import pandas as pd
import pytest

from option_validation.data import assignment, ingest, sha256, write_json
from option_validation.pricing import implied_volatility, spot_price
from option_validation.report import load_report_receipt, report
from option_validation.study import fit_group, metrics_file, run
from option_validation.validation import validate


@pytest.fixture(scope="module")
def completed_study(tmp_path_factory):
    folder = tmp_path_factory.mktemp("synthetic_option_validation_fixture")
    source, output = folder / "source", folder / "output"
    source.mkdir()
    rows = []
    for strike in range(85, 116):
        # Deliberate strike smile, used only in tests, never advertised as real data.
        volatility = .2 + .0008 * (strike - 100)**2
        for kind in ("call", "put"):
            price = spot_price(kind, 100, strike, 91 / 365, volatility, .03, .01)
            rows.append(dict(underlying="SPXW", style="E", settlement_time="PM", quote_date="2022-07-01",
                             expiration="2022-09-30", strike=strike, type=kind, bid=price - .04,
                             ask=price + .04, underlying_close=100, quote_time="", iv=999, delta=999))
    pd.DataFrame(rows).to_csv(source / "fixture.csv", index=False)
    pd.DataFrame([dict(date="2022-06-30", rate=.03), dict(date="2022-07-01", rate=.40)]).to_csv(folder / "rates.csv", index=False)
    receipt = ingest(source, folder / "rates.csv", output)
    assert receipt["accepted_rows"] == len(rows)
    run(output)
    result = validate(output)
    assert result["software_validation"] == "PASS", result["failures"]
    return output


@pytest.fixture
def study_copy(completed_study, tmp_path):
    target = tmp_path / "study"
    shutil.copytree(completed_study, target)
    return target


def refresh_prediction_hash_and_summaries(output):
    result = json.loads((output / "results.json").read_text())
    result["files"]["predictions.csv"] = sha256(output / "predictions.csv")
    result["market"]["summaries"] = metrics_file(output / "predictions.csv")
    write_json(output / "results.json", result)


def test_end_to_end_external_oracle_source_and_report(completed_study):
    validation = json.loads((completed_study / "validation.json").read_text())
    assert validation["numerical_cases_checked"] == 348
    assert validation["market_checks"]["predictions_checked"] == 62 * 3
    quotes = pd.read_csv(completed_study / "ingested_quotes.csv")
    assert quotes["rate"].eq(.03).all()  # Same-day .40 observation is unavailable.
    assert quotes["quality_flags"].str.contains("quote_time_missing").all()
    assert "iv" not in quotes and "delta" not in quotes  # Provider data are not gold.
    artefacts = report(completed_study)
    assert artefacts["figures"] == 7
    assert (completed_study / "report.html").exists()
    assert "not established" in (completed_study / "VALIDATION_REPORT.md").read_text(encoding="utf-8")
    receipt = json.loads((completed_study / "report_receipt.json").read_text())
    assert receipt["validation_sha256"] == sha256(completed_study / "validation.json")
    assert all(sha256(completed_study / name) == digest for name, digest in receipt["artifacts"].items())
    assert load_report_receipt(completed_study) == receipt
    assert "Inside bid/ask" in (completed_study / "report.html").read_text(encoding="utf-8")


def test_holdout_cannot_change_training_parameters(completed_study):
    quotes = pd.read_csv(completed_study / "ingested_quotes.csv", keep_default_na=False)
    original, _ = fit_group(quotes)
    quotes.loc[quotes.assignment == "holdout", ["bid", "ask", "mid"]] *= 1.2
    changed, _ = fit_group(quotes)
    assert original["sigma"] == changed["sigma"]
    assert original["forward"] == changed["forward"]
    for _, strike in quotes.groupby("strike"):
        assert strike.assignment.nunique() == 1
    assert assignment("2022-07-01", "2022-09-30", 100) == assignment("2022-07-01", "2022-09-30", 100)


def test_inconsistent_parity_is_retained_but_flagged(completed_study):
    quotes = pd.read_csv(completed_study / "ingested_quotes.csv", keep_default_na=False)
    index = quotes[(quotes.assignment == "train") & (quotes.kind == "call")].index[0]
    quotes.loc[index, ["bid", "ask", "mid"]] += 2
    result, rows = fit_group(quotes)
    assert result["status"] == "EXPLORATORY_INCONSISTENT_QUOTES"
    assert result["parity"]["intersection_gap"] > 0
    assert result["parity"]["pair_interval_satisfaction"] < 1
    assert len(rows) == len(quotes)


def test_validator_rejects_per_contract_iv_disguised_as_heldout_fit(study_copy):
    predictions = pd.read_csv(study_copy / "predictions.csv")
    for index, row in predictions[predictions.assignment == "holdout"].iterrows():
        iv = implied_volatility(row["kind"], row["mid"], row["forward"], row["strike"], row["time"], row["discount"])
        predictions.loc[index, "sigma"] = iv.volatility
        predictions.loc[index, "model_price"] = row["mid"]
        predictions.loc[index, ["error", "absolute_error", "spread_scaled_error"]] = 0
        predictions.loc[index, "within_spread"] = True
    predictions.to_csv(study_copy / "predictions.csv", index=False)
    refresh_prediction_hash_and_summaries(study_copy)  # Not merely a stale-hash test.
    result = validate(study_copy)
    assert result["software_validation"] == "FAIL"
    assert any(f["check"] == "prediction_frozen_group_parameter_binding" for f in result["failures"])


def test_validator_recalculates_errors_and_moneyness_statistics(study_copy):
    predictions = pd.read_csv(study_copy / "predictions.csv")
    assert predictions.loc[predictions.assignment == "holdout", "absolute_error"].max() > .1
    predictions.loc[:, ["error", "absolute_error", "spread_scaled_error"]] = 0
    predictions.to_csv(study_copy / "predictions.csv", index=False)
    refresh_prediction_hash_and_summaries(study_copy)
    result = validate(study_copy)
    assert any(f["check"] == "prediction_error_recalculation" for f in result["failures"])
    assert any(f["check"] == "heldout_statistic_recalculation" and "K/S" in f["item"] for f in result["failures"])


def test_report_rejects_changed_frozen_files(study_copy):
    payload = json.loads((study_copy / "groups.json").read_text())
    payload["groups"][0]["reason"] = "unverified new finding"
    write_json(study_copy / "groups.json", payload)
    with pytest.raises(ValueError, match="Frozen artefact changed"):
        report(study_copy)


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "missing_crr_step"])
def test_numerical_inventory_cannot_silently_disappear(study_copy, mutation):
    payload = json.loads((study_copy / "results.json").read_text())
    if mutation == "empty":
        payload["numerical"] = []
    elif mutation == "duplicate":
        payload["numerical"].append(payload["numerical"][0])
    else:
        next(r for r in payload["numerical"] if r["crr_gate"])["crr"].pop()
    write_json(study_copy / "results.json", payload)
    result = validate(study_copy)
    assert result["software_validation"] == "FAIL"
    assert any("protocol_inventory" in f["check"] for f in result["failures"])


def test_parity_bounds_are_independently_reconstructed(study_copy):
    groups = json.loads((study_copy / "groups.json").read_text())
    groups["groups"][0]["parity"]["intersection_lower"] -= 1
    write_json(study_copy / "groups.json", groups)
    payload = json.loads((study_copy / "results.json").read_text())
    payload["files"]["groups.json"] = sha256(study_copy / "groups.json")
    write_json(study_copy / "results.json", payload)
    result = validate(study_copy)
    assert any(f["check"] == "parity_bounds_external_recalculation" for f in result["failures"])


def test_duplicate_and_missing_predictions_are_detected(study_copy):
    pred = pd.read_csv(study_copy / "predictions.csv")
    pred = pd.concat([pred.iloc[1:], pred.iloc[[1]]], ignore_index=True)
    pred.to_csv(study_copy / "predictions.csv", index=False)
    refresh_prediction_hash_and_summaries(study_copy)
    result = validate(study_copy)
    assert any(f["check"] == "duplicate_prediction_key" for f in result["failures"])
    assert any(f["check"] == "complete_prediction_membership" for f in result["failures"])


def test_ingest_reasons_and_rate_availability(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    valid = dict(underlying="SPXW", style="E", settlement_time="PM", quote_date="2022-07-01",
                 expiration="2022-09-30", strike=100, type="call", bid=4.95, ask=5.05, underlying_close=100)
    rows = [dict(valid, underlying="SPY"), dict(valid, settlement_time="AM"), dict(valid, ask=4),
            dict(valid, bid=0), dict(valid, strike=150), dict(valid, expiration="2022-07-05"), valid]
    pd.DataFrame(rows).to_csv(source / "inputs.csv", index=False)
    pd.DataFrame([dict(date="2022-06-30", rate=.02)]).to_csv(tmp_path / "rates.csv", index=False)
    receipt = ingest(source, tmp_path / "rates.csv", tmp_path / "out")
    assert receipt["source_rows"] == 7 and receipt["accepted_rows"] == 1 and receipt["excluded_rows"] == 6
    rejected = pd.read_csv(tmp_path / "out" / "ingest_exclusions.csv")
    assert rejected.reasons.notna().all()
    assert rejected.reasons.str.contains("crossed_quote").any()
    pd.DataFrame([dict(date="2022-07-01", rate=.02)]).to_csv(tmp_path / "rates.csv", index=False)
    receipt = ingest(source, tmp_path / "rates.csv", tmp_path / "out2")
    assert receipt["accepted_rows"] == 0


def test_rate_shift_is_refitted_from_training_only(completed_study):
    groups = json.loads((completed_study / "groups.json").read_text())["groups"]
    assert {g["rate_shift"] for g in groups} == {-.01, 0, .01}
    assert len({g["forward"] for g in groups}) == 3
    assert all(g["training_quote_ids"] == groups[0]["training_quote_ids"] for g in groups)
    assert np.isfinite([g["sigma"] for g in groups]).all()


@pytest.mark.parametrize("mutation", ["crr_nan", "shock_nan", "empty_shocks", "duplicate_shock", "changed_portfolio"])
def test_nonfinite_or_missing_shock_and_crr_evidence_fails(study_copy, mutation):
    payload = json.loads((study_copy / "results.json").read_text())
    if mutation == "crr_nan":
        next(row for row in payload["numerical"] if row["crr_gate"])["crr"][0]["price"] = float("nan")
    elif mutation == "shock_nan":
        payload["shocks"]["scenarios"][0]["full_revaluation_pnl"] = float("nan")
    elif mutation == "empty_shocks":
        payload["shocks"]["scenarios"] = []
    elif mutation == "duplicate_shock":
        payload["shocks"]["scenarios"].append(payload["shocks"]["scenarios"][0])
    else:
        payload["shocks"]["legs"][0]["quantity"] = 200
    # An external malformed JSON producer can emit NaN; the result writer itself refuses it.
    (study_copy / "results.json").write_text(json.dumps(payload), encoding="utf-8")
    result = validate(study_copy)
    assert result["software_validation"] == "FAIL"
    assert any(any(term in failure["check"] for term in ("shock", "crr", "portfolio")) for failure in result["failures"])


def test_assessment_integrity_receipt_prevents_unvalidated_report(study_copy):
    assessment = json.loads((study_copy / "validation.json").read_text())
    assessment["market_validation"] = "APPROVED_WITHOUT_EVIDENCE"
    write_json(study_copy / "validation.json", assessment)
    with pytest.raises(ValueError, match="assessment changed"):
        report(study_copy)


def test_failed_software_audit_still_produces_failure_report(study_copy):
    payload = json.loads((study_copy / "results.json").read_text())
    payload["numerical"] = []
    write_json(study_copy / "results.json", payload)
    assert validate(study_copy)["software_validation"] == "FAIL"
    assert report(study_copy)["figures"] == 0
    document = (study_copy / "VALIDATION_REPORT.md").read_text(encoding="utf-8")
    assert "Software validation: FAIL" in document
    assert "NOT PERFORMED" in document
    assert "protocol_inventory" in document
    assert load_report_receipt(study_copy)["diagnostics_status"] == "NOT_PERFORMED_SOFTWARE_FAILURE"


@pytest.mark.parametrize("mutation", ["edited_report", "missing_figure", "source_inventory", "stale_validation_binding", "diagnostic_assessment_binding"])
def test_report_publication_receipt_rejects_stale_evidence(study_copy, mutation):
    if not (study_copy / "report_receipt.json").exists():
        report(study_copy)
    receipt = load_report_receipt(study_copy)
    if mutation == "edited_report":
        (study_copy / "MANAGEMENT_SUMMARY.md").write_text("new unaudited conclusion", encoding="utf-8")
    elif mutation == "missing_figure":
        receipt["artifacts"].pop(next(name for name in receipt["artifacts"] if name.endswith(".png")))
    elif mutation == "source_inventory":
        receipt["source_hashes"] = {}
    elif mutation == "stale_validation_binding":
        receipt["validation_sha256"] = "old assessment"
    else:
        receipt["diagnostics_validation_sha256"] = "old diagnostics assessment"
    write_json(study_copy / "report_receipt.json", receipt)
    with pytest.raises(ValueError):
        load_report_receipt(study_copy)
