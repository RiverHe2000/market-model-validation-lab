"""Offline-first command line; source acquisition is a separate explicit root script."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="market-risk",
        description="Freeze and independently validate a public-data FX cash-book study",
    )
    commands = result.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Validate canonical or official long ECB CSV")
    ingest.add_argument("--input", required=True, type=Path)
    ingest.add_argument("--output", required=True, type=Path)
    run = commands.add_parser("run", help="Freeze protocol, holdings and daily forecasts")
    run.add_argument("--data", required=True, type=Path)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--window", type=int, default=1000)
    run.add_argument("--ewma-decay", type=float, default=0.94)
    run.add_argument("--ewma-initial-window", type=int, default=250)
    validate = commands.add_parser("validate", help="Independently validate frozen prediction rows")
    validate.add_argument("--predictions", required=True, type=Path)
    validate.add_argument("--output", required=True, type=Path, help="JSON output file")
    validate.add_argument("--manifest", type=Path)
    validate.add_argument("--bootstrap-samples", type=int, default=5000)
    validate.add_argument("--block-length", type=int, default=20)
    validate.add_argument("--seed", type=int, default=42)
    report = commands.add_parser(
        "report", help="Write English Markdown and self-contained static HTML with figures"
    )
    report.add_argument("--predictions", required=True, type=Path)
    report.add_argument("--validation", required=True, type=Path)
    report.add_argument("--output", required=True, type=Path)
    audit = commands.add_parser(
        "audit", help="Synthetic size/power/fault audit, explicitly not market evidence"
    )
    audit.add_argument("--output", required=True, type=Path)
    audit.add_argument("--preset", choices=("fast", "formal"), default="fast")
    verify = commands.add_parser(
        "verify",
        help="Check frozen inputs and evidence receipts without rerunning models or inference",
    )
    verify.add_argument("--predictions", required=True, type=Path)
    verify.add_argument("--validation", required=True, type=Path)
    verify.add_argument("--report", type=Path, help="Optional generated report directory")
    verify.add_argument("--audit", type=Path, help="Optional synthetic audit directory")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "ingest":
            from .data import ingest

            answer = ingest(arguments.input, arguments.output)
        elif arguments.command == "run":
            from .runner import Protocol, run

            answer = run(
                arguments.data,
                arguments.output,
                Protocol(
                    window=arguments.window,
                    ewma_decay=arguments.ewma_decay,
                    ewma_initial_window=arguments.ewma_initial_window,
                ),
            )
            answer = {
                key: answer[key]
                for key in ("forecast_rows", "forecast_dates", "source_sha256", "protocol_sha256")
            }
        elif arguments.command == "validate":
            from .validation import validate_file

            result = validate_file(
                arguments.predictions,
                arguments.output,
                manifest=arguments.manifest,
                samples=arguments.bootstrap_samples,
                block_length=arguments.block_length,
                seed=arguments.seed,
            )
            answer = {
                "development_selected_model": result["development_selected_model"],
                "assessments": {
                    split: {name: value["assessment"] for name, value in content["models"].items()}
                    for split, content in result["splits"].items()
                },
                "output": str(arguments.output.resolve()),
            }
        elif arguments.command == "report":
            from .reporting import report

            answer = report(arguments.predictions, arguments.validation, arguments.output)
        elif arguments.command == "audit":
            from .audit import audit

            result = audit(arguments.output, arguments.preset)
            answer = {
                "kind": result["kind"],
                "preset": result["preset"],
                "output": str(arguments.output.resolve()),
            }
        else:
            from .validation import load_frozen_predictions, load_validation_result

            load_frozen_predictions(arguments.predictions)
            _, receipt = load_validation_result(arguments.validation, arguments.predictions)
            checked = ["frozen inputs", "validation", "descriptive diagnostics"]
            if arguments.report:
                from .reporting import load_report_receipt

                load_report_receipt(arguments.report, arguments.validation, arguments.predictions)
                checked.append("report artifacts and source")
            if arguments.audit:
                from .audit import load_audit_receipt

                load_audit_receipt(arguments.audit)
                checked.append("synthetic audit artifacts and source")
            answer = {
                "status": "consistent",
                "checked": checked,
                "validation_sha256": receipt["validation_sha256"],
                "assurance": "Unsigned artifact consistency, not model approval or a digital signature.",
            }
        print(json.dumps(answer, indent=2, allow_nan=False))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(f"market-risk: {exc}")
        return 2
