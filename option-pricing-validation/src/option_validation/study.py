"""Training-only parity forwards and constant-volatility quote-slice experiments."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import ndtr

from option_validation.data import sha256, write_json
from option_validation.experiments import numerical_cases, shock_experiment
from option_validation.pricing import IVResult, forward_greeks, implied_volatility

PREDICTION_COLUMNS = ["quote_id", "quote_date", "expiration", "kind", "strike", "spot", "days", "time",
                      "bid", "ask", "mid", "spread", "moneyness", "split", "assignment", "quality_flags",
                      "rate_date", "rate", "rate_shift", "discount", "forward", "sigma", "group_status",
                      "model_price", "error", "absolute_error", "within_spread", "spread_scaled_error",
                      "iv_bid", "iv_ask", "iv_bid_status", "iv_ask_status", "forward_delta", "forward_gamma",
                      "vega_1pct"]


def black_vector(kinds: np.ndarray, strikes: np.ndarray, forward: float, discount: float,
                 time: float, sigma: float) -> np.ndarray:
    """Vectorized calibration objective (independently audited with QuantLib)."""
    width = sigma * math.sqrt(time)
    d1 = np.log(forward / strikes) / width + width / 2
    d2 = d1 - width
    call = discount * (forward * ndtr(d1) - strikes * ndtr(d2))
    put = discount * (strikes * ndtr(-d2) - forward * ndtr(-d1))
    return np.maximum(np.where(kinds == "call", call, put), 0.0)


def parity_forward(train: pd.DataFrame, discount: float) -> dict:
    calls = train.loc[train["kind"] == "call"].set_index("strike")
    puts = train.loc[train["kind"] == "put"].set_index("strike")
    strikes = calls.index.intersection(puts.index).sort_values()
    if len(strikes) < 3:
        return dict(status="REJECTED", reason="fewer_than_three_training_call_put_pairs", pairs=len(strikes))
    call, put = calls.loc[strikes], puts.loc[strikes]
    ks = strikes.to_numpy(dtype=float)
    low = ks + (call["bid"].to_numpy() - put["ask"].to_numpy()) / discount
    high = ks + (call["ask"].to_numpy() - put["bid"].to_numpy()) / discount
    mid = ks + (call["mid"].to_numpy() - put["mid"].to_numpy()) / discount
    forward = float(np.median(mid))
    span = float((ks.max() - ks.min()) / train["spot"].median())
    dispersion = float((np.quantile(mid, 0.75) - np.quantile(mid, 0.25)) / max(abs(forward), 1e-12))
    if not math.isfinite(forward) or forward <= 0 or span < 0.02 or dispersion > 0.05:
        return dict(status="REJECTED", reason="unstable_parity_forward_or_insufficient_strike_span",
                    pairs=len(strikes), strike_span_fraction=span, forward_iqr_fraction=dispersion)
    lower, upper = float(low.max()), float(high.min())
    compatible = lower <= upper
    if compatible:
        forward = float(np.clip(forward, lower, upper))
    status = "PARITY_COMPATIBLE_DAILY_PROXY" if compatible else "EXPLORATORY_INCONSISTENT_QUOTES"
    return dict(status=status, forward=forward, pairs=len(strikes), intersection_lower=lower,
                intersection_upper=upper, intersection_gap=max(lower - upper, 0.0),
                intersection_gap_fraction=max(lower - upper, 0.0) / forward,
                pair_interval_satisfaction=float(np.mean((low <= forward) & (forward <= high))),
                strike_span_fraction=span, forward_iqr_fraction=dispersion,
                training_pair_strikes=ks.tolist(),
                note="Even compatible intervals do not establish synchronous quotes or a calibrated market discount curve.")


def fit_group(group: pd.DataFrame, rate_shift: float = 0.0) -> tuple[dict, list[dict]]:
    first = group.iloc[0]
    record = dict(quote_date=str(first["quote_date"]), expiration=str(first["expiration"]),
                  split=str(first["split"]), rate_shift=rate_shift, days=int(first["days"]),
                  time=float(first["time"]), rows=len(group), training_rows=int((group["assignment"] == "train").sum()),
                  holdout_rows=int((group["assignment"] == "holdout").sum()))
    if group["spot"].max() - group["spot"].min() > 1e-8 * float(group["spot"].median()):
        return dict(record, status="REJECTED", reason="inconsistent_underlying_close_within_group"), []
    train, holdout = group[group["assignment"] == "train"], group[group["assignment"] == "holdout"]
    if holdout["strike"].nunique() < 2:
        return dict(record, status="REJECTED", reason="fewer_than_two_holdout_strikes"), []
    rate = float(first["rate"]) + rate_shift
    discount = math.exp(-rate * float(first["time"]))
    parity = parity_forward(train, discount)
    if parity["status"] == "REJECTED":
        return dict(record, **parity), []
    forward, time = parity["forward"], float(first["time"])
    kinds, strikes, mids = train["kind"].to_numpy(), train["strike"].to_numpy(), train["mid"].to_numpy()
    scale = np.maximum(train["spread"].to_numpy() / 2, 0.05)

    def objective(sigma: float) -> float:
        residual = (black_vector(kinds, strikes, forward, discount, time, sigma) - mids) / scale
        return float(np.mean(residual**2))

    fit = minimize_scalar(objective, bounds=(0.01, 3.0), method="bounded", options={"xatol": 1e-8})
    sigma = float(fit.x)
    if not fit.success or sigma <= 0.01001 or sigma >= 2.99999:
        return dict(record, status="REJECTED", reason="constant_vol_fit_failed_or_hit_bound", parity=parity), []
    values = black_vector(group["kind"].to_numpy(), group["strike"].to_numpy(), forward, discount, time, sigma)
    predictions = []
    for row, value in zip(group.to_dict("records"), values, strict=True):
        # Intervals are a base-assumption held-out diagnostic, not a fit metric.
        # Avoid millions of unnecessary inversions on training/sensitivity rows.
        if row["assignment"] == "holdout" and rate_shift == 0:
            bid_iv = implied_volatility(row["kind"], row["bid"], forward, row["strike"], time, discount)
            ask_iv = implied_volatility(row["kind"], row["ask"], forward, row["strike"], time, discount)
        else:
            bid_iv = ask_iv = IVResult("not_computed_training_or_rate_sensitivity", None)
        greeks = forward_greeks(row["kind"], forward, row["strike"], time, sigma, discount)
        predictions.append({key: value_ for key, value_ in dict(
            row, rate=rate, rate_shift=rate_shift, discount=discount, forward=forward, sigma=sigma,
            group_status=parity["status"], model_price=float(value), error=float(value - row["mid"]),
            absolute_error=float(abs(value - row["mid"])),
            within_spread=bool(row["bid"] <= value <= row["ask"]),
            spread_scaled_error=float((value - row["mid"]) / max(row["spread"] / 2, 0.05)),
            iv_bid=bid_iv.volatility, iv_ask=ask_iv.volatility,
            iv_bid_status=bid_iv.status, iv_ask_status=ask_iv.status,
            forward_delta=greeks["forward_delta"], forward_gamma=greeks["forward_gamma"],
            vega_1pct=greeks["vega_1pct"]).items() if key in PREDICTION_COLUMNS})
    record.update(status=parity["status"], parity=parity, rate=rate, rate_date=str(first["rate_date"]),
                  discount=discount, forward=forward, sigma=sigma, training_objective=float(fit.fun),
                  training_quote_ids=train["quote_id"].tolist(), holdout_quote_ids=holdout["quote_id"].tolist())
    return record, predictions


def metrics(predictions: pd.DataFrame) -> list[dict]:
    if predictions.empty:
        return []
    holdout = predictions.loc[predictions["assignment"] == "holdout"].copy()
    holdout["moneyness_band"] = pd.cut(holdout["moneyness"], [0.0, 0.95, 1.05, np.inf], labels=["K/S<=0.95", "0.95<K/S<=1.05", "K/S>1.05"], right=True).astype(str)
    rows = []
    for keys in (("split", "group_status", "rate_shift"), ("split", "group_status", "rate_shift", "moneyness_band")):
        for values, frame in holdout.groupby(list(keys), observed=True):
            row = dict(zip(keys, values, strict=True))
            row.update(quotes=len(frame), dates=int(frame["quote_date"].nunique()),
                       expiry_date_groups=len(frame[["quote_date", "expiration"]].drop_duplicates()),
                       spread_coverage=float(frame["within_spread"].mean()),
                       mae_points=float(frame["absolute_error"].mean()),
                       rmse_points=float(np.sqrt(np.mean(frame["error"]**2))),
                       median_absolute_spread_scaled_error=float(frame["spread_scaled_error"].abs().median()))
            rows.append(row)
    return rows


def metrics_file(path: Path) -> list[dict]:
    """Full-sample aggregates without retaining the million-row prediction table."""
    accumulators = {}
    for chunk in pd.read_csv(path, chunksize=40000):
        held = chunk[chunk["assignment"] == "holdout"].copy()
        held["moneyness_band"] = pd.cut(held["moneyness"], [0.0, 0.95, 1.05, np.inf], labels=["K/S<=0.95", "0.95<K/S<=1.05", "K/S>1.05"], right=True).astype(str)
        for columns in (("split", "group_status", "rate_shift"), ("split", "group_status", "rate_shift", "moneyness_band")):
            for values, frame in held.groupby(list(columns), observed=True):
                key = tuple(zip(columns, values, strict=True))
                acc = accumulators.setdefault(key, dict(n=0, covered=0, absolute=0.0, squared=0.0, dates=set(), groups=set(), scaled=[]))
                acc["n"] += len(frame)
                acc["covered"] += int(frame["within_spread"].sum())
                acc["absolute"] += float(frame["absolute_error"].sum())
                acc["squared"] += float((frame["error"]**2).sum())
                acc["dates"].update(frame["quote_date"])
                acc["groups"].update(zip(frame["quote_date"], frame["expiration"], strict=True))
                acc["scaled"].append(frame["spread_scaled_error"].abs().to_numpy())
    rows = []
    for key, acc in sorted(accumulators.items(), key=lambda item: str(item[0])):
        row = dict(key)
        row.update(quotes=acc["n"], dates=len(acc["dates"]), expiry_date_groups=len(acc["groups"]),
                   spread_coverage=acc["covered"] / acc["n"], mae_points=acc["absolute"] / acc["n"],
                   rmse_points=math.sqrt(acc["squared"] / acc["n"]),
                   median_absolute_spread_scaled_error=float(np.median(np.concatenate(acc["scaled"]))))
        rows.append(row)
    return rows


def run(output: Path, *, numerical_only: bool = False) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    groups = []
    with (output / "predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        pd.DataFrame(columns=PREDICTION_COLUMNS).to_csv(stream, index=False)
        if not numerical_only:
            quotes_path = output / "ingested_quotes.csv"
            if not quotes_path.exists():
                raise ValueError("Run ingest first or explicitly select --numerical-only")
            quotes = pd.read_csv(quotes_path, keep_default_na=False)
            for _, group in quotes.groupby(["quote_date", "expiration"], sort=True):
                for shift in (-0.01, 0.0, 0.01):
                    record, rows = fit_group(group, shift)
                    groups.append(record)
                    if rows:
                        pd.DataFrame(rows, columns=PREDICTION_COLUMNS).to_csv(stream, index=False, header=False)
    write_json(output / "groups.json", {"groups": groups})
    payload = dict(
        schema_version=1, protocol="option-protocol-v1", numerical=numerical_cases(),
        shocks=shock_experiment(), market=dict(mode="numerical_only" if numerical_only else "real_quote_slice",
        groups=len(groups), base_groups=sum(g["rate_shift"] == 0 for g in groups),
        group_status_counts={s: sum(g["status"] == s and g["rate_shift"] == 0 for g in groups) for s in sorted({g["status"] for g in groups})},
        summaries=metrics_file(output / "predictions.csv")),
        files={name: sha256(output / name) for name in ("predictions.csv", "groups.json", "ingested_quotes.csv", "ingest_exclusions.csv", "ingest_manifest.json") if (output / name).exists()},
        conventions=dict(day_count="ACT/365F; integer date difference; daily-close proxy",
                         sigma="annual decimal", price="index points", vega="per 1 percentage point",
                         theta="calendar decay per ACT/365 day", rho="per 1 percentage point",
                         forward_greeks="F derivatives with discount held fixed; no claim of observed spot Greeks",
                         discount="prior-date DGS3MO flat proxy; not OIS or zero curve",
                         fit="Training strike pairs only; one sigma per date/expiry; 70/30 deterministic hash",
                         temporal_test="September–December frozen protocol, same-day training-strike recalibration; not next-day prediction"),
        limitations=["End-of-day bid/ask and underlying close are not proven synchronous; missing quote_time is retained as an explicit limitation.",
                     "Numerical engine agreement validates implementation under shared lognormal assumptions, not economic model truth.",
                     "Per-contract implied volatility is diagnostic inversion, never held-out model performance.",
                     "Quote observations cluster by date and expiry; counts are not independent population evidence.",
                     "No Heston, American exercise, live surface, tradable-arbitrage claim, or out-of-sample hedging claim."])
    write_json(output / "results.json", payload)
    return payload
