# Task 4 — Prediction / Forecast Script

## Objective

Task 4 joins the earlier tasks into one working pipeline. The script `scripts/predict.py` gets its data only through the Task 3 API. That API reads the Task 2 databases. The script then applies the Task 1 preprocessing, loads the Task 1 model, and forecasts hourly traffic volume on I-94.

## Design

The code is split into three modules so each step can be tested on its own:

| Module | Responsibility |
| :-- | :-- |
| `src/api_client.py` | HTTP client for `GET /{sql,mongo}/observations/latest` and `/range`. Uses only the standard library and reports clear errors when the API is down or returns an error. |
| `src/forecasting.py` | Turns API records into a DataFrame, reuses `clean_traffic_data()` and `add_features()` from Task 1, loads the model, runs the one-step check and the recursive forecast. |
| `scripts/predict.py` | Command-line entry point. Runs the four steps, prints the results and saves CSV, JSON and PNG outputs. |
| `notebooks/task4_forecast.ipynb` | Colab notebook showing each step with explanations. It also installs MySQL and MongoDB, loads the data and starts the API inside Colab, so the whole pipeline runs with *Run all*. |

### Step 1 — Fetch from the API

The script first calls `/latest` to find the newest stored hour. It then calls `/range` for the 336 hours (14 days) ending at that hour. The minimum look-back is 168 hours, because the model's longest features, `lag_168` and `ma_168`, need the previous full week. `--source` chooses MySQL (`sql`), MongoDB (`mongo`) or `both`. Both databases return the same JSON shape, so the rest of the pipeline is identical. With `both`, the script also checks that the two forecasts match, which confirms that the databases are in sync.

### Step 2 — Preprocess with the Task 1 pipeline

The API records are flattened back into the raw Kaggle column layout (`date_time`, `temp`, `weather_main`, …). This lets the Task 1 functions run unchanged, with no second copy of the logic:

- `clean_traffic_data()` parses timestamps, removes sensor errors, regularises to an hourly grid, interpolates gaps of up to 6 hours and drops longer gaps.
- `add_features()` builds calendar features (`hour`, `dayofweek`, `month`, `is_holiday`), lag features (`lag_1`, `lag_24`, `lag_168`) and moving averages (`ma_24`, `ma_168`).

An automated test (`tests/test_forecasting.py`) checks that features built from API records equal the features built from the training CSV for the same hours.

### Step 3 — Load the trained model

`models/best_model.joblib` holds the tuned Random Forest from experiment 4 (`max_depth=12`, `max_features=0.5`, `n_estimators=100`; test RMSE 236, MAE 153). It is loaded with `joblib`. The script checks that the model's feature order matches `models/features.json` and stops if it does not.

### Step 4 — Predict and forecast

1. **One-step check:** each of the last 24 fetched hours is predicted from its real lags and compared with the actual values and with a seasonal-naive baseline (same hour last week).
2. **Next-hour forecast:** a feature row is built for the hour after the last record and passed to the model.
3. **Recursive multi-hour forecast** (default 24 h): each prediction is fed back in as `lag_1` and into the moving averages for the next hour.

Future weather is not stored, so temperature, rain, snow and cloud cover are carried forward from the last observed hour. A future date counts as a holiday only if the fetched history already flags it. These assumptions are written to the JSON output.

`--as-of` starts the forecast from a past hour. In that mode the script fetches the true values for the forecast window from the API and scores the forecast against them.

## Results

| Run | Result |
| :-- | :-- |
| Next-hour forecast, 2018-10-01 00:00 (Monday) | **537 vehicles/hour**, identical from MySQL and MongoDB |
| One-step check, last 24 fetched hours | MAE 119, RMSE 146 (baseline: MAE 224, RMSE 318) |
| 24-hour recursive forecast from 2018-09-23 23:00, vs actual | MAE 153, RMSE 180 |

The 24-hour forecast for Monday 1 October reproduces the expected weekday pattern: about 275 vehicles/hour at 2 a.m., a morning peak of about 6,440 at 7 a.m. and an evening peak of about 6,050 at 4 p.m. (`figures/12_forecast_sql.png`).

In the `--as-of` run (`figures/13_forecast_vs_actual_sql.png`), the 24-hour forecast error (MAE 153) equals the model's one-step test MAE (153). Feeding predictions back in therefore does not make errors grow quickly within a day. The largest misses are overestimates of about 330–350 vehicles/hour around the midday plateau (10:00 and 13:00) and about 260–290 late in the evening, plus an underestimate of 291 at the 7 a.m. peak.

## Error handling

- API unreachable or returning an error: the script prints the cause and how to start the API, then exits with code 1.
- Too little history, or a gap longer than 6 hours inside the needed week: the script names the feature that cannot be built and suggests a different `--as-of` time or a longer `--history-hours`.
- Invalid arguments (history under 168 hours, horizon outside 1–168): rejected by the argument parser.
- scikit-learn version different from training: a single note is printed. The required version is pinned in `requirements.txt`.

## How to run

In Google Colab: open `notebooks/task4_forecast.ipynb` and choose *Runtime → Run all*. On a computer with Docker:

```bash
docker compose up -d
python scripts/seed_databases.py
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
python scripts/predict.py --source both
python scripts/predict.py --as-of "2018-09-23 23:00:00"
python -m pytest tests
```
