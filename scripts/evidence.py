"""Local consistency controls for verification and static report publication."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def source_snapshot(root: Path) -> dict[str, str]:
    files = set((root / "scripts").rglob("*.py"))
    for project in ("market-risk-validation", "option-pricing-validation"):
        for folder in ("src", "tests"):
            files.update((root / project / folder).rglob("*.py"))
        files.add(root / project / "pyproject.toml")
    files.update((root / ".github/workflows").glob("*.yml"))
    files.update(root / name for name in ("pyproject.toml", "requirements.lock"))
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(files) if p.is_file()}


def write_json(path: Path, payload: dict) -> None:
    """Never expose a partially written status document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_verification(root: Path, result: dict) -> None:
    if result.get("status") != "PASS":
        raise ValueError("The latest offline verification did not pass; run scripts/verify_repo.py")
    totals = result.get("junit_totals", {})
    if not totals.get("tests", 0) or any(totals.get(key, 0) for key in ("failures", "errors", "skipped")):
        raise ValueError("Verification must contain executed, passing tests without skipped checks")
    required = {"dependencies", "root-lint", "market-lint", "market-tests",
                "options-lint", "options-tests", "data-tests"}
    steps = result.get("steps", [])
    if {step["name"] for step in steps} != required or any(step.get("exit_code") != 0 for step in steps):
        raise ValueError("Offline verification evidence is incomplete")
    if result.get("source_sha256") != source_snapshot(root):
        raise ValueError("Code or tests changed since offline verification; rerun scripts/verify_repo.py")
    for name, version in result.get("packages", {}).items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError(f"Verified dependency is no longer installed: {name}") from exc
        if actual != version:
            raise ValueError(f"Dependency {name} changed since verification")


def validate_artifact_hashes(folder: Path, hashes: dict[str, str]) -> None:
    for relative, expected in hashes.items():
        target = (folder / relative).resolve()
        if not target.is_relative_to(folder.resolve()) or not target.is_file():
            raise ValueError(f"Report receipt references a missing or outside artifact: {relative}")
        if digest(target) != expected:
            raise ValueError(f"Report artifact changed since generation: {relative}")
