"""Forecast engines. The independent validator does not import this module.

Risk factors are simple returns on EUR prices of foreign-currency cash. For a
frozen cash book, current EUR holdings times these returns give exact cash HPL.
All three models see the same past observations and the same current holdings.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

MODEL_NAMES = ("historical", "ewma_gaussian", "ewma_fhs")


@dataclass(frozen=True)
class Forecast:
    var_975: float
    es_975: float
    var_99: float


def empirical_risk(losses: np.ndarray, alpha: float) -> tuple[float, float]:
    """Inverse empirical CDF and integrated upper-tail ES, including fractional mass."""
    values = np.asarray(losses, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("Loss scenarios must be a nonempty finite vector")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    ordered = np.sort(values)
    var = float(ordered[int(np.ceil(alpha * len(ordered))) - 1])
    mass = (1 - alpha) * len(ordered)
    if round(mass) >= 1 and np.isclose(mass, round(mass), atol=1e-10, rtol=0):
        mass = float(round(mass))
    whole = int(np.floor(mass))
    fraction = mass - whole
    total = float(ordered[-whole:].sum()) if whole else 0.0
    if fraction:
        total += fraction * float(ordered[-whole - 1])
    return var, total / mass


def scenario_forecast(losses: np.ndarray) -> Forecast:
    var, es = empirical_risk(losses, 0.975)
    var99, _ = empirical_risk(losses, 0.99)
    return Forecast(var, es, var99)


def ewma_states(
    returns: np.ndarray, decay: float = 0.94, initial_window: int = 250
) -> tuple[np.ndarray, np.ndarray]:
    """State[i] forecasts return[i] and uses only returns strictly before i.

    The first initial_window observations initialize a zero-mean second moment.
    Residual[i] divides return[i] by *its prior* volatility, never an ex-post one.
    """
    values = np.asarray(returns, dtype=float)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("Returns must be a finite matrix")
    if not 0 < decay < 1 or initial_window < 2 or len(values) <= initial_window:
        raise ValueError("Invalid EWMA initialization")
    count, assets = values.shape
    covariance = np.full((count, assets, assets), np.nan)
    residuals = np.full_like(values, np.nan)
    state = values[:initial_window].T @ values[:initial_window] / initial_window
    for i in range(initial_window, count):
        covariance[i] = state
        standard_deviation = np.sqrt(np.maximum(np.diag(state), 1e-18))
        residuals[i] = values[i] / standard_deviation
        state = decay * state + (1 - decay) * np.outer(values[i], values[i])
    return covariance, residuals


def forecast_models(
    history: np.ndarray,
    standardized_history: np.ndarray,
    covariance: np.ndarray,
    eur_holdings: np.ndarray,
) -> dict[str, Forecast]:
    if not all(
        np.isfinite(x).all() for x in (history, standardized_history, covariance, eur_holdings)
    ):
        raise ValueError("Forecast inputs must be finite and fully warmed up")
    if history.shape != standardized_history.shape:
        raise ValueError("FHS and HS must use the same joint historical observation window")
    historical_loss = -(history @ eur_holdings)
    variance = float(eur_holdings @ covariance @ eur_holdings)
    if variance < -1e-6:
        raise ValueError("EWMA covariance produced materially negative portfolio variance")
    sigma = np.sqrt(max(variance, 0.0))
    normal = Forecast(
        float(norm.ppf(0.975) * sigma),
        float(norm.pdf(norm.ppf(0.975)) / 0.025 * sigma),
        float(norm.ppf(0.99) * sigma),
    )
    shocks = standardized_history * np.sqrt(np.maximum(np.diag(covariance), 1e-18))
    if np.any(shocks <= -1):
        raise ValueError("FHS generated a cash-asset return <= -100%; no silent clipping")
    return {
        "historical": scenario_forecast(historical_loss),
        "ewma_gaussian": normal,
        "ewma_fhs": scenario_forecast(-(shocks @ eur_holdings)),
    }
