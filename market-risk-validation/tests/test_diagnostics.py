from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_risk.diagnostics import descriptive_diagnostics
from market_risk.validation import fz0_scores


@pytest.fixture
def cash_replay():
    dates = pd.to_datetime(
        [
            "2014-12-30",
            "2014-12-31",
            "2015-01-02",
            "2015-01-12",
            "2015-01-14",
            "2015-01-15",
            "2015-01-16",
            "2015-01-19",
        ]
    )
    currencies = ["USD", "GBP", "JPY", "CHF", "AUD"]
    prices = pd.DataFrame(1.0, index=dates, columns=currencies)
    prices.loc["2015-01-15":, "CHF"] = [1.2, 1.18, 1.15]
    hpl = prices.diff().sum(axis=1) * 100
    rows = []
    for name, factor in (("historical", 1), ("ewma_gaussian", 2), ("ewma_fhs", 3)):
        for i, day in enumerate(dates[1:], 1):
            var = factor * (25 if day > pd.Timestamp("2015-01-15") else 5)
            rows.append(
                {
                    "date": day.strftime("%Y-%m-%d"),
                    "as_of": dates[i - 1].strftime("%Y-%m-%d"),
                    "model": name,
                    "split": "test",
                    "pnl_eur": hpl.loc[day],
                    "loss_eur": -hpl.loc[day],
                    "var_99_eur": var,
                    "var_975_eur": 0.8 * var,
                    "es_975_eur": 1.1 * var,
                    "initial_gross_eur": 500.0,
                }
            )
    return pd.DataFrame(rows), 1 / prices, {"foreign_units": dict.fromkeys(currencies, 100.0)}


def test_all_annual_cells_reconcile_to_full_observed_data(cash_replay):
    frame, quotes, holdings = cash_replay
    result = descriptive_diagnostics(frame, quotes, holdings, [])
    assert len(result["annual"]) == 2 * 3
    for model, group in frame.groupby("model"):
        cells = [row for row in result["annual"] if row["model"] == model]
        assert sum(row["n"] for row in cells) == len(group)
        assert sum(row["signed_hpl_eur"] for row in cells) == pytest.approx(group.pnl_eur.sum())
        assert (
            sum(row["exceptions_99"] for row in cells) == (group.loss_eur > group.var_99_eur).sum()
        )
        assert sum(row["sum_excess_99_eur"] for row in cells) == pytest.approx(
            np.maximum(group.loss_eur - group.var_99_eur, 0).sum()
        )
        expected_score = fz0_scores(
            group.loss_eur / 500, group.var_975_eur / 500, group.es_975_eur / 500
        ).mean()
        assert sum(row["n"] * row["fz0_mean"] for row in cells) / len(group) == pytest.approx(
            expected_score
        )
    assert all(row["es_tail_evidence"] == "insufficient" for row in result["annual"])
    assert "no fresh holdout" in result["status"]


def test_gain_and_next_forecast_are_not_relabelled_as_anchor_loss_or_foresight(cash_replay):
    frame, quotes, holdings = cash_replay
    result = descriptive_diagnostics(frame, quotes, holdings, [])
    event = result["events"][0]
    assert event["event_id"] == "chf_floor_2015"
    assert event["signed_hpl_eur"] == pytest.approx(20)
    assert event["currency_hpl_eur"]["CHF"] == pytest.approx(20)
    assert sum(event["currency_hpl_eur"].values()) == pytest.approx(event["signed_hpl_eur"])
    for model in event["models"]:
        assert model["anchor_as_of"] == "2015-01-14"
        assert model["next_date"] == "2015-01-16"
        assert model["next_as_of"] == "2015-01-15"
        assert model["next_to_anchor_var_ratio"] == pytest.approx(5)
        assert model["anchor_exception_99"] is False
        assert model["anchor_excess_99_eur"] == 0
        assert model["pre_n"] == 4 and model["post_n"] == 2
        assert model["window_status"] == "truncated"
    assert {row["date"] for row in event["series"] if row["relative_observation"] == 2} == {
        "2015-01-19"
    }
    assert not any(row["date"] == "2015-01-17" for row in event["series"])


def test_currency_attribution_independently_detects_wrong_unit(cash_replay):
    frame, quotes, holdings = cash_replay
    holdings["foreign_units"]["CHF"] *= 100
    with pytest.raises(ValueError, match="contributions do not reconstruct"):
        descriptive_diagnostics(frame, quotes, holdings, [])


def test_retrospective_worst_day_cannot_be_mislabeled_as_chf_anchor(cash_replay):
    frame, quotes, holdings = cash_replay
    result = descriptive_diagnostics(
        frame, quotes, holdings, [{"year": 2015, "worst_date": "2015-01-19"}]
    )
    event = result["events"][1]
    assert event["event_id"] == "worst_loss_2015"
    assert "Retrospective" in event["selection"]
    assert event["anchor_date"] == "2015-01-19"
    assert event["signed_hpl_eur"] == pytest.approx(-3)
    assert all(row["next_date"] is None and row["post_n"] == 0 for row in event["models"])
