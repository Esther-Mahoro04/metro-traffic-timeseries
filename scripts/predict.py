"""Task 4: fetch -> preprocess -> load model -> forecast.

End-to-end forecast of I-94 hourly traffic volume using the Task 3 API as the
only data source.

  1. Fetch    the latest record and the preceding history from the API
              (MySQL, MongoDB, or both).
  2. Preprocess with the Task 1 pipeline (src/preprocessing.py): cleaning,
              hourly regularisation, gap handling, calendar features,
              lag_1/24/168 and 24 h / 168 h moving averages.
  3. Load     the tuned Random Forest (models/best_model.joblib, experiment 4).
  4. Predict  the next hour, plus a recursive multi-hour forecast, and score the
              model on the most recent fetched hours.

Start the API first (see README), then for example:

    python scripts/predict.py                                  # MySQL, next 24 h
    python scripts/predict.py --source mongo
    python scripts/predict.py --source both                    # both DBs, checks they agree
    python scripts/predict.py --as-of "2018-09-23 23:00:00"   # forecast a past week, compare to actuals

Outputs go to results/ (CSV + JSON) and figures/ (PNG).
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.api_client import STORES, ApiError, TrafficApiClient  # noqa: E402
from src.forecasting import (  # noqa: E402
    MIN_HISTORY_HOURS,
    check_history,
    load_model,
    metrics,
    one_step_backtest,
    preprocess,
    recursive_forecast,
)

STAMP = "%Y-%m-%d %H:%M:%S"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Task 4 traffic-volume forecast from the Task 3 API.")
    p.add_argument("--api-url", default="http://127.0.0.1:8000", help="Base URL of the Task 3 API.")
    p.add_argument("--source", choices=["sql", "mongo", "both"], default="sql",
                   help="Which database endpoint to read from (default: sql).")
    p.add_argument("--as-of", default=None,
                   help="Forecast from this hour instead of the latest record "
                        "(YYYY-MM-DD HH:MM:SS). Useful for checking against known actuals.")
    p.add_argument("--horizon", type=int, default=24, help="Hours to forecast ahead (default 24).")
    p.add_argument("--history-hours", type=int, default=336,
                   help="Hours of history to fetch (default 336 = 14 days, minimum 168).")
    p.add_argument("--backtest-hours", type=int, default=24,
                   help="Recent fetched hours to score one-step-ahead (default 24).")
    p.add_argument("--model-dir", default=str(ROOT / "models"))
    p.add_argument("--no-plot", action="store_true", help="Skip writing the PNG figure.")
    args = p.parse_args()
    if args.history_hours < MIN_HISTORY_HOURS:
        p.error(f"--history-hours must be at least {MIN_HISTORY_HOURS} (lag_168 / ma_168).")
    if not 1 <= args.horizon <= 168:
        p.error("--horizon must be between 1 and 168.")
    return args


def banner(text: str) -> None:
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


# --------------------------------------------------------------------------- #
# Step 1: fetch
# --------------------------------------------------------------------------- #
def fetch(client: TrafficApiClient, store: str, as_of: str | None, history_hours: int):
    latest = client.latest(store)
    print(f"  GET /{store}/observations/latest -> {latest['date_time']} "
          f"(traffic_volume={latest['traffic_volume']}, id={latest['id']})")

    latest_at = datetime.strptime(latest["date_time"], STAMP)
    end = latest_at if as_of is None else pd.Timestamp(as_of).to_pydatetime()
    if end > latest_at:
        raise ValueError(f"--as-of {end} is after the latest stored record ({latest_at}).")
    start = end - timedelta(hours=history_hours - 1)

    records = client.date_range(store, start, end)
    print(f"  GET /{store}/observations/range?start={start:{STAMP}}&end={end:{STAMP}} "
          f"-> {len(records)} records")
    if not records:
        raise ValueError("No records in that window.")
    return records, end, latest_at


# --------------------------------------------------------------------------- #
# Full pipeline for one database
# --------------------------------------------------------------------------- #
def run(store: str, args, client: TrafficApiClient, model, features, target) -> dict:
    banner(f"Source: {STORES[store]}  (/{store}/observations)")

    print("[1/4] Fetching records from the API")
    records, as_of, latest_at = fetch(client, store, args.as_of, args.history_hours)

    print("[2/4] Preprocessing with the Task 1 pipeline")
    clean = preprocess(records)
    imputed = int(clean["is_imputed"].sum())
    print(f"  {len(records)} records -> {len(clean)} clean hourly rows "
          f"({clean.index.min()} to {clean.index.max()}), {imputed} interpolated")
    print(f"  Features: {', '.join(features)}")
    check_history(clean)

    print("[3/4] Model loaded")
    print(f"  {type(model).__name__}(n_estimators={model.n_estimators}, max_depth={model.max_depth}, "
          f"max_features={model.max_features}), target='{target}'")

    print("[4/4] Predicting")
    backtest = one_step_backtest(clean, model, features, args.backtest_hours)
    bt_model = metrics(backtest["actual"], backtest["predicted"])
    bt_base = metrics(backtest["actual"], backtest["baseline_lag168"])
    if bt_model["n"]:
        print(f"  One-step check on the last {bt_model['n']} fetched hours: "
              f"MAE {bt_model['mae']}, RMSE {bt_model['rmse']} "
              f"(seasonal-naive lag_168: MAE {bt_base['mae']}, RMSE {bt_base['rmse']})")
    else:
        print("  One-step check skipped: no recent hour has a complete week of history.")

    forecast = recursive_forecast(clean, model, features, args.horizon)
    first = forecast.iloc[0]
    print(f"\n  >>> Next-hour forecast for {forecast.index[0]}: "
          f"{int(first['predicted'])} vehicles/hour <<<")

    # If we forecast from a past point, the API already holds the true values: compare.
    actual_cmp = None
    if as_of < latest_at:
        future = client.date_range(store, forecast.index[0].to_pydatetime(),
                                   forecast.index[-1].to_pydatetime())
        actual = pd.Series({pd.Timestamp(r["date_time"]): r["traffic_volume"] for r in future},
                           dtype=float)
        forecast["actual"] = actual.reindex(forecast.index)
        if forecast["actual"].notna().any():
            actual_cmp = metrics(forecast["actual"], forecast["predicted"])
            print(f"  Forecast vs actual over {actual_cmp['n']} h: "
                  f"MAE {actual_cmp['mae']}, RMSE {actual_cmp['rmse']}")

    show = forecast[["predicted"] + (["actual"] if "actual" in forecast else [])].copy()
    show.insert(0, "day", show.index.day_name().str[:3])
    print(f"\n  {args.horizon}-hour forecast:")
    print(show.to_string(float_format=lambda v: f"{v:.0f}"))

    # ---- save outputs ----
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    # Forecasts from the latest record and checks against a past date get separate files.
    stem = f"task4_forecast_{store}" if as_of == latest_at else f"task4_backtest_{store}_{as_of:%Y%m%d_%H}"
    csv_path = results_dir / f"{stem}.csv"
    forecast.to_csv(csv_path)
    summary = {
        "source": STORES[store],
        "api_url": args.api_url,
        "run_at": datetime.now().strftime(STAMP),
        "as_of": as_of.strftime(STAMP),
        "records_fetched": len(records),
        "rows_after_cleaning": len(clean),
        "model": "RandomForestRegressor (tuned, experiment 4)",
        "next_hour": {"timestamp": forecast.index[0].strftime(STAMP),
                      "predicted_traffic_volume": int(first["predicted"])},
        "horizon_hours": args.horizon,
        "forecast": [{"timestamp": ts.strftime(STAMP), "predicted": int(v)}
                     for ts, v in forecast["predicted"].items()],
        "backtest_last_hours": {"model": bt_model, "seasonal_naive_lag168": bt_base},
        "forecast_vs_actual": actual_cmp,
        "assumptions": [
            "Future weather (temp, rain, snow, clouds) is carried forward from the last observed hour.",
            "A future date is treated as a holiday only if it is already flagged in the fetched history.",
            "Steps beyond the first hour feed earlier predictions back in as lag/moving-average inputs.",
        ],
    }
    json_path = results_dir / f"{stem}.json"
    json_path.write_text(json.dumps(summary, indent=2))
    print(f"\n  Saved {csv_path.relative_to(ROOT)} and {json_path.relative_to(ROOT)}")

    if not args.no_plot:
        png = plot(clean, backtest, forecast, store, as_of,
                   "12_forecast" if as_of == latest_at else "13_forecast_vs_actual")
        print(f"  Saved {png.relative_to(ROOT)}")
    return summary


def plot(clean, backtest, forecast, store: str, as_of, name: str) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    recent = clean["traffic_volume"].iloc[-72:]
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(recent.index, recent.values, color="#333333", lw=1.6, label="Observed (from API)")
    ax.plot(backtest.index, backtest["predicted"], color="#2a7ab0", lw=1.2, ls="--",
            label="One-step prediction (recent hours)")
    ax.plot(forecast.index, forecast["predicted"], color="#d1495b", lw=2, marker="o", ms=3,
            label=f"Forecast (next {len(forecast)} h)")
    if "actual" in forecast:
        ax.plot(forecast.index, forecast["actual"], color="#333333", lw=1.2, alpha=0.5,
                label="Actual (held in DB)")
    ax.axvline(as_of, color="grey", lw=1, ls=":")
    ax.set_title(f"Task 4 forecast of I-94 hourly traffic volume — source: {STORES[store]}")
    ax.set_ylabel("Vehicles per hour")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=4, fontsize=9, frameon=False)
    fig.autofmt_xdate()
    fig.tight_layout()
    out = ROOT / "figures" / f"{name}_{store}.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def main() -> int:
    args = parse_args()
    client = TrafficApiClient(args.api_url)
    try:
        model, features, target, notes = load_model(Path(args.model_dir))
    except FileNotFoundError as exc:
        print(f"Model files not found: {exc}", file=sys.stderr)
        return 1
    for note in notes:
        print(f"Note: {note}")

    stores = ["sql", "mongo"] if args.source == "both" else [args.source]
    summaries = {}
    try:
        health = client.health()
        print(f"API health: {health}")
        for store in stores:
            summaries[store] = run(store, args, client, model, features, target)
    except (ApiError, ValueError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    if len(summaries) == 2:
        a = [f["predicted"] for f in summaries["sql"]["forecast"]]
        b = [f["predicted"] for f in summaries["mongo"]["forecast"]]
        verdict = "identical" if a == b else "DIFFERENT (the two databases are out of sync)"
        banner(f"MySQL and MongoDB forecasts are {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
