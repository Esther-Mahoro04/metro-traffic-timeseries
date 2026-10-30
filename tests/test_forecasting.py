"""Offline tests for the Task 4 pipeline (no API or database needed).

Records are built from data/traffic_clean.csv in the exact JSON shape the API
returns (api/schemas.py: ObservationOut). Run with:  python -m pytest tests
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.forecasting import (  # noqa: E402
    load_model,
    one_step_backtest,
    preprocess,
    recursive_forecast,
)
from src.preprocessing import add_features  # noqa: E402


def api_records(start: str, end: str) -> list[dict]:
    df = pd.read_csv(ROOT / "data" / "traffic_clean.csv", parse_dates=["timestamp"])
    df = df[(df.timestamp >= start) & (df.timestamp <= end)]
    return [
        {
            "id": i,
            "date_time": r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "traffic_volume": int(r.traffic_volume),
            "holiday": r.holiday if isinstance(r.holiday, str) else "None",
            "is_imputed": bool(r.is_imputed),
            "weather": {"temp": r.temp_k, "rain_1h": r.rain_1h, "snow_1h": r.snow_1h,
                        "clouds_all": int(r.clouds_all), "main": r.weather_main,
                        "description": r.weather_description},
        }
        for i, r in enumerate(df.itertuples(), 1)
    ]


@pytest.fixture(scope="module")
def model_bundle():
    return load_model(ROOT / "models")


@pytest.fixture(scope="module")
def clean():
    return preprocess(api_records("2018-09-10 00:00:00", "2018-09-23 23:00:00"))


def test_api_records_match_training_features(clean):
    """Features built from API records equal those built from the training CSV."""
    full = pd.read_csv(ROOT / "data" / "traffic_clean.csv", parse_dates=["timestamp"],
                       index_col="timestamp")
    full["holiday"] = full["holiday"].fillna("None")
    expected = add_features(full).loc[clean.index[-24:]]
    got = add_features(clean).loc[clean.index[-24:]]
    cols = ["lag_1", "lag_24", "lag_168", "ma_24", "ma_168", "hour", "dayofweek", "temp_k"]
    pd.testing.assert_frame_equal(got[cols], expected[cols], check_dtype=False, check_freq=False)


def test_backtest_beats_seasonal_naive(clean, model_bundle):
    model, features, _, _ = model_bundle
    bt = one_step_backtest(clean, model, features, 24)
    assert len(bt) == 24
    model_mae = (bt.actual - bt.predicted).abs().mean()
    naive_mae = (bt.actual - bt.baseline_lag168).abs().mean()
    assert model_mae < naive_mae


def test_recursive_forecast_shape_and_values(clean, model_bundle):
    model, features, _, _ = model_bundle
    fc = recursive_forecast(clean, model, features, horizon=24)
    assert len(fc) == 24
    assert fc.index[0] == clean.index[-1] + pd.Timedelta(hours=1)
    assert (fc.index.to_series().diff().dropna() == pd.Timedelta(hours=1)).all()
    assert fc.predicted.between(0, 8000).all()
    assert fc[features].notna().all(axis=None)
    # Monday-morning rush hour should be far busier than 3 a.m.
    assert fc.loc["2018-09-24 07:00"].predicted > 4 * fc.loc["2018-09-24 03:00"].predicted


def test_short_history_is_rejected(model_bundle):
    model, features, _, _ = model_bundle
    short = preprocess(api_records("2018-09-23 00:00:00", "2018-09-23 23:00:00"))
    with pytest.raises(ValueError, match="at least 168"):
        recursive_forecast(short, model, features, horizon=1)
