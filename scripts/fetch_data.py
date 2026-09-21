"""Fetch public research data, retaining source bytes and local provenance.

No vendor Python is executed. Raw and contract-level files are local-only.
Run with the project Python environment; dependencies: requests, pandas, numpy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd
import requests

FX_SYMBOLS = ["USD", "GBP", "JPY", "CHF", "AUD"]
FX_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
RATES_URL = (
    "https://fred.stlouisfed.org/graph/fredgraph.csv"
    "?id=DGS3MO&cosd=2022-06-01&coed=2022-12-31"
)
OPTIONS_URL = "https://historicaldata.net/file/options_sample_2022H2.zip"
OPTION_COLUMNS = [
    "contract", "underlying", "expiration", "type", "strike", "style",
    "quote_date", "bid", "bid_size", "ask", "ask_size", "quote_time",
    "volume", "open_interest", "open", "high", "low", "close", "trade_vwap",
    "transactions", "multileg_volume", "active_minutes", "last_trade_date",
    "underlying_close", "settlement_time", "iv_bid", "iv_ask", "iv", "iv_flag",
    "delta", "gamma", "theta", "vega", "rho",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def fetch(url: str, target: Path, *, attempts: int = 3) -> dict:
    """Download atomically; reuse only a hash-verified cache, resume using validators.

    SHA256 records are local integrity evidence, not an assertion of publisher
    authentication. Options CSV hashes are additionally checked against the
    publisher's manifest. Partial files never appear as completed inputs.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = target.with_suffix(target.suffix + ".source.json")
    if target.exists():
        if not metadata_path.exists():
            raise ValueError(f"Unverified cache has no source metadata: {target}")
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        if meta["url"] != url or meta["sha256"] != sha256(target):
            raise ValueError(f"Cached source URL/hash mismatch: {target}")
        if meta["bytes"] != target.stat().st_size:
            raise ValueError(f"Cached byte count mismatch: {target}")
        print(f"Verified cached {target.name} ({meta['bytes']:,} bytes)", flush=True)
        return meta
    partial = target.with_suffix(target.suffix + ".part")
    partial_meta_path = partial.with_suffix(partial.suffix + ".json")
    for attempt in range(attempts):
        prior = json.loads(partial_meta_path.read_text()) if partial_meta_path.exists() else {}
        offset = partial.stat().st_size if partial.exists() else 0
        validator = prior.get("etag") or prior.get("last_modified")
        headers = {"Accept-Encoding": "identity"}
        if offset and validator and prior.get("url") == url:
            headers.update({"Range": f"bytes={offset}-", "If-Range": validator})
        else:
            offset = 0
        try:
            with requests.get(url, headers=headers, timeout=(20, 90), stream=True) as response:
                response.raise_for_status()
                if response.status_code == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if not match or int(match[1]) != offset:
                        raise ValueError("Invalid Content-Range when resuming download")
                    expected_total = int(match[3])
                    new_validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
                    if offset and new_validator != validator:
                        raise ValueError("Source changed while resuming; partial file retained for inspection")
                else:
                    offset = 0  # If-Range mismatch or no Range support: start a new response.
                    length = response.headers.get("Content-Length")
                    expected_total = int(length) if length else None
                transfer = {
                    "url": url, "resolved_url": response.url,
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "expected_bytes": expected_total, "started_utc": utc_now(),
                }
                write_json(partial_meta_path, transfer)
                count = offset
                next_progress = count + 32 * 1024 * 1024
                with partial.open("ab" if offset else "wb") as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            stream.write(chunk)
                            count += len(chunk)
                            if count >= next_progress:
                                print(f"Downloading {target.name}: {count:,} bytes", flush=True)
                                next_progress = count + 32 * 1024 * 1024
                if expected_total is not None and count != expected_total:
                    raise ValueError(f"Truncated transfer: {count} of {expected_total} bytes")
                if count == 0:
                    raise ValueError("Empty download")
                meta = {**transfer, "fetched_utc": utc_now(), "bytes": count, "sha256": sha256(partial)}
                write_json(metadata_path, meta)
                partial.replace(target)
                partial_meta_path.unlink(missing_ok=True)
                print(f"Downloaded {target.name} ({count:,} bytes, SHA256 {meta['sha256']})", flush=True)
                return meta
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(1 + attempt)
    raise RuntimeError("Download did not complete")


