from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from market_risk.cli import main
from market_risk.data import sha256_file
from market_risk.reporting import load_report_receipt, report
from market_risk.runner import Protocol, run
from market_risk.validation import (
    ValidationError,
    check_contract,
    load_frozen_predictions,
    load_validation_result,
    validate_file,
)


@pytest.fixture
def frozen(fx_file, tmp_path):
    protocol = Protocol(window=100, ewma_initial_window=40)
    output = tmp_path / "study"
    manifest = run(fx_file, output, protocol)
    return output, manifest, protocol


def test_holdings_and_realized_pnl_are_fixed_and_exact(fx_file, frozen):
    output, manifest, _ = frozen
    frame, _ = load_frozen_predictions(output / "predictions.csv")
    prices = pd.read_csv(fx_file).set_index("date")
    holdings = manifest["holdings"]
    assert holdings["inception_date"] == "2004-01-01"
    assert holdings["first_forecast_date"] == "2004-01-02"
    # Synthetic fixtures intentionally use weekday rather than TARGET calendars.
    units = pd.Series(holdings["foreign_units"])
    first = frame.iloc[0]
    expected = (units * (1 / prices.loc[first["date"]] - 1 / prices.loc[first["as_of"]])).sum()
    assert first["pnl_eur"] == pytest.approx(expected, abs=1e-8)
    assert len(frame["model"].unique()) == 3


def test_future_price_mutation_cannot_change_earlier_predictions(fx_file, frozen, tmp_path):
    output, _, protocol = frozen
    before = pd.read_csv(output / "predictions.csv")
    data = pd.read_csv(fx_file)
    after_cut = data["date"] >= "2008-01-02"
    data.loc[after_cut, "CHF"] *= 1.05
    changed = tmp_path / "future_modified.csv"
    data.to_csv(changed, index=False, float_format="%.17g")
    later = tmp_path / "later"
    run(changed, later, protocol)
    after = pd.read_csv(later / "predictions.csv")
    numerical = ["var_975_eur", "es_975_eur", "var_99_eur", "loss_eur"]
    mask = before["date"] < "2008-01-02"
    np.testing.assert_allclose(
        before.loc[mask, numerical], after.loc[mask, numerical], rtol=1e-12, atol=1e-7
    )


def test_whole_book_scaling_scales_every_risk(fx_file, frozen, tmp_path):
    output, _, protocol = frozen
    double = tmp_path / "double"
    run(fx_file, double, replace(protocol, eur_per_currency_at_inception=2_000_000))
    base_frame = pd.read_csv(output / "predictions.csv")
    double_frame = pd.read_csv(double / "predictions.csv")
    values = ["var_975_eur", "es_975_eur", "var_99_eur", "loss_eur"]
    np.testing.assert_allclose(double_frame[values], 2 * base_frame[values], rtol=1e-12, atol=1e-7)


def test_changed_prediction_bytes_are_rejected(frozen):
    output, _, _ = frozen
    path = output / "predictions.csv"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="SHA-256"):
        load_frozen_predictions(path)


def test_wrong_split_rejected_even_if_csv_checksum_is_recomputed(frozen):
    output, manifest, _ = frozen
    path = output / "predictions.csv"
    frame = pd.read_csv(path)
    frame.loc[frame["split"] == "test", "split"] = "development"
    frame.to_csv(path, index=False, float_format="%.17g")
    manifest["predictions_sha256"] = sha256_file(path)
    (output / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValidationError, match="split"):
        load_frozen_predictions(path)


def test_same_day_information_leak_is_rejected(frozen):
    output, _, _ = frozen
    frame = pd.read_csv(output / "predictions.csv")
    frame["as_of"] = frame["date"]
    frame["history_end"] = frame["date"]
    with pytest.raises(ValidationError, match="strictly before"):
        check_contract(frame)


def _rewrite_prediction_receipt(output, manifest, frame):
    path = output / "predictions.csv"
    frame.to_csv(path, index=False, float_format="%.17g")
    manifest["predictions_sha256"] = sha256_file(path)
    (output / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_common_hundredfold_pnl_bug_is_rejected_independently(frozen):
    output, manifest, _ = frozen
    frame = pd.read_csv(output / "predictions.csv")
    frame[["pnl_eur", "loss_eur"]] *= 100
    # Simulate a buggy producer that consistently freezes its wrong P&L: source
    # quotes and legitimate holdings remain unchanged, and every model agrees.
    path = _rewrite_prediction_receipt(output, manifest, frame)
    with pytest.raises(ValidationError, match="independent source-price cash repricing"):
        load_frozen_predictions(path)


def test_each_initial_cash_allocation_is_rebuilt_from_source(frozen):
    output, manifest, _ = frozen
    manifest["holdings"]["foreign_units"]["JPY"] *= 100
    (output / "holdings.json").write_text(json.dumps(manifest["holdings"]), encoding="utf-8")
    manifest["holdings_sha256"] = sha256_file(output / "holdings.json")
    (output / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValidationError, match="each initial EUR cash allocation"):
        load_frozen_predictions(output / "predictions.csv")


def test_prediction_notional_is_bound_to_initial_cash(frozen):
    output, manifest, _ = frozen
    frame = pd.read_csv(output / "predictions.csv")
    frame["initial_gross_eur"] *= 100
    path = _rewrite_prediction_receipt(output, manifest, frame)
    with pytest.raises(ValidationError, match="notional does not match"):
        load_frozen_predictions(path)


def test_a_single_model_cannot_change_its_historical_window(frozen):
    output, manifest, _ = frozen
    frame = pd.read_csv(output / "predictions.csv")
    mask = frame["model"].eq("ewma_gaussian")
    frame.loc[mask, "history_start"] = frame.loc[mask, "as_of"]
    path = _rewrite_prediction_receipt(output, manifest, frame)
    with pytest.raises(ValidationError, match="history window"):
        load_frozen_predictions(path)


def test_report_rejects_modified_assessment_and_score(frozen):
    output, _, _ = frozen
    predictions, validation_path = output / "predictions.csv", output / "validation.json"
    result = validate_file(predictions, validation_path, samples=29)
    selected = result["development_selected_model"]
    result["splits"]["test"]["models"][selected]["assessment"] = "UNVALIDATED_INJECTED_APPROVAL"
    result["splits"]["test"]["models"][selected]["scores"]["fz0_mean"] = -9999
    validation_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValidationError, match="receipt hash mismatch"):
        report(predictions, validation_path, output / "report")


