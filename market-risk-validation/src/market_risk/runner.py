"""Freeze the protocol, holdings, provenance and daily forecasts before validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from . import __version__
from .data import CURRENCIES, DataError, json_hash, read_fx, sha256_file, write_json
from .models import MODEL_NAMES, ewma_states, forecast_models


@dataclass(frozen=True)
class Protocol:
    window: int = 1000
    ewma_decay: float = 0.94
    ewma_initial_window: int = 250
    inception: str = "2004-01-01"
    development_end: str = "2009-12-31"
    test_start: str = "2010-01-01"
    end: str = "2025-12-31"
    eur_per_currency_at_inception: float = 1_000_000.0

    def validate(self) -> None:
        if self.window < 20 or self.ewma_initial_window < 2:
            raise ValueError("Window >=20 and EWMA initialization >=2 are required")
        if not 0 < self.ewma_decay < 1 or self.eur_per_currency_at_inception <= 0:
            raise ValueError("Invalid decay or notional")
        if not self.inception <= self.development_end < self.test_start <= self.end:
            raise ValueError("Dates must define disjoint ordered development and test intervals")


def run(data_path: str | Path, output_dir: str | Path, protocol: Protocol | None = None) -> dict:
    import pandas as pd

    protocol = protocol or Protocol()
    protocol.validate()
    quotes = read_fx(data_path)
    quotes = quotes.loc[: protocol.end]
    inception_candidates = np.flatnonzero(quotes.index >= protocol.inception)
    if not len(inception_candidates):
        raise DataError("No observation on or after portfolio inception")
    inception_index = int(inception_candidates[0])
    # First forecast is for the day after construction using the construction-day quote.
    if inception_index < protocol.window + protocol.ewma_initial_window:
        raise DataError("Insufficient pre-inception data for the shared HS/FHS warm-up")
    if inception_index + 1 >= len(quotes):
        raise DataError("No post-inception observation available for HPL")
    fx = quotes.to_numpy()
    eur_prices = 1.0 / fx
    returns = eur_prices[1:] / eur_prices[:-1] - 1.0
    covariance, residuals = ewma_states(returns, protocol.ewma_decay, protocol.ewma_initial_window)
    units = protocol.eur_per_currency_at_inception * fx[inception_index]
    initial_gross = protocol.eur_per_currency_at_inception * len(CURRENCIES)
    source_hash = sha256_file(data_path)
    model_source_hashes = {
        name: sha256_file(Path(__file__).parent / name)
        for name in ("__init__.py", "data.py", "models.py", "runner.py")
    }
    model_source_hash = json_hash(model_source_hashes)
    protocol_dict = {
        **asdict(protocol),
        "currencies": list(CURRENCIES),
        "models": list(MODEL_NAMES),
        "base_currency": "EUR",
        "portfolio_rule": "long EUR 1m equivalent each at inception; foreign units then fixed",
        "cash_carry": "excluded: reference-price hypothetical P&L, not actual trading P&L",
        "quantile": "inverse empirical CDF; ES integrates upper-tail probability mass",
        "variance_floor": 1e-18,
    }
    protocol_hash = json_hash(protocol_dict)
    rows = []
    for date_index in range(inception_index + 1, len(quotes)):
        day = quotes.index[date_index].strftime("%Y-%m-%d")
        if day <= protocol.development_end:
            split = "development"
        elif day >= protocol.test_start:
            split = "test"
        else:
            continue
        return_index = date_index - 1
        history_begin = return_index - protocol.window
        eur_holdings = units * eur_prices[date_index - 1]
        forecasts = forecast_models(
            returns[history_begin:return_index],
            residuals[history_begin:return_index],
            covariance[return_index],
            eur_holdings,
        )
        # Independent exact-price arithmetic, rather than recycling scenario P&L code.
        pnl = float(units @ (eur_prices[date_index] - eur_prices[date_index - 1]))
        for model in MODEL_NAMES:
            forecast = forecasts[model]
            rows.append(
                {
                    "date": day,
                    "as_of": quotes.index[date_index - 1].strftime("%Y-%m-%d"),
                    "split": split,
                    "model": model,
                    "pnl_eur": pnl,
                    "loss_eur": -pnl,
                    "var_975_eur": forecast.var_975,
                    "es_975_eur": forecast.es_975,
                    "var_99_eur": forecast.var_99,
                    "initial_gross_eur": initial_gross,
                    "history_start": quotes.index[history_begin + 1].strftime("%Y-%m-%d"),
                    "history_end": quotes.index[date_index - 1].strftime("%Y-%m-%d"),
                    "source_sha256": source_hash,
                    "protocol_sha256": protocol_hash,
                    "model_source_sha256": model_source_hash,
                }
            )
    if not rows:
        raise DataError("No forecast rows within the specified intervals")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    forecast_path = output / "predictions.csv"
    pd.DataFrame(rows).to_csv(forecast_path, index=False, float_format="%.17g")
    write_json(output / "protocol.json", protocol_dict)
    holdings = {
        "inception_date": quotes.index[inception_index].strftime("%Y-%m-%d"),
        "first_forecast_date": rows[0]["date"],
        "foreign_units": dict(zip(CURRENCIES, units.tolist(), strict=True)),
        "inception_quotes_foreign_per_eur": dict(
            zip(CURRENCIES, fx[inception_index].tolist(), strict=True)
        ),
        "initial_gross_eur": initial_gross,
        "rebalancing": "none",
    }
    write_json(output / "holdings.json", holdings)
    manifest = {
        "schema_version": 1,
        "package_version": __version__,
        "frozen_at_utc": datetime.now(UTC).isoformat(),
        "source_path": str(Path(data_path).resolve()),
        "source_sha256": source_hash,
        "source_rows_used": len(quotes),
        "source_first_date": quotes.index[0].strftime("%Y-%m-%d"),
        "source_last_date": quotes.index[-1].strftime("%Y-%m-%d"),
        "protocol_sha256": protocol_hash,
        "model_source_hashes": model_source_hashes,
        "model_source_sha256": model_source_hash,
        "predictions_sha256": sha256_file(forecast_path),
        "holdings_sha256": sha256_file(output / "holdings.json"),
        "forecast_rows": len(rows),
        "forecast_dates": len(rows) // len(MODEL_NAMES),
        "holdings": holdings,
        "protocol": protocol_dict,
    }
    write_json(output / "run_manifest.json", manifest)
    return manifest
