"""Stage and validate a complete local gallery before replacing the previous one."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

from evidence import digest, write_json


def validate_links(root: Path, staging: Path) -> dict:
    missing = []
    checked = 0
    target = (root / "reports").resolve()

    class Links(HTMLParser):
        def __init__(self, file: Path):
            super().__init__()
            self.logical = target / file.relative_to(staging)

        def handle_starttag(self, tag, attrs):
            nonlocal checked
            for key, value in attrs:
                if key not in ("href", "src") or not value:
                    continue
                url = urlsplit(value)
                if url.scheme or url.netloc or not url.path:
                    continue
                logical = (self.logical.parent / unquote(url.path)).resolve()
                if not logical.is_relative_to(root.resolve()):
                    missing.append(value)
                    continue
                actual = staging / logical.relative_to(target) if logical.is_relative_to(target) else logical
                checked += 1
                if not actual.exists():
                    missing.append(f"{self.logical.relative_to(target)}: {value}")

    pages = list(staging.rglob("*.html"))
    for file in pages:
        Links(file).feed(file.read_text(encoding="utf-8"))
    if missing:
        raise ValueError(f"Gallery contains broken or outside local links: {missing}")
    return {"html_pages": len(pages), "local_links_checked": checked, "broken_links": []}


def publish_site(root: Path, builder: Callable[[Path], None]) -> Path:
    root = root.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    private = root / "artifacts/private/publications" / stamp
    staging, backup, target = private / "staging", private / "previous", root / "reports"
    # All directory moves remain inside this explicitly supplied project root.
    for path in (staging, backup, target):
        if not path.resolve().is_relative_to(root):
            raise ValueError("Publication paths must remain within the project")
    staging.mkdir(parents=True)
    builder(staging)
    if not (staging / "index.html").is_file():
        raise ValueError("A complete gallery requires index.html")
    # The gallery may link to its receipt. Its final hash inventory excludes
    # the receipt itself, avoiding a self-referential digest.
    write_json(staging / "PUBLISH_MANIFEST.json", {"kind": "pending_local_bundle"})
    links = validate_links(root, staging)
    manifest = {
        "kind": "local_static_report_bundle", "generated_utc": datetime.now(timezone.utc).isoformat(),
        "assurance": "Unsigned consistency receipt; not a digital signature or external publication.",
        "link_checks": links,
        "files": {p.relative_to(staging).as_posix(): digest(p) for p in sorted(staging.rglob("*"))
                  if p.is_file() and p != staging / "PUBLISH_MANIFEST.json"},
    }
    write_json(staging / "PUBLISH_MANIFEST.json", manifest)
    had_previous = target.exists()
    if had_previous:
        os.replace(target, backup)
    try:
        os.replace(staging, target)
    except BaseException:
        if had_previous:
            os.replace(backup, target)
        raise
    return target
