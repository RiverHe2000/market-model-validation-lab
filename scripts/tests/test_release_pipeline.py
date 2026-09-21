"""Offline regressions for stale evidence, interrupted runs and safe publication.

Every input and output is synthetic and lives under pytest's temporary directory.
The tests never run a study, fetch data, or modify the real report gallery.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
VERIFICATION_STEPS = (
    "dependencies", "root-lint", "market-lint", "market-tests",
    "options-lint", "options-tests", "data-tests",
)


def load_script(name: str, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"release_test_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_repository(root: Path) -> None:
    files = {
        "scripts/example.py": "ANSWER = 1\n",
        "scripts/tests/test_example.py": "def test_answer():\n    assert 1 == 1\n",
        "market-risk-validation/src/market_risk/model.py": "SCALE = 1\n",
        "market-risk-validation/tests/test_model.py": "def test_scale():\n    assert 1 == 1\n",
        "market-risk-validation/pyproject.toml": "[project]\nname = 'synthetic-market'\n",
        "option-pricing-validation/src/option_validation/model.py": "SCALE = 1\n",
        "option-pricing-validation/tests/test_model.py": "def test_scale():\n    assert 1 == 1\n",
        "option-pricing-validation/pyproject.toml": "[project]\nname = 'synthetic-options'\n",
        "requirements.lock": "synthetic-dependency==1.0\n",
    }
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def passing_verification(evidence, root: Path) -> dict:
    return {
        "status": "PASS",
        "junit_totals": {"tests": 1, "failures": 0, "errors": 0, "skipped": 0},
        "steps": [{"name": name, "exit_code": 0} for name in VERIFICATION_STEPS],
        "source_sha256": evidence.source_snapshot(root),
        "packages": {"pytest": importlib.metadata.version("pytest")},
    }


@pytest.mark.parametrize("change", ["edit_model", "add_test", "delete_test", "edit_lock"])
def test_verification_fingerprint_rejects_changed_code_or_tests(tmp_path, monkeypatch, change):
    evidence = load_script("evidence", monkeypatch)
    synthetic_repository(tmp_path)
    result = passing_verification(evidence, tmp_path)
    evidence.validate_verification(tmp_path, result)
    if change == "edit_model":
        (tmp_path / "market-risk-validation/src/market_risk/model.py").write_text("SCALE = 2\n")
    elif change == "add_test":
        (tmp_path / "scripts/tests/test_new_regression.py").write_text("def test_new():\n    assert False\n")
    elif change == "delete_test":
        (tmp_path / "option-pricing-validation/tests/test_model.py").unlink()
    else:
        (tmp_path / "requirements.lock").write_text("synthetic-dependency==2.0\n")
    with pytest.raises(ValueError, match="changed"):
        evidence.validate_verification(tmp_path, result)


def test_report_receipt_rejects_changed_displayed_report(tmp_path, monkeypatch):
    evidence = load_script("evidence", monkeypatch)
    report = tmp_path / "report.html"
    report.write_text("<p>Validated conclusion</p>", encoding="utf-8")
    hashes = {"report.html": evidence.digest(report)}
    evidence.validate_artifact_hashes(tmp_path, hashes)
    report.write_text("<p>Unvalidated replacement conclusion</p>", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        evidence.validate_artifact_hashes(tmp_path, hashes)


def test_verification_missing_package_invalidates_previous_pass(tmp_path, monkeypatch):
    verifier = load_script("verify_repo", monkeypatch)
    synthetic_repository(tmp_path)
    output = tmp_path / "artifacts/verification"
    output.mkdir(parents=True)
    summary = output / "summary.json"
    summary.write_text(json.dumps({
        "status": "PASS", "started_utc": "old-run",
        "junit_totals": {"tests": 999, "failures": 0, "errors": 0, "skipped": 0},
    }), encoding="utf-8")
    observed_states = []

    def missing_package(name):
        observed_states.append(json.loads(summary.read_text(encoding="utf-8"))["status"])
        raise importlib.metadata.PackageNotFoundError("synthetic-missing-package")

    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    monkeypatch.setattr(verifier.sys, "argv", ["verify_repo.py", "--output", str(output)])
    monkeypatch.setattr(verifier.importlib.metadata, "version", missing_package)
    monkeypatch.setattr(verifier.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout="", stderr=""))
    assert verifier.main() != 0
    result = json.loads(summary.read_text(encoding="utf-8"))
    assert observed_states and set(observed_states) == {"RUNNING"}
    assert result["status"] == "FAIL"
    assert result["finished_utc"]
    assert result["started_utc"] != "old-run"
    assert result.get("junit_totals", {}).get("tests", 0) != 999
    assert "synthetic-missing-package" in result.get("error", "")


def test_interrupted_verification_records_current_step_and_terminal_status(tmp_path, monkeypatch):
    verifier = load_script("verify_repo", monkeypatch)
    synthetic_repository(tmp_path)
    output = tmp_path / "artifacts/verification"

    def interrupted(*args, **kwargs):
        current = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        assert current["status"] == "RUNNING"
        assert current["steps"][-1]["status"] == "RUNNING"
        raise KeyboardInterrupt

    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    monkeypatch.setattr(verifier.sys, "argv", ["verify_repo.py", "--output", str(output)])
    monkeypatch.setattr(verifier.subprocess, "run", interrupted)
    assert verifier.main() == 130
    result = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert result["status"] == "INTERRUPTED"
    assert result["steps"][-1]["name"] == "dependencies"
    assert result["steps"][-1]["status"] == "INTERRUPTED"
    assert result["finished_utc"]


def write_old_gallery(root: Path) -> dict[str, bytes]:
    gallery = root / "reports"
    (gallery / "figures").mkdir(parents=True)
    (gallery / "index.html").write_text("<p>Old complete gallery</p>", encoding="utf-8")
    (gallery / "figures/old.png").write_bytes(b"synthetic old figure")
    return gallery_bytes(gallery)


def gallery_bytes(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in folder.rglob("*") if path.is_file()}


def test_failed_builder_keeps_previous_complete_gallery(tmp_path, monkeypatch):
    publication = load_script("publication", monkeypatch)
    before = write_old_gallery(tmp_path)

    def failed_builder(staging: Path) -> None:
        assert not staging.resolve().is_relative_to((tmp_path / "reports").resolve())
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "index.html").write_text("<p>Incomplete new gallery</p>", encoding="utf-8")
        raise RuntimeError("synthetic publication failure")

    with pytest.raises(RuntimeError, match="synthetic publication failure"):
        publication.publish_site(tmp_path, failed_builder)
    assert gallery_bytes(tmp_path / "reports") == before


def test_broken_local_link_prevents_replacing_old_gallery(tmp_path, monkeypatch):
    publication = load_script("publication", monkeypatch)
    before = write_old_gallery(tmp_path)

    def broken_builder(staging: Path) -> None:
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "index.html").write_text('<a href="missing-report.html">Report</a>', encoding="utf-8")

    with pytest.raises(ValueError):
        publication.publish_site(tmp_path, broken_builder)
    assert gallery_bytes(tmp_path / "reports") == before


def test_successful_publication_replaces_bundle_without_stale_assets(tmp_path, monkeypatch):
    publication = load_script("publication", monkeypatch)
    write_old_gallery(tmp_path)

    def complete_builder(staging: Path) -> None:
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "index.html").write_text('<a href="summary.html">New summary</a>', encoding="utf-8")
        (staging / "summary.html").write_text('<a href="index.html">Home</a>', encoding="utf-8")

    published = publication.publish_site(tmp_path, complete_builder)
    assert published.resolve() == (tmp_path / "reports").resolve()
    assert set(gallery_bytes(tmp_path / "reports")) == {
        "index.html", "summary.html", "PUBLISH_MANIFEST.json",
    }
    assert "New summary" in (tmp_path / "reports/index.html").read_text(encoding="utf-8")
    receipt = json.loads((published / "PUBLISH_MANIFEST.json").read_text(encoding="utf-8"))
    assert receipt["link_checks"]["local_links_checked"] == 2
    assert receipt["link_checks"]["broken_links"] == []
    assert receipt["files"] == {
        name: publication.digest(published / name) for name in ("index.html", "summary.html")
    }


def test_failed_final_swap_restores_previous_complete_gallery(tmp_path, monkeypatch):
    publication = load_script("publication", monkeypatch)
    before = write_old_gallery(tmp_path)
    original_replace = publication.os.replace

    def fail_new_gallery_swap(source, target):
        if Path(source).name == "staging" and Path(target) == tmp_path / "reports":
            raise OSError("synthetic final-swap failure")
        return original_replace(source, target)

    def complete_builder(staging: Path) -> None:
        (staging / "index.html").write_text("<p>New complete gallery</p>", encoding="utf-8")

    monkeypatch.setattr(publication.os, "replace", fail_new_gallery_swap)
    with pytest.raises(OSError, match="synthetic final-swap failure"):
        publication.publish_site(tmp_path, complete_builder)
    assert gallery_bytes(tmp_path / "reports") == before


def test_interrupted_study_preserves_running_step_and_streamed_log(tmp_path, monkeypatch):
    runner = load_script("run_study", monkeypatch)
    synthetic_repository(tmp_path)
    inputs = tmp_path / "data/processed"
    inputs.mkdir(parents=True)
    (inputs / "fx.csv").write_text("synthetic marker; no study reads this file\n")
    observations = {}

    class InterruptedProcess:
        pid = 31415

        def __init__(self, command, **kwargs):
            self.terminated = False
            self.log = Path(kwargs["stdout"].name)
            current = json.loads((self.log.parent / "execution.json").read_text(encoding="utf-8"))
            observations["initial_step"] = current["steps"][-1]
            observations["initial_status"] = current["status"]
            observations["unbuffered_child"] = kwargs["env"].get("PYTHONUNBUFFERED")
            kwargs["stdout"].write("synthetic progress before interruption\n")
            kwargs["stdout"].flush()

        def wait(self, timeout=None):
            if self.terminated:
                return -15
            observations["log_before_exit"] = self.log.read_text(encoding="utf-8")
            raise KeyboardInterrupt

        def poll(self):
            return -15 if self.terminated else None

        def terminate(self):
            self.terminated = True
            observations["child_terminated"] = True

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.sys, "argv", ["run_study.py", "--project", "market", "--skip-audit"])
    monkeypatch.setattr(runner.subprocess, "Popen", InterruptedProcess)
    assert runner.main() == 130
    record_path = next((tmp_path / "artifacts/private/executions").glob("*/execution.json"))
    result = json.loads(record_path.read_text(encoding="utf-8"))
    assert observations["initial_status"] == "RUNNING"
    assert observations["initial_step"]["name"] == "market-run"
    assert observations["initial_step"]["status"] == "RUNNING"
    assert observations["initial_step"]["arguments"]
    assert observations["unbuffered_child"] == "1"
    assert observations["child_terminated"]
    assert "synthetic progress" in observations["log_before_exit"]
    assert result["status"] == "INTERRUPTED"
    assert result["finished_utc"]
    assert len(result["steps"]) == 1
    step = result["steps"][0]
    assert step["status"] == "INTERRUPTED"
    assert step["exit_code"] == 130
    assert step["finished_utc"]
    assert (record_path.parent / step["log"]).read_text(encoding="utf-8") == observations["log_before_exit"]


def test_study_launch_failure_retains_failed_step(tmp_path, monkeypatch):
    runner = load_script("run_study", monkeypatch)
    synthetic_repository(tmp_path)
    inputs = tmp_path / "data/processed"
    inputs.mkdir(parents=True)
    (inputs / "fx.csv").write_text("synthetic marker\n")

    def failed_launch(*args, **kwargs):
        raise OSError("synthetic process launch failure")

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.sys, "argv", ["run_study.py", "--project", "market", "--skip-audit"])
    monkeypatch.setattr(runner.subprocess, "Popen", failed_launch)
    assert runner.main() == 1
    record_path = next((tmp_path / "artifacts/private/executions").glob("*/execution.json"))
    result = json.loads(record_path.read_text(encoding="utf-8"))
    assert result["status"] == "FAIL"
    assert "synthetic process launch failure" in result["error"]
    assert result["steps"][0]["status"] == "FAIL"
    assert result["steps"][0]["finished_utc"]