def test_report_requires_a_validation_receipt(frozen):
    output, _, _ = frozen
    predictions, validation_path = output / "predictions.csv", output / "validation.json"
    validate_file(predictions, validation_path, samples=29)
    validation_path.with_suffix(".receipt.json").unlink()
    with pytest.raises(ValidationError, match="receipt missing"):
        report(predictions, validation_path, output / "report")


def test_report_detects_postvalidation_manifest_change(frozen):
    output, manifest, _ = frozen
    predictions, validation_path = output / "predictions.csv", output / "validation.json"
    validate_file(predictions, validation_path, samples=29)
    manifest["frozen_at_utc"] = "changed after validation"
    (output / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValidationError, match="Run manifest changed"):
        report(predictions, validation_path, output / "report")


def test_report_detects_changed_validator_source(frozen, monkeypatch):
    from market_risk import validation

    output, _, _ = frozen
    predictions, validation_path = output / "predictions.csv", output / "validation.json"
    validate_file(predictions, validation_path, samples=29)
    original = validation.validator_source_identity()
    altered = {**original, "validation.py": "f" * 64}
    monkeypatch.setattr(validation, "validator_source_identity", lambda: altered)
    with pytest.raises(ValidationError, match="Validator source changed"):
        report(predictions, validation_path, output / "report")


def test_small_offline_validation_and_complete_report(frozen):
    output, _, _ = frozen
    predictions = output / "predictions.csv"
    result = validate_file(predictions, output / "validation.json", samples=39, seed=42)
    assert result["development_selected_model"] in {"historical", "ewma_gaussian", "ewma_fhs"}
    assert set(result["splits"]) == {"development", "test"}
    artifact = report(predictions, output / "validation.json", output / "report")
    text = (output / "report" / "report.md").read_text(encoding="utf-8")
    page = (output / "report" / "report.html").read_text(encoding="utf-8")
    assert "non-rejected" in text
    assert "data:image/png;base64," in page
    assert "管理摘要" in page
    assert "<script" not in page
    assert str(output) not in text
    assert artifact["html"].endswith("report.html")
    assert "Post-review calendar-year diagnostics" in text
    receipt = load_report_receipt(output / "report", output / "validation.json", predictions)
    assert "figures/event_responses.png" in receipt["artifact_sha256"]
    assert "data/currency_hpl.csv" in receipt["artifact_sha256"]
    assert (
        main(
            [
                "verify",
                "--predictions",
                str(predictions),
                "--validation",
                str(output / "validation.json"),
                "--report",
                str(output / "report"),
            ]
        )
        == 0
    )


def test_diagnostic_sidecar_cannot_be_edited_after_validation(frozen):
    output, _, _ = frozen
    predictions, validation_path = output / "predictions.csv", output / "validation.json"
    validate_file(predictions, validation_path, samples=29)
    path = validation_path.with_suffix(".diagnostics.json")
    diagnostics = json.loads(path.read_text(encoding="utf-8"))
    diagnostics["annual"][0]["exceptions_99"] = 0
    path.write_text(json.dumps(diagnostics), encoding="utf-8")
    with pytest.raises(ValidationError, match="diagnostics changed"):
        load_validation_result(validation_path, predictions)


@pytest.mark.parametrize(
    "artifact", ["report.html", "data/annual.csv", "figures/event_responses.png"]
)
def test_report_receipt_rejects_stale_or_altered_display(frozen, artifact):
    output, _, _ = frozen
    predictions, validation_path = output / "predictions.csv", output / "validation.json"
    validate_file(predictions, validation_path, samples=29)
    report(predictions, validation_path, output / "report")
    target = output / "report" / artifact
    target.write_bytes(target.read_bytes() + b"altered-display")
    with pytest.raises(ValidationError, match="Report artifact changed"):
        load_report_receipt(output / "report", validation_path, predictions)


def test_report_receipt_rejects_stale_generating_code(frozen, monkeypatch):
    from market_risk import reporting

    output, _, _ = frozen
    predictions, validation_path = output / "predictions.csv", output / "validation.json"
    validate_file(predictions, validation_path, samples=29)
    report(predictions, validation_path, output / "report")
    original = reporting.sha256_file
    monkeypatch.setattr(
        reporting,
        "sha256_file",
        lambda path: "f" * 64 if path.name == "reporting.py" else original(path),
    )
    with pytest.raises(ValidationError, match="Report source changed"):
        load_report_receipt(output / "report", validation_path, predictions)


def test_cli_missing_input_returns_clear_nonzero(tmp_path):
    assert (
        main(
            [
                "ingest",
                "--input",
                str(tmp_path / "missing.csv"),
                "--output",
                str(tmp_path / "canonical.csv"),
            ]
        )
        == 2
    )
