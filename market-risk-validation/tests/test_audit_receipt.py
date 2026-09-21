from __future__ import annotations

import shutil

import pytest

from market_risk import audit as audit_module
from market_risk.audit import audit, load_audit_receipt
from market_risk.validation import ValidationError


@pytest.fixture(scope="module")
def synthetic_audit(tmp_path_factory):
    path = tmp_path_factory.mktemp("synthetic-audit")
    audit(path, "fast")
    return path


def test_audit_receipt_binds_current_source_and_synthetic_outputs(synthetic_audit):
    receipt = load_audit_receipt(synthetic_audit)
    assert receipt["preset"] == "fast"
    assert set(receipt["artifact_sha256"]) == {"audit.json", "audit.md"}
    assert {"audit.py", "validation.py", "diagnostics.py"}.issubset(receipt["source_hashes"])


@pytest.mark.parametrize("artifact", ["audit.json", "audit.md"])
def test_edited_synthetic_evidence_is_rejected(synthetic_audit, tmp_path, artifact):
    copied = tmp_path / "audit"
    shutil.copytree(synthetic_audit, copied)
    path = copied / artifact
    path.write_bytes(path.read_bytes() + b"edited")
    with pytest.raises(ValidationError, match="Audit artifact changed"):
        load_audit_receipt(copied)


def test_changed_audit_code_requires_actual_rerun(synthetic_audit, monkeypatch):
    original = audit_module.sha256_file
    monkeypatch.setattr(
        audit_module,
        "sha256_file",
        lambda path: "f" * 64 if str(path).endswith("audit.py") else original(path),
    )
    with pytest.raises(ValidationError, match="Audit source changed"):
        load_audit_receipt(synthetic_audit)
