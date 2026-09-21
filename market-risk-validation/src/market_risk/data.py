"""Read public ECB quotes without silently repairing suspicious observations.

The canonical quote is foreign currency units per EUR. No interpolation, forward
fill, winsorisation or zero-return insertion is performed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

CURRENCIES = ("USD", "GBP", "JPY", "CHF", "AUD")


class DataError(ValueError):
    """The supplied dataset cannot be used without an explicit correction."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def write_json(path: str | Path, value: object) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )


def read_fx(path: str | Path) -> pd.DataFrame:
    """Accept canonical wide CSV or official ECB long CSV; return date-indexed quotes."""
    raw = pd.read_csv(path, dtype=str)
    if {"TIME_PERIOD", "CURRENCY", "OBS_VALUE"}.issubset(raw.columns):
        raw = raw.loc[raw["CURRENCY"].isin(CURRENCIES)].copy()
        if raw.empty:
            raise DataError("ECB file contains none of the five required currencies")
        for name, expected in (("FREQ", "D"), ("CURRENCY_DENOM", "EUR"), ("EXR_TYPE", "SP00")):
            if name in raw and not raw[name].eq(expected).all():
                raise DataError(f"ECB {name} must be {expected}; mixed/reversed series rejected")
        if raw.duplicated(["TIME_PERIOD", "CURRENCY"]).any():
            raise DataError("Duplicate ECB date/currency observations")
        # Official long files are grouped by series; a pivot is an explicit format conversion.
        raw = raw.pivot(index="TIME_PERIOD", columns="CURRENCY", values="OBS_VALUE")
        raw = raw.sort_index().reset_index().rename(columns={"TIME_PERIOD": "date"})
    if "date" not in raw:
        raise DataError("Expected date column or official ECB long CSV")
    missing = set(CURRENCIES) - set(raw.columns)
    if missing:
        raise DataError(f"Missing currencies: {sorted(missing)}")
    if len(raw) < 2:
        raise DataError("At least two observations are required")
    if not raw["date"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise DataError("Dates must use YYYY-MM-DD without time or timezone")
    dates = pd.to_datetime(raw["date"], format="%Y-%m-%d", errors="raise")
    if dates.duplicated().any():
        raise DataError("Duplicate dates")
    if not dates.is_monotonic_increasing:
        raise DataError("Canonical input dates must already be strictly increasing")
    if (dates.dt.dayofweek >= 5).any():
        raise DataError("Weekend observations are not ECB reference-rate business days")
    try:
        quotes = raw.loc[:, CURRENCIES].apply(pd.to_numeric, errors="raise")
    except (ValueError, TypeError) as exc:
        raise DataError("Quotes must be numeric") from exc
    if not np.isfinite(quotes.to_numpy()).all() or (quotes.to_numpy() <= 0).any():
        raise DataError("Quotes must be finite, strictly positive and complete for all currencies")
    quotes.index = pd.DatetimeIndex(dates, name="date")
    return quotes.astype(float)


def ingest(source: str | Path, output: str | Path) -> dict:
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise DataError("Use a separate canonical output; retain the original source bytes")
    quotes = read_fx(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    quotes.to_csv(output, date_format="%Y-%m-%d", float_format="%.17g")
    gaps = quotes.index.to_series().diff().dt.days
    metadata = {
        "schema_version": 1,
        "source_path": str(source.resolve()),
        "source_sha256": sha256_file(source),
        "canonical_path": str(output.resolve()),
        "canonical_sha256": sha256_file(output),
        "retrieved_or_processed_at_utc": datetime.now(UTC).isoformat(),
        "currencies": list(CURRENCIES),
        "quote_convention": "foreign_currency_units_per_EUR",
        "rows": len(quotes),
        "first_date": quotes.index[0].strftime("%Y-%m-%d"),
        "last_date": quotes.index[-1].strftime("%Y-%m-%d"),
        "calendar": "observed ECB reference-rate dates only; no filling",
        "gaps_over_four_calendar_days": int((gaps > 4).sum()),
        "cleaning": "format conversion and validation only; no imputation or clipping",
    }
    write_json(output.with_suffix(".manifest.json"), metadata)
    return metadata
