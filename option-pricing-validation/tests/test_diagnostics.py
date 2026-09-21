import json

import pandas as pd
import pytest

from option_validation.data import sha256, write_json
from option_validation.diagnostics import compute_diagnostics, read_heldout
from option_validation.diagnostics_validation import checked_diagnostics, validate_diagnostics


@pytest.fixture
def descriptive_fixture(tmp_path):
    rows = []
    compatible, inconsistent = "PARITY_COMPATIBLE_DAILY_PROXY", "EXPLORATORY_INCONSISTENT_QUOTES"
    for index in range(4):
        for shift in (-.01, 0.0, .01):
            error = (1 if index < 3 else 9) if shift == 0 else ((2 if index < 3 else 5) if shift < 0 else (.05 if index < 3 else 9))
            status = (compatible if index < 3 else inconsistent) if shift == 0 else (inconsistent if index < 3 else compatible)
            rows.append(dict(quote_id=f"fixture-{index}", quote_date="2022-09-01" if index < 3 else "2022-09-02",
                expiration="2022-10-31", kind="call" if index in (0, 2) else "put",
                moneyness=(.9, 1, 1.1, .9)[index], split="temporal_test", group_status=status,
                assignment="holdout", rate_shift=shift, bid=9.9, ask=10.1, mid=10., model_price=10 + error))
    pd.DataFrame(rows).to_csv(tmp_path / "predictions.csv", index=False)
    # Minimal audit-input fixtures: these test descriptive reconstruction, not
    # pricing validation or a real data run.
    for name in ("results.json", "groups.json", "validation.json", "validation_receipt.json"):
        write_json(tmp_path / name, {"synthetic_test_fixture": True})
    return tmp_path


def compute_and_save(output):
    hashes = {name: sha256(output / name) for name in ("results.json", "predictions.csv", "groups.json", "validation.json", "validation_receipt.json")}
    result = compute_diagnostics(read_heldout(output), hashes)
    write_json(output / "diagnostics.json", result)
    return result


def test_fixed_membership_and_baseline_strata_avoid_composition_confounding(descriptive_fixture):
    result = compute_and_save(descriptive_fixture)
    assert result["population"]["common_quotes"] == 4
    all_minus = next(r for r in result["matched_rate"] if r["base_group_status"] == "ALL_BASE_STATUSES" and r["rate_shift"] == -.01)
    assert all_minus["delta_mae_points"] == pytest.approx(-.25)
    assert all_minus["equal_date_delta_mae_points"] == pytest.approx(-1.5)
    base_compatible = next(r for r in result["matched_rate"] if r["base_group_status"] == "PARITY_COMPATIBLE_DAILY_PROXY" and r["rate_shift"] == -.01)
    assert base_compatible["common_quotes"] == 3
    assert base_compatible["shift_mae_points"] == pytest.approx(2)  # Not 5 from the shifted compatible group.
    assert base_compatible["delta_mae_points"] == pytest.approx(1)
    assert any(r["base_group_status"] != r["shifted_group_status"] for r in result["status_transitions"])
    assert validate_diagnostics(descriptive_fixture)["status"] == "PASS"


def test_equal_date_and_quote_weighted_coverage_are_distinct(descriptive_fixture):
    result = compute_and_save(descriptive_fixture)
    plus = next(r for r in result["matched_rate"] if r["base_group_status"] == "ALL_BASE_STATUSES" and r["rate_shift"] == .01)
    assert plus["delta_coverage_pp"] == pytest.approx(75)
    assert plus["equal_date_delta_coverage_pp"] == pytest.approx(50)


