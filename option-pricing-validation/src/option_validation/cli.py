"""Explicit stages: ingest, run, independent validate, post-hoc diagnose, report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from option_validation.data import ingest
from option_validation.diagnostics import generate_diagnostics
from option_validation.diagnostics_validation import validate_diagnostics
from option_validation.report import report
from option_validation.study import run
from option_validation.validation import validate


def main(argv: list[str] | None = None) -> int:
    project = Path(__file__).resolve().parents[2]
    repository = project.parent
    parser = argparse.ArgumentParser(description="European index option validation; no trading or market-calibration claim")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("ingest", "run", "validate", "diagnose", "report"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--output", type=Path, default=project / "output" / "full-study")
        if command in {"ingest", "run"}:
            command_parser.add_argument("--options-dir", type=Path, default=repository / "data" / "processed" / "options")
            command_parser.add_argument("--rates", type=Path, default=repository / "data" / "processed" / "rates.csv")
        if command == "run":
            command_parser.add_argument("--numerical-only", action="store_true")
            command_parser.add_argument("--reingest", action="store_true", help="Explicitly rebuild input snapshot before computing results")
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            result = ingest(args.options_dir, args.rates, args.output)
            print(json.dumps({k: result[k] for k in ("source_rows", "accepted_rows", "excluded_rows")}, indent=2))
        elif args.command == "run":
            if not args.numerical_only and (args.reingest or not (args.output / "ingested_quotes.csv").exists()):
                ingest(args.options_dir, args.rates, args.output)
            result = run(args.output, numerical_only=args.numerical_only)
            print(json.dumps(dict(numerical_cases=len(result["numerical"]), market=result["market"]), indent=2))
        elif args.command == "validate":
            result = validate(args.output)
            print(json.dumps(dict(software_validation=result["software_validation"], failures=len(result["failures"]),
                                  numerical_cases=result.get("numerical_cases_checked", 0), market=result["market_checks"]), indent=2))
            return 0 if result["software_validation"] == "PASS" else 1
        elif args.command == "diagnose":
            generated = generate_diagnostics(args.output)
            assessment = validate_diagnostics(args.output)
            print(json.dumps(dict(analysis_kind=generated["analysis_kind"], population=generated["population"],
                                  validation=assessment["status"], failures=len(assessment["failures"])), indent=2))
            return 0 if assessment["status"] == "PASS" else 1
        else:
            print(json.dumps(report(args.output), indent=2))
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(2, f"{exc}\n")
    return 0
