"""Auditable quote ingestion and historical-rate availability rules."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd

REQUIRED = {"underlying", "style", "settlement_time", "quote_date", "expiration",
            "strike", "type", "bid", "ask", "underlying_close"}
NORMALIZED = ["quote_id", "source_file", "source_row", "quote_date", "expiration", "kind",
              "strike", "bid", "ask", "spot", "days", "time", "moneyness", "mid", "spread",
              "rate", "rate_date", "split", "assignment", "quote_time", "quality_flags"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def assignment(quote_date: str, expiration: str, strike: float) -> str:
    """The call and put of a strike always have the same predeclared assignment."""
    key = f"option-protocol-v1|{quote_date}|{expiration}|{strike:.8f}"
    bucket = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 10
    return "train" if bucket < 7 else "holdout"


def rate_table(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if not {"date", "rate"} <= set(frame):
        raise ValueError("Rate file requires date and annual-decimal rate")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["rate"] = pd.to_numeric(frame["rate"], errors="coerce")
    frame = frame.dropna(subset=["date", "rate"]).sort_values("date")
    if frame["date"].duplicated().any():
        raise ValueError("Rate dates must be unique")
    if not frame["rate"].map(math.isfinite).all() or not frame["rate"].between(-0.10, 0.50).all():
        raise ValueError("Rates must be finite annual decimals (not percentage values)")
    return frame


def ingest(options_dir: Path, rates_path: Path, output: Path) -> dict:
    """Validate source rows without using provider IV or provider Greeks as truth."""
    output.mkdir(parents=True, exist_ok=True)
    paths = sorted(options_dir.glob("*.csv"))
    if not paths:
        raise ValueError(f"No source option CSV files in {options_dir}")
    rates = rate_table(rates_path)
    receipts = []
    seen = set()
    source_count = 0
    accepted_count = excluded_count = 0
    date_cache, rate_cache = {}, {}
    quotes_path, exclusions_path = output / "ingested_quotes.csv", output / "ingest_exclusions.csv"
    rejected_columns = ["quote_id", "source_file", "source_row", "quote_date", "expiration", "reasons"]
    pd.DataFrame(columns=NORMALIZED).to_csv(quotes_path, index=False)
    pd.DataFrame(columns=rejected_columns).to_csv(exclusions_path, index=False)
    def parsed_date(value):
        key = str(value)
        if key not in date_cache:
            date_cache[key] = pd.to_datetime(value, errors="coerce")
        return date_cache[key]
    for path in paths:
        accepted, rejected = [], []
        receipts.append(dict(file=path.name, sha256=sha256(path)))
        frame = pd.read_csv(path, low_memory=False, usecols=lambda c: c.strip().lower() in REQUIRED | {"quote_time"})
        frame.columns = [str(c).strip().lower() for c in frame.columns]
        missing = REQUIRED - set(frame)
        if missing:
            raise ValueError(f"{path.name}: missing required columns {sorted(missing)}")
        for row_number, row in enumerate(frame.to_dict("records"), 2):
            source_count += 1
            quote_id = hashlib.sha256(f"{path.name}|{row_number}".encode()).hexdigest()[:20]
            # The downloaded universe includes equities. Record each out-of-scope
            # row, but avoid expensive date/IV processing outside the chosen product.
            if str(row["underlying"]).upper().strip() != "SPXW":
                rejected.append(dict(quote_id=quote_id, source_file=path.name, source_row=row_number,
                                     quote_date=str(row["quote_date"]), expiration=str(row["expiration"]),
                                     reasons="unsupported_underlying"))
                continue
            reasons = []
            date = parsed_date(row["quote_date"])
            expiry = parsed_date(row["expiration"])
            if pd.isna(date) or pd.isna(expiry):
                reasons.append("invalid_date")
            else:
                date, expiry = date.normalize(), expiry.normalize()
                if not pd.Timestamp("2022-07-01") <= date <= pd.Timestamp("2022-12-31"):
                    reasons.append("outside_predeclared_2022H2")
            if str(row["underlying"]).upper().strip() != "SPXW":
                reasons.append("unsupported_underlying")
            if str(row["style"]).upper().strip() != "E":
                reasons.append("not_european")
            if str(row["settlement_time"]).upper().strip() != "PM":
                reasons.append("not_pm_settled")
            kind = {"c": "call", "p": "put", "call": "call", "put": "put"}.get(str(row["type"]).strip().lower())
            if kind is None:
                reasons.append("unsupported_option_type")
            numbers = {}
            for key in ("strike", "bid", "ask", "underlying_close"):
                try:
                    numbers[key] = float(row[key])
                except (ValueError, TypeError):
                    numbers[key] = float("nan")
                if not math.isfinite(numbers[key]):
                    reasons.append(f"invalid_{key}")
            strike, bid, ask, spot = (numbers[k] for k in ("strike", "bid", "ask", "underlying_close"))
            if math.isfinite(strike) and strike <= 0:
                reasons.append("nonpositive_strike")
            if math.isfinite(spot) and spot <= 0:
                reasons.append("nonpositive_underlying_close")
            if math.isfinite(bid) and bid <= 0:
                reasons.append("nonpositive_bid_excluded_from_iv_study")
            if math.isfinite(ask) and ask <= 0:
                reasons.append("nonpositive_ask")
            if math.isfinite(bid) and math.isfinite(ask) and ask < bid:
                reasons.append("crossed_quote")
            mid = (bid + ask) / 2
            if math.isfinite(mid) and mid > 0 and (ask - bid) / mid > 0.15 + 1e-12:
                reasons.append("relative_spread_above_15pct")
            if spot > 0 and math.isfinite(spot) and math.isfinite(strike) and not 0.8 <= strike / spot <= 1.2:
                reasons.append("moneyness_outside_0.8_1.2")
            days, rate, rate_date = None, None, None
            if not pd.isna(date) and not pd.isna(expiry):
                days = (expiry - date).days
                if not 30 <= days <= 180:
                    reasons.append("tenor_outside_30_180_days")
                if date not in rate_cache:
                    eligible = rates.loc[rates["date"] < date]
                    rate_cache[date] = None if eligible.empty or (date - eligible.iloc[-1]["date"]).days > 7 else (float(eligible.iloc[-1]["rate"]), eligible.iloc[-1]["date"].date().isoformat())
                if rate_cache[date] is None:
                    reasons.append("no_prior_rate_within_7_days")
                else:
                    rate, rate_date = rate_cache[date]
            if reasons:
                rejected.append(dict(quote_id=quote_id, source_file=path.name, source_row=row_number,
                                     quote_date=str(row["quote_date"]), expiration=str(row["expiration"]),
                                     reasons=";".join(sorted(set(reasons)))))
                continue
            date_text, expiry_text = date.date().isoformat(), expiry.date().isoformat()
            key = (date_text, expiry_text, strike, kind)
            if key in seen:
                rejected.append(dict(quote_id=quote_id, source_file=path.name, source_row=row_number,
                                     quote_date=date_text, expiration=expiry_text,
                                     reasons="duplicate_contract_date_keep_first_sorted_source"))
                continue
            seen.add(key)
            quote_time = row.get("quote_time", "")
            quote_time = "" if pd.isna(quote_time) else str(quote_time).strip()
            flags = "daily_close_proxy_not_verified_simultaneous"
            if not quote_time:
                flags += ";quote_time_missing"
            accepted.append(dict(quote_id=quote_id, source_file=path.name, source_row=row_number,
                                 quote_date=date_text, expiration=expiry_text, kind=kind, strike=strike,
                                 bid=bid, ask=ask, spot=spot, days=days, time=days / 365,
                                 moneyness=strike / spot, mid=mid, spread=ask - bid, rate=rate,
                                 rate_date=rate_date, split="development" if date.month <= 8 else "temporal_test",
                                 assignment=assignment(date_text, expiry_text, strike), quote_time=quote_time,
                                 quality_flags=flags))
        pd.DataFrame(accepted, columns=NORMALIZED).to_csv(quotes_path, index=False, mode="a", header=False)
        pd.DataFrame(rejected, columns=rejected_columns).to_csv(exclusions_path, index=False, mode="a", header=False)
        accepted_count += len(accepted)
        excluded_count += len(rejected)
    summary = dict(protocol="option-protocol-v1", source_rows=source_count, accepted_rows=accepted_count,
                   excluded_rows=excluded_count, sources=receipts,
                   rates=dict(file=rates_path.name, sha256=sha256(rates_path)),
                   outputs={p.name: sha256(p) for p in (quotes_path, exclusions_path)},
                   note="DGS3MO is a historical 3-month Treasury flat discount proxy, not an OIS/zero curve. Prior observations only; at most seven days stale.")
    write_json(output / "ingest_manifest.json", summary)
    return summary