def require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = set(columns).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")


def validate_dates(values: pd.Series, start: str, end: str) -> pd.Series:
    if not values.astype("string").str.fullmatch(r"\d{4}-\d{2}-\d{2}").fillna(False).all():
        raise ValueError("Dates must be nonmissing ISO YYYY-MM-DD strings")
    parsed = pd.to_datetime(values, format="%Y-%m-%d", errors="raise")
    if parsed.isna().any() or not parsed.between(start, end).all():
        raise ValueError(f"Missing or out-of-window dates ({start} to {end})")
    return parsed


def atomic_csv(frame: pd.DataFrame, path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".csv.tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    temporary.replace(path)
    return {"path": path.name, "sha256": sha256(path), "bytes": path.stat().st_size,
            "rows": len(frame), "columns": list(frame.columns)}


def process_fx(raw: Path, out: Path) -> dict:
    frame = pd.read_csv(raw, keep_default_na=True)
    required = ["TIME_PERIOD", "CURRENCY", "CURRENCY_DENOM", "OBS_VALUE", "FREQ", "EXR_TYPE", "EXR_SUFFIX"]
    require_columns(frame, required)
    if set(frame.CURRENCY.unique()) != set(FX_SYMBOLS):
        raise ValueError("FX source does not contain exactly the five requested currencies")
    for column, expected in [("CURRENCY_DENOM", "EUR"), ("FREQ", "D"), ("EXR_TYPE", "SP00"), ("EXR_SUFFIX", "A")]:
        if not frame[column].eq(expected).all():
            raise ValueError(f"Unexpected FX convention in {column}")
    validate_dates(frame.TIME_PERIOD, "1999-01-01", "2025-12-31")
    frame["OBS_VALUE"] = pd.to_numeric(frame.OBS_VALUE, errors="raise")
    if not (np.isfinite(frame.OBS_VALUE) & (frame.OBS_VALUE > 0)).all():
        raise ValueError("FX values must be finite and strictly positive")
    if frame.duplicated(["TIME_PERIOD", "CURRENCY"]).any():
        raise ValueError("Duplicate FX date/currency keys")
    canonical = frame.pivot(index="TIME_PERIOD", columns="CURRENCY", values="OBS_VALUE")[FX_SYMBOLS]
    canonical = canonical.sort_index().rename_axis("date").reset_index()
    if canonical[FX_SYMBOLS].isna().any().any():
        raise ValueError("FX dates are not aligned; missing observations are not forward-filled")
    if len(canonical) < 6500 or canonical.date.iloc[0] != "1999-01-04" or canonical.date.iloc[-1] != "2025-12-31":
        raise ValueError("Incomplete expected 1999-2025 FX research window")
    return {**atomic_csv(canonical, out), "start": canonical.date.iloc[0], "end": canonical.date.iloc[-1],
            "long_raw_rows": len(frame), "missing_by_currency": canonical[FX_SYMBOLS].isna().sum().to_dict()}


def process_rates(raw: Path, out: Path) -> dict:
    frame = pd.read_csv(raw, na_values=["."])
    require_columns(frame, ["observation_date", "DGS3MO"])
    validate_dates(frame.observation_date, "2022-06-01", "2022-12-31")
    if frame.observation_date.duplicated().any():
        raise ValueError("Duplicate rate dates")
    numeric = pd.to_numeric(frame.DGS3MO, errors="raise")
    available = numeric.notna()
    if not np.isfinite(numeric[available]).all() or not numeric[available].between(-10, 50).all():
        raise ValueError("Invalid DGS3MO percent yield")
    canonical = pd.DataFrame({"date": frame.observation_date[available], "rate": numeric[available] / 100}).sort_values("date")
    if len(canonical) < 130 or canonical.date.iloc[0] > "2022-06-03" or canonical.date.iloc[-1] < "2022-12-29":
        raise ValueError("Incomplete June-December 2022 rates window")
    return {**atomic_csv(canonical, out), "start": canonical.date.iloc[0], "end": canonical.date.iloc[-1],
            "missing_source_dates": frame.loc[~available, "observation_date"].tolist()}


def validate_zip_members(archive: zipfile.ZipFile) -> None:
    """Reject traversal, absolute paths, links, duplicate names, and zip bombs."""
    names: set[str] = set()
    total = 0
    for member in archive.infolist():
        if member.orig_filename != member.filename:
            raise ValueError(f"Unsafe ZIP member normalized by platform: {member.orig_filename}")
        name = member.filename
        pure = PurePosixPath(name)
        if ("\\" in name or ":" in name or pure.is_absolute()
                or any(p in ("..", ".", "") for p in name.split("/"))):
            raise ValueError(f"Unsafe ZIP member: {name}")
        if name.casefold() in names:
            raise ValueError("Duplicate/colliding ZIP member")
        names.add(name.casefold())
        if stat.S_ISLNK(member.external_attr >> 16):
            raise ValueError("Symbolic links in ZIP are not allowed")
        total += member.file_size
        if member.file_size > 100 * 1024 * 1024 or total > 3 * 1024**3:
            raise ValueError("ZIP expanded size exceeds research sample limits")
        if member.file_size > 1024**2 and member.file_size / max(1, member.compress_size) > 500:
            raise ValueError("Suspicious ZIP compression ratio")


def fetch_fx(data_dir: Path) -> dict:
    archive_path = data_dir / "raw" / "ecb_eurofxref_hist.zip"
    source = fetch(FX_URL, archive_path)
    original_csv = data_dir / "raw" / "ecb_eurofxref_hist_source.csv"
    with zipfile.ZipFile(archive_path) as archive:
        validate_zip_members(archive)
        if archive.namelist() != ["eurofxref-hist.csv"]:
            raise ValueError("Unexpected ECB history archive contents")
        with archive.open("eurofxref-hist.csv") as stream, original_csv.open("wb") as target:
            shutil.copyfileobj(stream, target)
    wide = pd.read_csv(original_csv, na_values=["N/A"])
    require_columns(wide, ["Date", *FX_SYMBOLS])
    validate_dates(wide.Date, "1999-01-01", utc_now()[:10])
    selected = wide.loc[wide.Date.between("1999-01-01", "2025-12-31"), ["Date", *FX_SYMBOLS]]
    normalized = selected.melt(id_vars="Date", var_name="CURRENCY", value_name="OBS_VALUE")
    normalized = normalized.rename(columns={"Date": "TIME_PERIOD"})
    for column, value in [("CURRENCY_DENOM", "EUR"), ("FREQ", "D"), ("EXR_TYPE", "SP00"), ("EXR_SUFFIX", "A")]:
        normalized[column] = value
    raw = data_dir / "raw" / "ecb_fx_1999_2025_long.csv"
    normalized_info = atomic_csv(normalized.sort_values(["TIME_PERIOD", "CURRENCY"]), raw)
    output = process_fx(raw, data_dir / "processed" / "fx.csv")
    manifest = {
        "dataset": "fx", "validated_utc": utc_now(), "source": source, "output": output,
        "terms_url": "https://www.ecb.europa.eu/services/disclaimer/html/index.en.html",
        "source_page": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
        "source_csv": {"path": original_csv.name, "sha256": sha256(original_csv), "bytes": original_csv.stat().st_size},
        "normalized_long": {**normalized_info, "status": "Derived long-format copy; original ECB bytes are preserved separately"},
        "units": "units of foreign currency per 1 EUR; do not interpret as EUR per foreign currency",
        "cleaning": ["Preserve official source ZIP and its wide CSV bytes", "Select the fixed 1999-2025 window and five currencies", "Melt to a separately identified normalized long CSV with ECB daily spot conventions", "Reject duplicate date/currency keys, nonpositive values and missing currency observations", "Pivot into date,USD,GBP,JPY,CHF,AUD and sort ascending", "No interpolation or forward fill; no weekend/holiday rows inserted"],
        "limitations": ["Reference rates are for information, not executable transaction prices", "Downloaded now; revised historical series, not vintage point-in-time release data", "1999-01-01 is the requested window start; first published observation is 1999-01-04"],
    }
    write_json(data_dir / "manifests" / "fx.json", manifest)
    print(f"FX ready: {output['rows']:,} dates, {output['start']} to {output['end']}", flush=True)
    return manifest


def fetch_rates(data_dir: Path) -> dict:
    raw = data_dir / "raw" / "fred_DGS3MO_2022JunDec.csv"
    source = fetch(RATES_URL, raw)
    output = process_rates(raw, data_dir / "processed" / "rates.csv")
    manifest = {
        "dataset": "rates", "validated_utc": utc_now(), "source": source, "output": output,
        "source_page": "https://fred.stlouisfed.org/series/DGS3MO",
        "terms_url": "https://fred.stlouisfed.org/legal/",
        "originator": "Board of Governors of the Federal Reserve System (US), H.15",
        "series": "DGS3MO", "source_units": "percent per annum, investment basis, daily, not seasonally adjusted",
        "units": "annual decimal yield; investment-basis quote, not a full continuously compounded zero curve",
        "cleaning": ["Convert percent to decimal by division by 100", "Drop missing holiday observations and record their dates", "Reject duplicate/nonfinite observations; no interpolation or forward-fill in stored rates"],
        "limitations": ["One 3-month Treasury yield is a documented discounting proxy, not an OIS/zero curve for all maturities", "Using an earlier available observation requires an explicit backward as-of rule in the pricing study", "Historical downloaded series may have revisions; citation requested for public-domain Federal Reserve observations"],
    }
    write_json(data_dir / "manifests" / "rates.json", manifest)
    print(f"Rates ready: {output['rows']} dated observations", flush=True)
    return manifest


def fetch_options(data_dir: Path) -> dict:
    """Obtain the archive; extraction and verification are defined below."""
    raw = data_dir / "raw" / "options_sample_2022H2.zip"
    source = fetch(OPTIONS_URL, raw)
    return process_options(raw, data_dir, source)


def process_options(raw: Path, data_dir: Path, source: dict) -> dict:
    """Check archive scope, published hashes and study inputs without vendor code.

    CSVs are extracted byte-for-byte. Quote filters belong in the pricing study;
    this layer preserves missing quotes rather than inventing zero prices.
    """
    output_dir = data_dir / "processed" / "options"
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = data_dir / "raw" / "options_sample_documents"
    documents.mkdir(parents=True, exist_ok=True)
    verified = []
    totals = {"rows": 0, "quote_time_missing": 0, "bid_missing": 0,
              "ask_missing": 0, "underlying_close_missing": 0, "crossed_quotes": 0,
              "spxw_european_pm_rows": 0, "spxw_two_sided_uncrossed_rows": 0,
              "last_trade_before_quote_date": 0}
    underlying_counts: dict[str, int] = {}
    close_discrepancies = []
    with zipfile.ZipFile(raw) as archive:
        validate_zip_members(archive)
        publisher_bytes = archive.read("day_by_date/manifest.json")
        publisher = json.loads(publisher_bytes)
        expected = publisher.get("files", [])
        if (publisher.get("product") != "options_sample_2022H2"
                or publisher.get("trading_days_expected") != 127
                or publisher.get("trading_days_present") != 127
                or publisher.get("trading_days_missing") != []
                or len(expected) != 127):
            raise ValueError("Unexpected/incomplete options sample manifest")
        names = []
        for entry in expected:
            name = entry.get("name", "")
            if not re.fullmatch(r"2022-\d{2}-\d{2}_options\.csv", name):
                raise ValueError("Unsafe or unexpected publisher file name")
            if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
                raise ValueError("Invalid publisher SHA256")
            if not isinstance(entry.get("rows"), int) or entry["rows"] <= 0:
                raise ValueError("Invalid publisher row count")
            if not isinstance(entry.get("bytes"), int) or entry["bytes"] <= 0:
                raise ValueError("Invalid publisher byte count")
            names.append(name)
        if len(set(names)) != 127:
            raise ValueError("Duplicate publisher entries")
        dates = sorted(name[:10] for name in names)
        validate_dates(pd.Series(dates), "2022-07-01", "2022-12-30")
        if dates[0] != publisher.get("first_day") or dates[-1] != publisher.get("last_day"):
            raise ValueError("Publisher date range is inconsistent")
        required_members = {f"day_by_date/{name}" for name in names}
        required_members.update({"LICENSE.txt", "README.md", "verify.py", "day_by_date/manifest.json"})
        if set(archive.namelist()) != required_members:
            raise ValueError("ZIP contents do not exactly match declared sample")
        unexpected_existing = {p.name for p in output_dir.glob("*.csv")} - set(names)
        if unexpected_existing:
            raise ValueError("Options output directory has unlisted CSV files")
        # Documentation is inert. verify.py remains inside the original ZIP only.
        for name in ["LICENSE.txt", "README.md", "day_by_date/manifest.json"]:
            (documents / PurePosixPath(name).name).write_bytes(archive.read(name))
        for number, entry in enumerate(sorted(expected, key=lambda x: x["name"]), 1):
            target = output_dir / entry["name"]
            temporary = target.with_suffix(".csv.tmp")
            with archive.open(f"day_by_date/{entry['name']}") as stream, temporary.open("wb") as dest:
                shutil.copyfileobj(stream, dest)
            check_publisher_file(temporary, entry)
            audit = audit_options_day(temporary, entry["name"][:10])
            if audit["rows"] != entry["rows"]:
                raise ValueError(f"Publisher row count mismatch: {entry['name']}")
            for key in totals:
                totals[key] += audit[key]
            for underlying, count in audit["underlying_counts"].items():
                underlying_counts[underlying] = underlying_counts.get(underlying, 0) + count
            if audit["spx_spxw_close_max_difference"] > 0:
                close_discrepancies.append({"date": entry["name"][:10],
                                           "max_difference": audit["spx_spxw_close_max_difference"]})
            temporary.replace(target)
            verified.append({**entry, "schema_validated": True})
            if number % 25 == 0:
                print(f"Options verified: {number}/127 day files", flush=True)
        if totals["rows"] != publisher.get("rows_total"):
            raise ValueError("Publisher total rows mismatch")
    manifest = {
        "dataset": "options", "validated_utc": utc_now(), "source": source,
        "source_page": "https://historicaldata.net/samples.html",
        "terms_url": "https://historicaldata.net/terms.html",
        "schema": OPTION_COLUMNS, "files": verified,
        "publisher_manifest_sha256": hashlib.sha256(publisher_bytes).hexdigest(),
        "publisher_license_sha256": sha256(documents / "LICENSE.txt"),
        "first_day": dates[0], "last_day": dates[-1], "day_files": len(verified),
        "quality_counts": totals, "underlying_counts": underlying_counts,
        "spx_spxw_close_discrepancies": close_discrepancies,
        "cleaning": ["None: contract CSV bytes retained exactly as published",
                     "Independently check publisher file hashes, bytes, rows, schema and file-set coverage",
                     "Reject unsafe ZIP paths, links, collisions and excessive expanded size",
                     "Validate study input types, key uniqueness, date alignment and positive available prices",
                     "No provider Python is executed; validation does not claim to reproduce every vendor solver invariant"],
        "usage": ["Free sample evaluation allowed by publisher terms",
                  "Keep original and contract-level derived data local and out of Git",
                  "Do not redistribute raw files or reconstructable derived outputs",
                  "Credit HistoricalData.net with a link in public research"],
        "limitations": ["Third-party historical archive, not authenticated exchange quote data; hashes establish delivery integrity only",
                        "All 2022 quote_time cells are blank: freshness and simultaneous quote times cannot be verified",
                        "Last standing option quotes and underlying closes can be asynchronous; an EOD file is not a synchronized snapshot",
                        "SPX and SPXW underlying_close differences are recorded, not silently reconciled",
                        "Provider iv and Greeks are computed fields, not independent validation truth",
                        "Do not treat missing bid/ask, volume or trade dates as zero",
                        "Only six months and five roots; no claim of complete market or regime coverage"],
    }
    write_json(data_dir / "manifests" / "options.json", manifest)
    print(f"Options ready: {len(verified)} dates, {totals['rows']:,} rows", flush=True)
    return manifest


def check_publisher_file(path: Path, entry: dict) -> None:
    if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
        raise ValueError(f"Publisher byte/hash mismatch: {entry['name']}")


def audit_options_day(path: Path, day: str) -> dict:
    frame = pd.read_csv(path, keep_default_na=False, dtype=str)
    if list(frame.columns) != OPTION_COLUMNS:
        raise ValueError(f"Incorrect 34-column options schema: {path.name}")
    required = ["contract", "underlying", "expiration", "type", "strike", "style", "quote_date", "iv_flag"]
    if frame[required].eq("").any().any() or frame.empty:
        raise ValueError("Empty options day or missing required values")
    if not frame.quote_date.eq(day).all() or frame.contract.duplicated().any():
        raise ValueError("Option quote dates or contract keys are inconsistent")
    validate_dates(frame.quote_date, "2022-07-01", "2022-12-30")
    expiration = validate_dates(frame.expiration, day, "2035-12-31")
    if not frame.type.isin(["call", "put"]).all() or not frame["style"].isin(["A", "E"]).all():
        raise ValueError("Unexpected option type/exercise style")
    if not frame.settlement_time.isin(["", "AM", "PM"]).all():
        raise ValueError("Unexpected option settlement code")
    if not frame.underlying.isin(["SPX", "SPXW", "SPY", "TSLA", "KO"]).all():
        raise ValueError("Unexpected underlying in options sample")
    if frame.quote_time.ne("").any():
        raise ValueError("Unexpected quote timestamps in the historical 2022 sample")
    text_columns = {"contract", "underlying", "expiration", "type", "style", "quote_date", "quote_time", "last_trade_date", "settlement_time"}
    integer_columns = {"bid_size", "ask_size", "volume", "open_interest", "transactions", "multileg_volume", "active_minutes", "iv_flag"}
    for column in set(OPTION_COLUMNS) - text_columns:
        frame[column] = pd.to_numeric(frame[column].replace("", np.nan), errors="raise")
        values = frame[column].dropna()
        if not np.isfinite(values).all():
            raise ValueError(f"Nonfinite options value: {column}")
        if column in integer_columns and ((values % 1 != 0) | (values < 0)).any():
            raise ValueError(f"Invalid options integer: {column}")
    for column in ["strike", "bid", "ask", "underlying_close"]:
        if (frame[column].dropna() <= 0).any():
            raise ValueError(f"Nonpositive options value: {column}")
    present_trade = frame.last_trade_date.ne("")
    validate_dates(frame.loc[present_trade, "last_trade_date"], "2002-01-01", day)
    root = frame.contract.str.extract(r"^([A-Z]+)\d{6}[CP]\d{8}$", expand=False)
    if root.isna().any() or not root.eq(frame.underlying).all():
        raise ValueError("Unexpected contract identifiers in 2022 sample")
    if (not frame.contract.str[-15:-9].eq(expiration.dt.strftime("%y%m%d")).all()
            or not frame.contract.str[-9].eq(frame.type.map({"call": "C", "put": "P"})).all()
            or not np.allclose(frame.contract.str[-8:].astype(int) / 1000, frame.strike,
                               rtol=0, atol=1e-8)):
        raise ValueError("Contract symbol disagrees with expiration/type/strike fields")
    spxw = root.eq("SPXW") & frame["style"].eq("E") & frame.settlement_time.eq("PM")
    both = frame.bid.notna() & frame.ask.notna()
    spx_close = frame.loc[root.eq("SPX"), "underlying_close"].dropna()
    spxw_close = frame.loc[root.eq("SPXW"), "underlying_close"].dropna()
    difference = 0.0
    if not spx_close.empty and not spxw_close.empty:
        difference = max(abs(spx_close.max() - spxw_close.min()), abs(spxw_close.max() - spx_close.min()))
    return {
        "rows": len(frame), "quote_time_missing": int(frame.quote_time.eq("").sum()),
        "bid_missing": int(frame.bid.isna().sum()), "ask_missing": int(frame.ask.isna().sum()),
        "underlying_close_missing": int(frame.underlying_close.isna().sum()),
        "crossed_quotes": int((both & (frame.bid > frame.ask)).sum()),
        "spxw_european_pm_rows": int(spxw.sum()),
        "spxw_two_sided_uncrossed_rows": int((spxw & both & (frame.ask >= frame.bid)).sum()),
        "last_trade_before_quote_date": int((present_trade & (frame.last_trade_date < day)).sum()),
        "underlying_counts": {key: int(value) for key, value in frame.underlying.value_counts().items()},
        "spx_spxw_close_max_difference": float(difference),
        "latest_expiration": expiration.max().strftime("%Y-%m-%d"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=["fx", "rates", "options", "all"], default="all")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    actions = {"fx": fetch_fx, "rates": fetch_rates, "options": fetch_options}
    for dataset in actions if args.dataset == "all" else [args.dataset]:
        actions[dataset](data_dir)


if __name__ == "__main__":
    main()
