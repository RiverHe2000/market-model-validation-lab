"""Reproduce both studies on local licensed snapshots and record execution evidence.

This command never downloads data implicitly. Run fetch_data.py first. The
per-project entry points remain usable independently. A protocol/source snapshot
is recorded before each invocation, including failed invocations.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from evidence import write_json

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", choices=["market", "options", "all"], default="all")
    parser.add_argument("--bootstrap-samples", type=int, default=5000)
    parser.add_argument("--skip-audit", action="store_true", help="Skip the separate simulated validator audit")
    parser.add_argument("--from-stage", choices=["start", "validate", "report"], default="start",
                        help="Reuse frozen predictions for validation/reporting; never silently resume a failed fit")
    args = parser.parse_args()
    if args.bootstrap_samples < 20:
        parser.error("bootstrap-samples must be >= 20")
    required = []
    if args.project in ("market", "all"):
        required.append(ROOT / "data/processed/fx.csv")
    if args.project in ("options", "all"):
        required.extend([ROOT / "data/processed/rates.csv", ROOT / "data/processed/options"])
    if missing := [str(p.relative_to(ROOT)) for p in required if not p.exists()]:
        parser.error(f"Missing local inputs: {missing}. Run scripts/fetch_data.py first.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    evidence = ROOT / "artifacts/private/executions" / stamp
    evidence.mkdir(parents=True)
    source_files = []
    for project in ("market-risk-validation", "option-pricing-validation"):
        source_files.extend((ROOT / project / "src").rglob("*.py"))
        source_files.extend((ROOT / project / "docs").rglob("*PROTOCOL*"))
        source_files.extend((ROOT / project).glob("*PROTOCOL*"))
        source_files.extend((ROOT / project).glob("pyproject.toml"))
    record = {
        "status": "RUNNING",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "project": args.project,
        "bootstrap_samples": args.bootstrap_samples,
        "from_stage": args.from_stage,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {},
        "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p)
                          for p in sorted(source_files) if p.is_file()},
        "steps": [],
    }

    def persist() -> None:
        write_json(evidence / "execution.json", record)

    def execute(name: str, project: str, arguments: list[str]) -> None:
        command = [sys.executable, "-m", *arguments]
        print(f"Running {name}", flush=True)
        step = {"name": name, "arguments": arguments, "status": "RUNNING", "exit_code": None,
                "started_utc": datetime.now(timezone.utc).isoformat(), "log": f"{name}.log"}
        record["steps"].append(step)
        persist()
        start = time.perf_counter()
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "MPLBACKEND": "Agg"}
        process = None
        log_path = evidence / f"{name}.log"
        try:
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(command, cwd=ROOT / project, env=env, stdout=log,
                                           stderr=subprocess.STDOUT, text=True, encoding="utf-8")
                step["pid"] = process.pid
                persist()
                step["exit_code"] = process.wait()
            step["status"] = "PASS" if step["exit_code"] == 0 else "FAIL"
            if step["exit_code"]:
                print(log_path.read_text(encoding="utf-8", errors="replace")[-6000:], file=sys.stderr)
                raise RuntimeError(f"{name} failed; see {log_path}")
        except KeyboardInterrupt:
            step.update(status="INTERRUPTED", exit_code=130)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise
        except Exception:
            step["status"] = "FAIL"
            raise
        finally:
            step["seconds"] = round(time.perf_counter() - start, 3)
            step["finished_utc"] = datetime.now(timezone.utc).isoformat()
            persist()
        print(f"{name}: PASS ({step['seconds']:.1f}s); log: {log_path.name}", flush=True)

    persist()
    try:
        record["packages"] = {name: importlib.metadata.version(name) for name in (
            "numpy", "scipy", "pandas", "matplotlib", "QuantLib"
        )}
        if args.project in ("market", "all"):
            project = "market-risk-validation"
            base = "output/full-study"
            if args.from_stage == "start":
                execute("market-run", project, ["market_risk", "run", "--data", "../data/processed/fx.csv", "--output", base])
            if args.from_stage != "report":
                execute("market-validate", project, ["market_risk", "validate", "--predictions", f"{base}/predictions.csv",
                        "--output", f"{base}/validation.json", "--bootstrap-samples", str(args.bootstrap_samples)])
            execute("market-report", project, ["market_risk", "report", "--predictions", f"{base}/predictions.csv",
                    "--validation", f"{base}/validation.json", "--output", f"{base}/report"])
            if not args.skip_audit:
                execute("market-validator-audit", project, ["market_risk", "audit", "--preset", "formal", "--output", "output/validator-audit"])
        if args.project in ("options", "all"):
            # The CLI adapter below is deliberately explicit and matches the
            # independently installable option project.
            project = "option-pricing-validation"
            base = "output/full-study"
            if args.from_stage == "start":
                execute("options-ingest", project, ["option_validation", "ingest", "--options-dir", "../data/processed/options",
                        "--rates", "../data/processed/rates.csv", "--output", base])
                execute("options-run", project, ["option_validation", "run", "--output", base])
            if args.from_stage != "report":
                execute("options-validate", project, ["option_validation", "validate", "--output", base])
            execute("options-diagnose", project, ["option_validation", "diagnose", "--output", base])
            execute("options-report", project, ["option_validation", "report", "--output", base])
        record["status"] = "PASS"
    except KeyboardInterrupt:
        record.update(status="INTERRUPTED", error="Execution interrupted; completed stages and partial logs retained")
    except Exception as exc:
        record["status"] = "FAIL"
        record["error"] = str(exc)
        print(str(exc), file=sys.stderr)
    finally:
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        persist()
    print(f"{record['status']}; execution evidence: {evidence}", flush=True)
    return 0 if record["status"] == "PASS" else (130 if record["status"] == "INTERRUPTED" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
