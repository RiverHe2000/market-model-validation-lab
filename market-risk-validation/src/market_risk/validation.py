"""Independent validation of an immutable forecast/HPL exchange file.

No import of models or runner is permitted here. Z2 inference below is explicitly
a centered circular moving-block-bootstrap approximation, not an exact
distribution-free test or a reproduction of the paper's simulation algorithm.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import xlogy
from scipy.stats import beta, binomtest, chi2

from .data import json_hash, read_fx, sha256_file, write_json
from .diagnostics import descriptive_diagnostics

REQUIRED_COLUMNS = {
    "date",
    "as_of",
    "split",
    "model",
    "loss_eur",
    "pnl_eur",
    "var_975_eur",
    "es_975_eur",
    "var_99_eur",
    "initial_gross_eur",
    "history_start",
    "history_end",
    "source_sha256",
    "protocol_sha256",
    "model_source_sha256",
}


class ValidationError(ValueError):
    """Forecast data failed its contract; statistical findings were not substituted."""


def load_frozen_predictions(path: str | Path, manifest_path: str | Path | None = None) -> tuple:
    path = Path(path)
    manifest_path = Path(manifest_path) if manifest_path else path.parent / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sha256_file(path) != manifest.get("predictions_sha256"):
        raise ValidationError("Prediction file changed after freeze: SHA-256 mismatch")
    if json_hash(manifest["protocol"]) != manifest["protocol_sha256"]:
        raise ValidationError("Frozen protocol hash mismatch")
    expected_source_files = {"__init__.py", "data.py", "models.py", "runner.py"}
    source_hashes = manifest.get("model_source_hashes", {})
    if set(source_hashes) != expected_source_files or json_hash(source_hashes) != manifest.get(
        "model_source_sha256"
    ):
        raise ValidationError("Frozen model-source manifest is incomplete or inconsistent")
    for name, expected in source_hashes.items():
        if sha256_file(Path(__file__).parent / name) != expected:
            raise ValidationError(f"Model source changed since prediction freeze: {name}")
    frame = pd.read_csv(path)
    check_contract(frame)
    if not frame["source_sha256"].eq(manifest["source_sha256"]).all():
        raise ValidationError("Prediction source identity differs from run manifest")
    if not frame["protocol_sha256"].eq(manifest["protocol_sha256"]).all():
        raise ValidationError("Prediction protocol identity differs from run manifest")
    if not frame["model_source_sha256"].eq(manifest["model_source_sha256"]).all():
        raise ValidationError("Prediction model source differs from run manifest")
    if len(frame) != manifest.get("forecast_rows"):
        raise ValidationError("Prediction row count differs from run manifest")
    protocol = manifest["protocol"]
    if set(frame["model"]) != set(protocol["models"]):
        raise ValidationError("Model set differs from the frozen protocol")
    expected_split = np.where(frame["date"] <= protocol["development_end"], "development", "test")
    if not frame["split"].eq(expected_split).all():
        raise ValidationError("Date/split assignment differs from the frozen protocol")
    in_gap = (frame["date"] > protocol["development_end"]) & (
        frame["date"] < protocol["test_start"]
    )
    if in_gap.any() or (frame["date"] > protocol["end"]).any():
        raise ValidationError("Forecast date outside the frozen intervals")
    portfolio_path = manifest_path.parent / "holdings.json"
    if sha256_file(portfolio_path) != manifest["holdings_sha256"]:
        raise ValidationError("Frozen holdings file changed")
    if json.loads(portfolio_path.read_text(encoding="utf-8")) != manifest["holdings"]:
        raise ValidationError("Holdings differ from run manifest")
    source = Path(manifest["source_path"])
    if sha256_file(source) != manifest["source_sha256"]:
        raise ValidationError("Source data changed since freeze")
    source_quotes = read_fx(source).loc[: protocol["end"]]
    calendar = source_quotes.index.strftime("%Y-%m-%d").tolist()
    holdings = manifest["holdings"]
    inception = holdings["inception_date"]
    eligible_dates = [day for day in calendar if day >= protocol["inception"]]
    if not eligible_dates or inception != eligible_dates[0]:
        raise ValidationError("Holdings inception is not the first eligible source observation")
    currencies = list(source_quotes.columns)
    if set(holdings["foreign_units"]) != set(currencies) or set(
        holdings["inception_quotes_foreign_per_eur"]
    ) != set(currencies):
        raise ValidationError("Frozen holdings currencies do not match the source")
    quantities = np.array([holdings["foreign_units"][name] for name in currencies], dtype=float)
    inception_quotes = source_quotes.loc[inception].to_numpy()
    recorded_quotes = np.array(
        [holdings["inception_quotes_foreign_per_eur"][name] for name in currencies], dtype=float
    )
    if not np.isfinite(quantities).all() or (quantities <= 0).any():
        raise ValidationError("Frozen cash quantities must be finite and positive")
    if not np.allclose(recorded_quotes, inception_quotes, rtol=1e-12, atol=1e-12):
        raise ValidationError("Frozen inception quotes differ from the source prices")
    per_currency_eur = float(protocol["eur_per_currency_at_inception"])
    if not np.allclose(quantities / inception_quotes, per_currency_eur, rtol=1e-12, atol=1e-6):
        raise ValidationError("Frozen quantities do not reproduce each initial EUR cash allocation")
    expected_gross = len(currencies) * per_currency_eur
    if not np.isclose(holdings["initial_gross_eur"], expected_gross, rtol=1e-12, atol=1e-6):
        raise ValidationError("Frozen holdings gross notional does not match the protocol")
    if not np.allclose(frame["initial_gross_eur"], expected_gross, rtol=1e-12, atol=1e-6):
        raise ValidationError("Prediction notional does not match the initial cash allocation")
    expected_dates = [
        day
        for day in calendar
        if day > inception and (day <= protocol["development_end"] or day >= protocol["test_start"])
    ]
    if sorted(frame["date"].unique()) != expected_dates:
        raise ValidationError("Forecast dates do not cover the frozen source calendar")
    calendar_index = {day: i for i, day in enumerate(calendar)}
    if holdings["first_forecast_date"] != expected_dates[0]:
        raise ValidationError("First forecast date differs from the frozen source calendar")
    # Every model's row is checked; comparing only one row per date can hide a
    # producer bug restricted to a challenger model's information set.
    for row in frame.itertuples():
        index = calendar_index[row.date]
        if (
            row.as_of != calendar[index - 1]
            or row.history_start != calendar[index - protocol["window"]]
        ):
            raise ValidationError("Forecast history window does not match the source calendar")
    # Independently reconstruct cash HPL from raw quote inverses and frozen native
    # quantities. A common unit/sign bug in every model's supplied P&L must not
    # become accepted merely because those models agree with one another.
    inverse_quotes = 1.0 / source_quotes.to_numpy()
    independent_hpl = (inverse_quotes[1:] - inverse_quotes[:-1]) @ quantities
    row_indices = np.array([calendar_index[day] - 1 for day in frame["date"]])
    expected_hpl = independent_hpl[row_indices]
    if not np.allclose(frame["pnl_eur"], expected_hpl, rtol=1e-12, atol=1e-6):
        raise ValidationError("Prediction HPL differs from independent source-price cash repricing")
    if not np.allclose(frame["loss_eur"], -expected_hpl, rtol=1e-12, atol=1e-6):
        raise ValidationError(
            "Prediction losses differ from independent source-price cash repricing"
        )
    return frame, manifest


def validator_source_identity() -> dict[str, str]:
    """Source files that can affect the independently validated artifact."""
    return {
        name: sha256_file(Path(__file__).parent / name)
        for name in ("__init__.py", "data.py", "validation.py", "diagnostics.py")
    }


def load_validation_result(
    validation_path: str | Path, predictions: str | Path, manifest_path: str | Path | None = None
) -> tuple[dict, dict]:
    """Check the validation receipt before a report reads any conclusions.

    This is artifact/source consistency protection, not a signature. An attacker
    who rewrites all files and receipts is outside this unsigned integrity model.
    """
    validation_path, predictions = Path(validation_path), Path(predictions)
    receipt_path = validation_path.with_suffix(".receipt.json")
    if not receipt_path.is_file():
        raise ValidationError("Validation receipt missing; re-run independent validation")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema_version") != 1:
        raise ValidationError("Unsupported validation receipt schema")
    if receipt.get("validation_sha256") != sha256_file(validation_path):
        raise ValidationError("Validation result changed after validation: receipt hash mismatch")
    source_hashes = validator_source_identity()
    if receipt.get("validator_source_hashes") != source_hashes or receipt.get(
        "validator_source_sha256"
    ) != json_hash(source_hashes):
        raise ValidationError("Validator source changed; regenerate the validation artifact")
    manifest_path = (
        Path(manifest_path) if manifest_path else predictions.parent / "run_manifest.json"
    )
    if receipt.get("run_manifest_sha256") != sha256_file(manifest_path):
        raise ValidationError("Run manifest changed after validation")
    if receipt.get("predictions_sha256") != sha256_file(predictions):
        raise ValidationError("Validation receipt belongs to different predictions")
    result = json.loads(validation_path.read_text(encoding="utf-8"))
    frozen = json.loads(manifest_path.read_text(encoding="utf-8"))
    if result.get("schema_version") != 2:
        raise ValidationError("Unsupported validation result schema; re-run validation")
    for name in ("predictions_sha256", "protocol_sha256", "source_sha256", "model_source_sha256"):
        if result.get(name) != frozen.get(name) or receipt.get(name) != frozen.get(name):
            raise ValidationError(f"Validation evidence identity mismatch: {name}")
    if result.get("validator_source_sha256") != receipt["validator_source_sha256"]:
        raise ValidationError("Validation source identity differs from receipt")
    if result.get("run_manifest_sha256") != receipt["run_manifest_sha256"]:
        raise ValidationError("Validation manifest identity differs from receipt")
    diagnostics_path = validation_path.with_suffix(".diagnostics.json")
    if not diagnostics_path.is_file() or sha256_file(diagnostics_path) != result.get(
        "diagnostics_sha256"
    ):
        raise ValidationError("Descriptive diagnostics changed or missing; re-run validation")
    if receipt.get("diagnostics_sha256") != result["diagnostics_sha256"]:
        raise ValidationError("Descriptive diagnostics identity differs from receipt")
    return result, receipt


def check_contract(frame: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValidationError(f"Missing prediction columns: {sorted(missing)}")
    if frame.empty or frame.duplicated(["date", "model"]).any():
        raise ValidationError("Predictions are empty or date/model keys are duplicated")
    numeric = [
        "loss_eur",
        "pnl_eur",
        "var_975_eur",
        "es_975_eur",
        "var_99_eur",
        "initial_gross_eur",
    ]
    if not np.isfinite(frame[numeric].to_numpy(dtype=float)).all():
        raise ValidationError("Non-finite forecast or P&L values")
    if not np.allclose(frame["loss_eur"], -frame["pnl_eur"], rtol=1e-12, atol=1e-8):
        raise ValidationError("Loss/P&L signs disagree")
    if (frame[["var_975_eur", "es_975_eur", "var_99_eur", "initial_gross_eur"]] <= 0).any().any():
        raise ValidationError(
            "This nonzero cash book requires strictly positive tail risks and notional"
        )
    if (frame["es_975_eur"] + 1e-8 < frame["var_975_eur"]).any():
        raise ValidationError("ES must be >= VaR at the same confidence level")
    if (frame["var_99_eur"] + 1e-8 < frame["var_975_eur"]).any():
        raise ValidationError("99% VaR must be >= 97.5% VaR")
    if not set(frame["split"]).issubset({"development", "test"}):
        raise ValidationError("Unknown split")
    dates = pd.to_datetime(frame["date"], errors="raise")
    as_of = pd.to_datetime(frame["as_of"], errors="raise")
    if not (as_of < dates).all():
        raise ValidationError("Every forecast must be made strictly before the realised date")
    if not frame["history_end"].eq(frame["as_of"]).all():
        raise ValidationError("History end must equal the forecast's information date")
    if (pd.to_datetime(frame["history_start"]) > as_of).any():
        raise ValidationError("Invalid historical window")
    if any(
        frame[name].nunique() != 1
        for name in ("source_sha256", "protocol_sha256", "model_source_sha256", "initial_gross_eur")
    ):
        raise ValidationError("Mixed source/protocol/notional in forecast file")
    reference = None
    for _, group in frame.groupby("model", sort=True):
        if not pd.to_datetime(group["date"]).is_monotonic_increasing:
            raise ValidationError("Forecast dates must be increasing within each model")
        comparable = group[["date", "as_of", "split", "loss_eur"]].reset_index(drop=True)
        if reference is None:
            reference = comparable
        elif not comparable.equals(reference):
            raise ValidationError(
                "Models must be compared on identical dates, splits and realised HPL"
            )


def _bernoulli_log_likelihood(zeros: int, ones: int, p: float) -> float:
    return float(xlogy(ones, p) + xlogy(zeros, 1 - p))


def independence_lr(exceptions: np.ndarray) -> float | None:
    hit = np.asarray(exceptions, dtype=bool)
    if len(hit) < 3 or hit.sum() < 2 or (~hit).sum() < 2:
        return None
    prev, current = hit[:-1], hit[1:]
    n00 = int((~prev & ~current).sum())
    n01 = int((~prev & current).sum())
    n10 = int((prev & ~current).sum())
    n11 = int((prev & current).sum())
    if n00 + n01 == 0 or n10 + n11 == 0:
        return None
    p = (n01 + n11) / (len(hit) - 1)
    null = _bernoulli_log_likelihood(n00 + n10, n01 + n11, p)
    alternative = _bernoulli_log_likelihood(n00, n01, n01 / (n00 + n01))
    alternative += _bernoulli_log_likelihood(n10, n11, n11 / (n10 + n11))
    return max(0.0, 2 * (alternative - null))


def var_backtest(
    losses: np.ndarray,
    forecasts: np.ndarray,
    alpha: float,
    *,
    simulations: int = 2000,
    seed: int = 42,
) -> dict:
    hits = np.asarray(losses) > np.asarray(forecasts)
    n, k = len(hits), int(hits.sum())
    if n < 2 or not 0 < alpha < 1 or simulations < 1:
        raise ValueError("Need at least two observations, valid alpha and simulations >=1")
    q = 1 - alpha
    null = _bernoulli_log_likelihood(n - k, k, q)
    fitted = _bernoulli_log_likelihood(n - k, k, k / n)
    lr = max(0.0, 2 * (fitted - null))
    independence = independence_lr(hits)
    permutation_p = None
    if independence is not None:
        rng = np.random.default_rng(seed)
        at_least = 0
        # Condition on the observed count: under independent hits all arrangements
        # are equiprobable. This avoids trusting chi-square tails with sparse cells.
        for _ in range(simulations):
            shuffled = np.zeros(n, dtype=bool)
            shuffled[rng.choice(n, size=k, replace=False)] = True
            statistic = independence_lr(shuffled)
            if statistic is not None and statistic >= independence - 1e-12:
                at_least += 1
        permutation_p = (at_least + 1) / (simulations + 1)
    return {
        "alpha": alpha,
        "n": n,
        "exceptions": k,
        "expected_exceptions": n * q,
        "exception_rate": k / n,
        "rate_ci_95": [
            0.0 if k == 0 else float(beta.ppf(0.025, k, n - k + 1)),
            1.0 if k == n else float(beta.ppf(0.975, k + 1, n - k)),
        ],
        "coverage_exact_p": float(binomtest(k, n, q, alternative="two-sided").pvalue),
        "kupiec_lr": lr,
        "kupiec_asymptotic_p": float(chi2.sf(lr, 1)),
        "christoffersen_lr_independence": independence,
        "christoffersen_asymptotic_p": None
        if independence is None
        else float(chi2.sf(independence, 1)),
        "independence_permutation_p": permutation_p,
        "independence_status": "insufficient" if independence is None else "available",
        "conditional_permutations": simulations,
        "interpretation": "Non-rejection is not proof of calibration; few hits give low power.",
    }


def circular_block_means(
    values: np.ndarray, samples: int, block_length: int, seed: int
) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 2 or samples < 1 or block_length < 1 or block_length > n:
        raise ValueError("Invalid bootstrap sample count, length or block size")
    extended = np.concatenate((values, values[:block_length]))
    prefix = np.concatenate(([0.0], np.cumsum(extended)))
    starts = np.arange(n)
    complete = prefix[starts + block_length] - prefix[starts]
    blocks, remainder = divmod(n, block_length)
    partial = prefix[starts + remainder] - prefix[starts]
    rng = np.random.default_rng(seed)
    result = np.empty(samples)
    for first in range(0, samples, 128):
        size = min(128, samples - first)
        total = complete[rng.integers(0, n, size=(size, blocks))].sum(axis=1)
        if remainder:
            total += partial[rng.integers(0, n, size=size)]
        result[first : first + size] = total / n
    return result


def es_backtest(
    losses: np.ndarray,
    var: np.ndarray,
    es: np.ndarray,
    *,
    alpha: float = 0.975,
    samples: int = 5000,
    block_length: int = 20,
    seed: int = 42,
    min_tail: int = 20,
) -> dict:
    loss, v, e = (np.asarray(x, dtype=float) for x in (losses, var, es))
    if not (loss.shape == v.shape == e.shape) or not np.isfinite(e).all() or np.any(e <= 0):
        raise ValueError("ES test requires matching finite forecasts with positive ES")
    if not np.isfinite(loss).all() or not np.isfinite(v).all():
        raise ValueError("ES test inputs must be finite")
    hits = loss > v
    moments = loss * hits / ((1 - alpha) * e) - 1
    observed = float(moments.mean())
    tail_count = int(hits.sum())
    sufficient = tail_count >= min_tail and len(loss) >= block_length
    interval, p = None, None
    if sufficient:
        centered = circular_block_means(moments - observed, samples, block_length, seed)
        interval = np.quantile(centered + observed, [0.025, 0.975]).tolist()
        p = float((1 + np.count_nonzero(centered >= observed)) / (samples + 1))
    return {
        "method": "Acerbi-Szekely Z2 loss-sign moment with centered circular block bootstrap",
        "alpha": alpha,
        "n": len(loss),
        "tail_count": tail_count,
        "minimum_tail_count": min_tail,
        "moment": observed,
        "moment_ci_95": interval,
        "underestimation_p": p,
        "status": "available" if sufficient else "insufficient",
        "bootstrap_samples": samples,
        "block_length": block_length,
        "interpretation": (
            "Positive moment indicates tail loss above forecast. Inference is approximate, "
            "assumes sufficiently weak dependence/local stability, and is affected by VaR misspecification. "
            "It is not an ES-only guarantee or the original paper's exact simulation procedure."
        ),
    }


def fz0_scores(
    loss: np.ndarray, var: np.ndarray, es: np.ndarray, alpha: float = 0.975
) -> np.ndarray:
    loss, var, es = (np.asarray(x, dtype=float) for x in (loss, var, es))
    if np.any(es <= 0) or np.any(var <= 0) or np.any(es < var - 1e-12):
        raise ValueError("FZ0 requires 0 < VaR <= ES in the loss convention")
    return var / es + np.maximum(loss - var, 0) / ((1 - alpha) * es) + np.log(es) - 1


def pinball_scores(loss: np.ndarray, var: np.ndarray, alpha: float) -> np.ndarray:
    difference = np.asarray(loss) - np.asarray(var)
    return (alpha - (difference < 0)) * difference


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values, key=p_values.get)
    adjusted, previous = {}, 0.0
    for index, key in enumerate(ordered):
        previous = max(previous, (len(ordered) - index) * p_values[key])
        adjusted[key] = min(1.0, previous)
    return adjusted


def validate_predictions(
    frame: pd.DataFrame, *, samples: int = 5000, block_length: int = 20, seed: int = 42
) -> dict:
    check_contract(frame)
    if samples < 20 or block_length < 1:
        raise ValueError("Use >=20 bootstrap/permutation draws and a positive block length")
    output = {
        "schema_version": 2,
        "seed": seed,
        "bootstrap_samples": samples,
        "block_length": block_length,
        "significance_level": 0.05,
        "multiple_testing": "Holm within each split across available coverage/independence/ES hypotheses",
        "splits": {},
        "stress": [],
        "events": [],
        "limitations": [
            "Public reference-rate hypothetical P&L; no actual trading, bid/ask, funding or liquidity cost.",
            "No result is regulatory approval; non-rejection is not proof of a correct model.",
            "Long samples can hide regime-specific failures; short regimes have weak test power.",
            "Z2 bootstrap is approximate; a wrong VaR can distort the ES diagnostic.",
            "All model comparisons reuse the same fixed book; this does not demonstrate universal superiority.",
        ],
    }
    for split, split_frame in frame.groupby("split", sort=True):
        models, p_values = {}, {}
        for index, (name, group) in enumerate(split_frame.groupby("model", sort=True)):
            losses = group["loss_eur"].to_numpy()
            v975, e975, v99 = (
                group[c].to_numpy() for c in ("var_975_eur", "es_975_eur", "var_99_eur")
            )
            scale = group["initial_gross_eur"].to_numpy()
            model_seed = seed + index * 100
            result = {
                "n": len(group),
                "first_date": str(group["date"].iloc[0]),
                "last_date": str(group["date"].iloc[-1]),
                "var_975": var_backtest(losses, v975, 0.975, simulations=samples, seed=model_seed),
                "var_99": var_backtest(losses, v99, 0.99, simulations=samples, seed=model_seed + 1),
                "es_975": es_backtest(
                    losses,
                    v975,
                    e975,
                    samples=samples,
                    block_length=block_length,
                    seed=model_seed + 2,
                ),
                "scores": {
                    "fz0_mean": float(
                        fz0_scores(losses / scale, v975 / scale, e975 / scale).mean()
                    ),
                    "pinball_975_mean": float(
                        pinball_scores(losses / scale, v975 / scale, 0.975).mean()
                    ),
                    "pinball_99_mean": float(
                        pinball_scores(losses / scale, v99 / scale, 0.99).mean()
                    ),
                    "mean_var_99_eur": float(v99.mean()),
                    "mean_es_975_eur": float(e975.mean()),
                },
            }
            for label in ("var_975", "var_99"):
                p_values[f"{name}/{label}/coverage"] = result[label]["coverage_exact_p"]
                p = result[label]["independence_permutation_p"]
                if p is not None:
                    p_values[f"{name}/{label}/independence"] = p
            if result["es_975"]["underestimation_p"] is not None:
                p_values[f"{name}/es_975/underestimation"] = result["es_975"]["underestimation_p"]
            models[name] = result
        adjusted = holm_adjust(p_values)
        hypotheses = [
            {
                "name": key,
                "raw_p": p_values[key],
                "holm_p": adjusted[key],
                "reject": adjusted[key] < 0.05,
            }
            for key in sorted(p_values)
        ]
        for name, result in models.items():
            rejected = [
                row["name"]
                for row in hypotheses
                if row["name"].startswith(name + "/") and row["reject"]
            ]
            insufficient = result["es_975"]["status"] == "insufficient" or any(
                result[x]["independence_status"] == "insufficient" for x in ("var_975", "var_99")
            )
            result["rejected_hypotheses"] = rejected
            result["assessment"] = (
                "rejected" if rejected else "insufficient" if insufficient else "not_rejected"
            )
        output["splits"][split] = {
            "models": models,
            "hypotheses": hypotheses,
            "hypothesis_count": len(hypotheses),
        }
    development = output["splits"].get("development", {}).get("models", {})
    output["development_selected_model"] = (
        min(development, key=lambda name: (development[name]["scores"]["fz0_mean"], name))
        if development
        else None
    )
    output["selection_rule"] = (
        "Lowest development-period mean FZ0; held-out results never select or retune a model."
    )
    for year, label in (
        (2008, "GFC"),
        (2015, "CHF discontinuity"),
        (2020, "Pandemic"),
        (2022, "Rate reset"),
    ):
        window = frame.loc[frame["date"].str.startswith(str(year))]
        for name, group in window.groupby("model", sort=True):
            worst = group.loc[group["loss_eur"].idxmax()]
            output["stress"].append(
                {
                    "year": year,
                    "label": label,
                    "split": str(group["split"].iloc[0]),
                    "model": name,
                    "n": len(group),
                    "exceptions_99": int((group["loss_eur"] > group["var_99_eur"]).sum()),
                    "worst_loss_eur": float(worst["loss_eur"]),
                    "worst_date": str(worst["date"]),
                    "var_99_on_worst_day_eur": float(worst["var_99_eur"]),
                    "es_975_on_worst_day_eur": float(worst["es_975_eur"]),
                    "interpretation": "Predeclared calendar-year diagnostic; no short-window significance claim.",
                }
            )
    # The full-year worst loss is not the CHF event. A long CHF cash position can
    # gain on 2015-01-15; preserve the signed realised HPL instead of relabeling it.
    event_frame = frame.loc[frame["date"].between("2015-01-14", "2015-01-16")]
    for row in event_frame.itertuples():
        output["events"].append(
            {
                "event": "CHF floor removal: fixed 2015-01-14 to 2015-01-16 observation window",
                "date": row.date,
                "as_of": row.as_of,
                "model": row.model,
                "signed_hpl_eur": float(row.pnl_eur),
                "loss_eur": float(row.loss_eur),
                "var_99_eur": float(row.var_99_eur),
                "es_975_eur": float(row.es_975_eur),
                "exception_99": bool(row.loss_eur > row.var_99_eur),
            }
        )
    return output


def validate_file(
    predictions: str | Path,
    output_path: str | Path,
    *,
    manifest: str | Path | None = None,
    samples: int = 5000,
    block_length: int = 20,
    seed: int = 42,
) -> dict:
    frame, frozen = load_frozen_predictions(predictions, manifest)
    result = validate_predictions(frame, samples=samples, block_length=block_length, seed=seed)
    diagnostics = descriptive_diagnostics(
        frame, read_fx(frozen["source_path"]), frozen["holdings"], result["stress"]
    )
    diagnostics_path = Path(output_path).with_suffix(".diagnostics.json")
    write_json(diagnostics_path, diagnostics)
    result["diagnostics_sha256"] = sha256_file(diagnostics_path)
    result["predictions_sha256"] = frozen["predictions_sha256"]
    result["protocol_sha256"] = frozen["protocol_sha256"]
    result["source_sha256"] = frozen["source_sha256"]
    result["model_source_sha256"] = frozen["model_source_sha256"]
    source_hashes = validator_source_identity()
    result["validator_source_sha256"] = json_hash(source_hashes)
    manifest_path = Path(manifest) if manifest else Path(predictions).parent / "run_manifest.json"
    result["run_manifest_sha256"] = sha256_file(manifest_path)
    write_json(output_path, result)
    receipt = {
        "schema_version": 1,
        "kind": "unsigned_validation_integrity_receipt",
        "validation_sha256": sha256_file(output_path),
        "validator_source_hashes": source_hashes,
        "validator_source_sha256": result["validator_source_sha256"],
        "run_manifest_sha256": result["run_manifest_sha256"],
        **{
            name: result[name]
            for name in (
                "predictions_sha256",
                "protocol_sha256",
                "source_sha256",
                "model_source_sha256",
                "diagnostics_sha256",
            )
        },
        "validation_settings": {"samples": samples, "block_length": block_length, "seed": seed},
        "assurance": "Detects artifact/source inconsistencies; not a digital signature or hostile-rewrite protection.",
    }
    write_json(Path(output_path).with_suffix(".receipt.json"), receipt)
    return result