def test_missing_scenario_is_explicit_and_uses_same_common_cohort(descriptive_fixture):
    path = descriptive_fixture / "predictions.csv"
    frame = pd.read_csv(path)
    frame = frame[~((frame.quote_id == "fixture-3") & (frame.rate_shift == -.01))]
    frame.to_csv(path, index=False)
    result = compute_and_save(descriptive_fixture)
    assert result["population"]["excluded_base_quotes"] == 1
    assert result["population"]["common_quotes"] == 3
    assert result["pair_exclusions"] == [dict(quote_id="fixture-3", quote_date="2022-09-02", expiration="2022-10-31", missing_rate_shifts=[-.01])]
    all_rows = [r for r in result["matched_rate"] if r["base_group_status"] == "ALL_BASE_STATUSES"]
    assert {r["common_quotes"] for r in all_rows} == {3}
    assert validate_diagnostics(descriptive_fixture)["status"] == "PASS"


@pytest.mark.parametrize("mutation", ["alternative_status_cohort", "fake_equal_date", "drop_daily_row", "fake_population"])
def test_independent_audit_rejects_misleading_descriptive_output(descriptive_fixture, mutation):
    result = compute_and_save(descriptive_fixture)
    if mutation == "alternative_status_cohort":
        row = next(r for r in result["matched_rate"] if r["base_group_status"] == "PARITY_COMPATIBLE_DAILY_PROXY" and r["rate_shift"] == -.01)
        row["shift_mae_points"] = 5
    elif mutation == "fake_equal_date":
        row = next(r for r in result["matched_rate"] if r["base_group_status"] == "ALL_BASE_STATUSES" and r["rate_shift"] == -.01)
        row["equal_date_delta_mae_points"] = row["delta_mae_points"]
    elif mutation == "drop_daily_row":
        result["daily_paired"].pop()
    else:
        result["population"]["common_quotes"] = 100
    write_json(descriptive_fixture / "diagnostics.json", result)
    assert validate_diagnostics(descriptive_fixture)["status"] == "FAIL"


def test_scenario_source_mismatch_is_not_silently_joined(descriptive_fixture):
    path = descriptive_fixture / "predictions.csv"
    frame = pd.read_csv(path)
    frame.loc[(frame.quote_id == "fixture-0") & (frame.rate_shift == .01), "mid"] = 99
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="changed the observed quote"):
        compute_and_save(descriptive_fixture)


def test_diagnostic_receipt_rejects_tampering(descriptive_fixture):
    compute_and_save(descriptive_fixture)
    assert validate_diagnostics(descriptive_fixture)["status"] == "PASS"
    assert checked_diagnostics(descriptive_fixture)["analysis_kind"] == "post_hoc_descriptive"
    actual = json.loads((descriptive_fixture / "diagnostics.json").read_text())
    actual["population"]["common_quotes"] = 1000
    write_json(descriptive_fixture / "diagnostics.json", actual)
    with pytest.raises(ValueError, match="changed after its receipt"):
        checked_diagnostics(descriptive_fixture)


@pytest.mark.parametrize("mutation", ["missing_sources", "missing_inputs", "assessment_payload", "assessment_inputs"])
def test_diagnostic_receipt_requires_complete_binding(descriptive_fixture, mutation):
    compute_and_save(descriptive_fixture)
    validate_diagnostics(descriptive_fixture)
    path = descriptive_fixture / "diagnostics_validation_receipt.json"
    receipt = json.loads(path.read_text())
    if mutation == "missing_sources":
        receipt["source_hashes"] = {}
    elif mutation == "missing_inputs":
        payload = json.loads((descriptive_fixture / "diagnostics.json").read_text())
        payload["input_hashes"] = {}
        write_json(descriptive_fixture / "diagnostics.json", payload)
        receipt["diagnostics_sha256"] = sha256(descriptive_fixture / "diagnostics.json")
    else:
        assessment = json.loads((descriptive_fixture / "diagnostics_validation.json").read_text())
        if mutation == "assessment_payload":
            assessment["diagnostics_sha256"] = "different_payload"
        else:
            assessment["input_hashes"] = {}
        write_json(descriptive_fixture / "diagnostics_validation.json", assessment)
        receipt["validation_sha256"] = sha256(descriptive_fixture / "diagnostics_validation.json")
    write_json(path, receipt)
    with pytest.raises(ValueError):
        checked_diagnostics(descriptive_fixture)
