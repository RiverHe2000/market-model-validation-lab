from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_risk.data import CURRENCIES


@pytest.fixture
def fx_file(tmp_path):
    dates = pd.bdate_range("2003-01-01", "2010-02-26")
    rng = np.random.default_rng(731)
    common = rng.normal(0, 0.003, (len(dates), 1))
    shocks = common + rng.normal(0, 0.006, (len(dates), 5))
    base = np.array([1.2, 0.8, 130.0, 1.5, 1.6])
    frame = pd.DataFrame(base * np.exp(np.cumsum(shocks, axis=0)), columns=CURRENCIES)
    frame.insert(0, "date", dates.strftime("%Y-%m-%d"))
    path = tmp_path / "fx.csv"
    frame.to_csv(path, index=False, float_format="%.17g")
    return path
