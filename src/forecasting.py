"""Task 4 forecasting logic, kept separate from HTTP and printing so it can be tested.

Pipeline:
    API records (JSON)  ->  raw-dataset DataFrame  ->  clean_traffic_data()   (Task 1)
                        ->  add_features()  (Task 1: calendar, lags 1/24/168, MA 24/168)
                        ->  trained Random Forest (models/best_model.joblib)  ->  forecast

The preprocessing functions are imported from src/preprocessing.py, the same
module used to train the model, so features are built exactly as in Task 1.
"""

import json
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.preprocessing import add_features, clean_traffic_data

# The longest look-back used by the model: lag_168 and the 168-hour moving average
# both need the previous full week of hourly values.
MIN_HISTORY_HOURS = 168

# Exogenous columns that are unknown for future hours. They are carried forward
# from the last observed hour (a persistence assumption, stated in the output).
WEATHER_CARRY = ["temp_k", "rain_1h", "snow_1h", "clouds_all", "weather_main", "weather_description"]


# --------------------------------------------------------------------------- #
# 1. API records -> DataFrame
# --------------------------------------------------------------------------- #
def records_to_raw_frame(records: list[dict]) -> pd.DataFrame:
    """Flatten API records back into the column layout of the original Kaggle CSV.

    Doing this lets the Task 1 cleaning function run unchanged on API data.
    """
    if not records:
        raise ValueError("The API returned no records for the requested window.")
    rows = [
        {
            "holiday": rec["holiday"],
            "temp": rec["weather"]["temp"],
            "rain_1h": rec["weather"]["rain_1h"],
            "snow_1h": rec["weather"]["snow_1h"],
            "clouds_all": rec["weather"]["clouds_all"],
            "weather_main": rec["weather"]["main"],
            "weather_description": rec["weather"]["description"],
            "date_time": rec["date_time"],
            "traffic_volume": rec["traffic_volume"],
        }
        for rec in records
    ]
    return pd.DataFrame(rows)


def preprocess(records: list[dict]) -> pd.DataFrame:
    """Apply the Task 1 cleaning pipeline to records fetched from the API.

    clean_traffic_data() parses timestamps, removes sensor errors (temp <= 0 K,
    rain > 500 mm), regularises to an hourly grid, interpolates short gaps
    (<= 6 h) and drops long ones, exactly as during training.
    """
    raw = records_to_raw_frame(records)
    return clean_traffic_data(raw)


# --------------------------------------------------------------------------- #
# 2. Model loading
# --------------------------------------------------------------------------- #
def load_model(model_dir: Path):
    """Load the tuned model and its feature list. Returns (model, features, target, notes)."""
    model_dir = Path(model_dir)
    meta = json.loads((model_dir / "features.json").read_text())
    notes = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = joblib.load(model_dir / "best_model.joblib")
    if any("InconsistentVersion" in type(w.message).__name__ for w in caught):
        notes.append(
            "scikit-learn version differs from the one used for training (1.6.1); "
            "install scikit-learn==1.6.1 to silence this."
        )

    features = meta["features"]
    trained_on = list(getattr(model, "feature_names_in_", features))
    if trained_on != features:
        raise ValueError(f"features.json {features} does not match the model {trained_on}")
    return model, features, meta["target"], notes


# --------------------------------------------------------------------------- #
# 3. Predictions
# --------------------------------------------------------------------------- #
def check_history(clean: pd.DataFrame) -> None:
    """Make sure the last week is complete enough to build every lag/MA feature."""
    if len(clean) < MIN_HISTORY_HOURS:
        raise ValueError(
            f"Need at least {MIN_HISTORY_HOURS} hourly records after cleaning, got {len(clean)}. "
            "Fetch a longer history (--history-hours)."
        )


def one_step_backtest(clean: pd.DataFrame, model, features: list[str], hours: int) -> pd.DataFrame:
    """Predict each of the last `hours` fetched hours from its real lags, compare to actuals.

    This shows how accurate the model is on the data that just came from the API.
    The seasonal-naive baseline (same hour last week, lag_168) is included for context.
    """
    feats = add_features(clean).dropna(subset=features)
    window = feats.iloc[-hours:]
    if window.empty:
        return pd.DataFrame(columns=["actual", "predicted", "baseline_lag168", "error"])
    out = pd.DataFrame(index=window.index)
    out["actual"] = window["traffic_volume"].astype(float)
    out["predicted"] = np.clip(model.predict(window[features]), 0, None)
    out["baseline_lag168"] = window["lag_168"]
    out["error"] = out["actual"] - out["predicted"]
    out.index.name = "timestamp"
    return out


def recursive_forecast(clean: pd.DataFrame, model, features: list[str], horizon: int) -> pd.DataFrame:
    """Forecast `horizon` hours after the last fetched record.

    Step 1 uses only observed traffic. For steps 2+, the previous prediction is
    fed back in as lag_1 / moving-average input (recursive multi-step forecast).
    Calendar features are exact; weather is carried forward from the last
    observed hour; a future hour is a holiday only if its date is already
    flagged as one in the fetched history.
    """
    check_history(clean)
    history = clean.copy()
    history["traffic_volume"] = history["traffic_volume"].astype(float)
    last = history.iloc[-1]
    holiday_dates = set(history.index[history["holiday"] != "None"].date)

    rows = []
    for step in range(1, horizon + 1):
        ts = history.index[-1] + pd.Timedelta(hours=1)
        future = {col: last[col] for col in WEATHER_CARRY}
        future.update(
            holiday="Holiday (from history)" if ts.date() in holiday_dates else "None",
            traffic_volume=np.nan,
            is_imputed=0,
        )
        history = pd.concat([history, pd.DataFrame([future], index=pd.DatetimeIndex([ts]))])

        x = add_features(history).loc[[ts], features]
        if x.isna().any(axis=None):
            missing = x.columns[x.isna().any()].tolist()
            raise ValueError(
                f"Cannot build {missing} for {ts}: the week before it has a gap longer than "
                "6 hours. Choose another --as-of time or fetch more history."
            )
        y_hat = float(np.clip(model.predict(x)[0], 0, None))
        history.loc[ts, "traffic_volume"] = y_hat
        rows.append({"timestamp": ts, "step": step, "predicted": round(y_hat), **x.iloc[0].to_dict()})

    return pd.DataFrame(rows).set_index("timestamp")


def metrics(actual: pd.Series, predicted: pd.Series) -> dict:
    err = (actual - predicted).dropna()
    if err.empty:
        return {"n": 0, "mae": None, "rmse": None}
    return {
        "n": int(err.count()),
        "mae": round(float(err.abs().mean()), 1),
        "rmse": round(float(np.sqrt((err**2).mean())), 1),
    }
