"""Run the offline acceptance checks and retain machine-readable evidence."""

from __future__ import annotations

import argparse
import importlib.metadata
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from evidence import source_snapshot, write_json

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "verification")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 2, "status": "RUNNING",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "packages": {}, "steps": [],
        "junit_totals": {key: 0 for key in ("tests", "failures", "errors", "skipped")},
        "network_note": "Tests use local fixtures and mocked downloads; installation is separate.",
    }
    write_json(out / "summary.json", report)
    # A failed collection must never inherit a previous run's test totals.
    for name in ("market", "options", "data"):
        (out / f"{name}.xml").unlink(missing_ok=True)
    steps = [
        ("dependencies", ROOT, ["-m", "pip", "check"]),
        ("root-lint", ROOT, ["-m", "ruff", "check", "scripts"]),
    ]
    for short, project in (
        ("market", "market-risk-validation"),
        ("options", "option-pricing-validation"),
    ):
        steps.append((f"{short}-lint", ROOT / project, ["-m", "ruff", "check", "src", "tests"]))
        steps.append((
            f"{short}-tests", ROOT / project,
            ["-m", "pytest", "tests", "--import-mode=importlib", "-q",
             f"--junitxml={out / (short + '.xml')}"],
        ))
    steps.append((
        "data-tests", ROOT,
        ["-m", "pytest", "scripts/tests", "--import-mode=importlib", "-q",
         f"--junitxml={out / 'data.xml'}"],
    ))
    try:
        report["source_sha256"] = source_snapshot(ROOT)
        report["packages"] = {name: importlib.metadata.version(name) for name in (
            "numpy", "scipy", "pandas", "matplotlib", "QuantLib", "pytest", "ruff"
        )}
        for name, cwd, arguments in steps:
            step = {"name": name, "working_directory": str(cwd.relative_to(ROOT)) or ".",
                    "arguments": arguments, "status": "RUNNING", "exit_code": None}
            report["steps"].append(step)
            write_json(out / "summary.json", report)
            started = time.perf_counter()
            result = subprocess.run(
                [sys.executable, *arguments], cwd=cwd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False,
            )
            elapsed = time.perf_counter() - started
            (out / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            step.update(exit_code=result.returncode, seconds=round(elapsed, 3),
                        status="PASS" if result.returncode == 0 else "FAIL")
            write_json(out / "summary.json", report)
            print(f"{name}: {step['status']} ({elapsed:.2f}s)", flush=True)
            if result.returncode:
                print((result.stdout + result.stderr)[-12000:], flush=True)
        totals = report["junit_totals"]
        for name in ("market", "options", "data"):
            path = out / f"{name}.xml"
            if not path.is_file():
                raise ValueError(f"Missing fresh test evidence: {path.name}")
            for suite in ET.parse(path).getroot().iter("testsuite"):
                for key in totals:
                    totals[key] += int(suite.get(key, "0"))
        if source_snapshot(ROOT) != report["source_sha256"]:
            raise ValueError("Source files changed while verification was running; rerun on a stable version")
        report["status"] = "PASS" if all(x["exit_code"] == 0 for x in report["steps"]) else "FAIL"
    except KeyboardInterrupt:
        report.update(status="INTERRUPTED", error="Verification interrupted")
    except Exception as exc:
        report.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
        print(report["error"], file=sys.stderr)
    finally:
        if report["steps"] and report["steps"][-1]["status"] == "RUNNING":
            report["steps"][-1]["status"] = report["status"]
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(out / "summary.json", report)
    print(f"{report['status']}: {report['junit_totals']}", flush=True)
    return 0 if report["status"] == "PASS" else (130 if report["status"] == "INTERRUPTED" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
