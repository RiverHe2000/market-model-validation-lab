"""Descriptive post-review diagnostics, without changing inference or model selection.

Calendar years are exhaustive. Event replay uses observed trading dates, never a
holiday fill, and keeps the pre-shock forecast separate from the next forecast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _summary(group: pd.DataFrame) -> dict:
    loss = group["loss_eur"].to_numpy()
    var = group["var_99_eur"].to_numpy()
    v975 = group["var_975_eur"].to_numpy()
    es = group["es_975_eur"].to_numpy()
    scale = group["initial_gross_eur"].to_numpy()
    tail_count = int((loss > v975).sum())
    excess = np.maximum(loss - var, 0)
    # Same proper score as the frozen validation, but this is a descriptive
    # annual average, not another hypothesis test or a new selection rule.
    score = v975 / es + np.maximum(loss - v975, 0) / (0.025 * es) + np.log(es / scale) - 1
    return {
        "n": len(group),
        "first_date": str(group["date"].iloc[0]),
        "last_date": str(group["date"].iloc[-1]),
        "exceptions_99": int((loss > var).sum()),
        "expected_exceptions_99": len(group) * 0.01,
        "exception_rate_99": float((loss > var).mean()),
        "tail_count_975": tail_count,
        "es_tail_evidence": "insufficient" if tail_count < 20 else "count_threshold_met_not_tested",
        "mean_var_99_eur": float(var.mean()),
        "mean_es_975_eur": float(es.mean()),
        "fz0_mean": float(score.mean()),
        "sum_excess_99_eur": float(excess.sum()),
        "max_excess_99_eur": float(excess.max()),
        "signed_hpl_eur": float(group["pnl_eur"].sum()),
    }


def descriptive_diagnostics(
    frame: pd.DataFrame, source_quotes: pd.DataFrame, holdings: dict, stress: list[dict]
) -> dict:
    """Derive review evidence from checked frozen forecasts and source cash prices.

    The caller verifies the frozen artifact contract. No forecast engine is used.
    Positive currency/portfolio HPL is a gain. Sum of excesses is a descriptive
    shortfall relative to daily VaR, not a capital amount or a hedging benefit.
    """
    frame = frame.sort_values(["date", "model"]).copy()
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    annual = [
        {"year": int(year), "split": str(split), "model": str(model), **_summary(group)}
        for (year, split, model), group in frame.groupby(["year", "split", "model"], sort=True)
    ]
    units = pd.Series(holdings["foreign_units"], dtype=float)
    currency_hpl = (1.0 / source_quotes).diff().mul(units, axis=1)
    anchors = [
        (
            "chf_floor_2015",
            "2015-01-15",
            "Original CHF anchor; +/-20-observation replay added after review",
        )
    ]
    years = sorted({entry["year"] for entry in stress})
    for year in years:
        candidates = [entry for entry in stress if entry["year"] == year]
        dates = {entry["worst_date"] for entry in candidates}
        if len(dates) != 1:
            raise ValueError("Stress models must share the same realised worst-loss date")
        anchors.append(
            (
                f"worst_loss_{year}",
                dates.pop(),
                "Retrospective worst loss within original stress year",
            )
        )
    dates = sorted(frame["date"].unique())
    events = []
    for event_id, day, selection in anchors:
        if day not in dates:
            continue
        anchor_index = dates.index(day)
        window_dates = dates[max(0, anchor_index - 20) : anchor_index + 21]
        anchor = frame.loc[frame["date"].eq(day)]
        contribution = currency_hpl.loc[day]
        actual_hpl = float(anchor["pnl_eur"].iloc[0])
        if not np.isclose(contribution.sum(), actual_hpl, rtol=1e-12, atol=1e-6):
            raise ValueError("Event currency contributions do not reconstruct frozen cash HPL")
        models, series = [], []
        for name, group in frame.loc[frame["date"].isin(window_dates)].groupby("model", sort=True):
            before, after = group.loc[group["date"] < day], group.loc[group["date"] > day]
            on_day = group.loc[group["date"].eq(day)].iloc[0]
            following = None if after.empty else after.iloc[0]
            record = {
                "model": str(name),
                "anchor_as_of": str(on_day["as_of"]),
                "anchor_var_99_eur": float(on_day["var_99_eur"]),
                "anchor_es_975_eur": float(on_day["es_975_eur"]),
                "anchor_exception_99": bool(on_day["loss_eur"] > on_day["var_99_eur"]),
                "anchor_excess_99_eur": float(max(on_day["loss_eur"] - on_day["var_99_eur"], 0)),
                "next_date": None if following is None else str(following["date"]),
                "next_as_of": None if following is None else str(following["as_of"]),
                "next_var_99_eur": None if following is None else float(following["var_99_eur"]),
                "next_to_anchor_var_ratio": None
                if following is None
                else float(following["var_99_eur"] / on_day["var_99_eur"]),
                "pre_n": len(before),
                "post_n": len(after),
                "pre_mean_var_99_eur": None if before.empty else float(before["var_99_eur"].mean()),
                "post_mean_var_99_eur": None if after.empty else float(after["var_99_eur"].mean()),
                "post_exceptions_99": int((after["loss_eur"] > after["var_99_eur"]).sum()),
                "post_sum_excess_99_eur": float(
                    np.maximum(after["loss_eur"] - after["var_99_eur"], 0).sum()
                ),
                "window_status": "complete" if len(before) == len(after) == 20 else "truncated",
            }
            models.append(record)
            for row in group.itertuples():
                series.append(
                    {
                        "model": str(name),
                        "date": row.date,
                        "as_of": row.as_of,
                        "relative_observation": dates.index(row.date) - anchor_index,
                        "signed_hpl_eur": float(row.pnl_eur),
                        "loss_eur": float(row.loss_eur),
                        "var_99_eur": float(row.var_99_eur),
                        "es_975_eur": float(row.es_975_eur),
                        "exception_99": bool(row.loss_eur > row.var_99_eur),
                    }
                )
        events.append(
            {
                "event_id": event_id,
                "anchor_date": day,
                "selection": selection,
                "split": str(anchor["split"].iloc[0]),
                "signed_hpl_eur": actual_hpl,
                "currency_hpl_eur": {key: float(value) for key, value in contribution.items()},
                "models": models,
                "series": series,
            }
        )
    return {
        "schema_version": 1,
        "kind": "post_review_descriptive_diagnostics",
        "status": "Existing inspected sample; no fresh holdout or new hypothesis tests",
        "calendar": "All observed years; event windows use up to 20 observations before/after, excluding anchor",
        "interpretation": [
            "Annual cells and event windows are descriptive, not additional model approvals.",
            "ES count threshold alone does not imply a test was performed or that ES is calibrated.",
            "Retrospective worst-day anchors are selected after observing losses, not forecast successes.",
            "A next-observation risk increase reacts to the anchor; it was unavailable to cover that anchor.",
            "Currency HPL contributions are cash accounting, not causal attribution or marginal VaR contributions.",
            "Excess sums are sums of positive daily loss-minus-VaR gaps, not capital or avoidable trading losses.",
        ],
        "annual": annual,
        "events": events,
    }
