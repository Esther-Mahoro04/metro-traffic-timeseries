import argparse
import os

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

MYSQL_URL = os.getenv("MYSQL_URL", "mysql+pymysql://root:password@localhost:3306/traffic_db")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "traffic_db")
MONGO_COLL = os.getenv("MONGO_COLLECTION", "traffic")
BATCH = 5000

REQUIRED = ["date_time", "holiday", "temp", "rain_1h", "snow_1h", "clouds_all",
            "weather_main", "weather_description", "traffic_volume", "is_imputed"]


def read_csv(path: str, raw: bool) -> pd.DataFrame:
    """Read the CSV and map it onto the column names used by the database."""
    df = pd.read_csv(path)
    df = df.rename(columns={"timestamp": "date_time", "temp_k": "temp"})
    df["date_time"] = pd.to_datetime(df["date_time"])
    df["holiday"] = df["holiday"].fillna("None")
    # MySQL compares text case-insensitively, so 'Sky is Clear' and 'sky is clear' would collide
    # in the weather_conditions lookup. Normalise so both databases hold identical values.
    for c in ["weather_main", "weather_description", "holiday"]:
        df[c] = df[c].str.strip()
    df["weather_description"] = df["weather_description"].str.lower()
    if raw:
        df = clean_raw(df)
        df["is_imputed"] = 0
    if "is_imputed" not in df.columns:
        df["is_imputed"] = 0
    missing = [c for c in REQUIRED if c not in df.columns]
    assert not missing, f"CSV is missing columns: {missing}"
    df = df[REQUIRED].sort_values("date_time").reset_index(drop=True)
    assert df["date_time"].is_unique, "date_time must be unique before loading"
    assert not df.isna().any().any(), f"NaN values found:\n{df.isna().sum()}"
    return df


def clean_raw(df: pd.DataFrame) -> pd.DataFrame:
    """Only used with --raw (original Kaggle file). Not needed for the Task 1 cleaned CSV."""
    before = len(df)
    df = df.sort_values("date_time").drop_duplicates(subset="date_time", keep="first")
    print(f"[clean] dropped {before - len(df)} duplicate timestamps")
    bad = (df["temp"] <= 0) | (df["rain_1h"] > 1000)
    print(f"[clean] dropped {int(bad.sum())} outlier rows (temp<=0 K or rain_1h>1000)")
    return df[~bad]


def load_sql(df: pd.DataFrame) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(MYSQL_URL)
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for t in ["weather_readings", "traffic_observations", "weather_conditions", "holidays"]:
            conn.execute(text(f"TRUNCATE TABLE {t}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))

        pd.DataFrame({"holiday_name": df["holiday"].unique()}).to_sql(
            "holidays", conn, if_exists="append", index=False)
        df[["weather_main", "weather_description"]].drop_duplicates().to_sql(
            "weather_conditions", conn, if_exists="append", index=False)

        hol_map = pd.read_sql("SELECT holiday_id, holiday_name FROM holidays", conn)
        wc_map = pd.read_sql("SELECT * FROM weather_conditions", conn)

        obs = df.merge(hol_map, left_on="holiday", right_on="holiday_name")[
            ["date_time", "traffic_volume", "holiday_id", "is_imputed"]]
        obs.to_sql("traffic_observations", conn, if_exists="append", index=False,
                   chunksize=BATCH, method="multi")
        obs_map = pd.read_sql("SELECT obs_id, date_time FROM traffic_observations", conn)

        wr = (df.merge(obs_map, on="date_time")
                .merge(wc_map, on=["weather_main", "weather_description"])
              [["obs_id", "weather_id", "temp", "rain_1h", "snow_1h", "clouds_all"]])
        wr.to_sql("weather_readings", conn, if_exists="append", index=False,
                  chunksize=BATCH, method="multi")
    print(f"[sql] loaded {len(obs)} observations")


def load_mongo(df: pd.DataFrame) -> None:
    from pymongo import MongoClient

    db = MongoClient(MONGO_URI)[MONGO_DB]
    if MONGO_COLL in db.list_collection_names():
        db[MONGO_COLL].drop()  # re-create so the time-series options are applied cleanly
    try:
        db.create_collection(MONGO_COLL, timeseries={"timeField": "date_time", "granularity": "hours"})
        print("[mongo] created time-series collection")
    except Exception as e:  # MongoDB < 5.0: regular collection + unique index
        print(f"[mongo] time-series unsupported ({e}); using regular collection")
        db.create_collection(MONGO_COLL)
        db[MONGO_COLL].create_index("date_time", unique=True)
    coll = db[MONGO_COLL]

    docs = [
        {
            "date_time": r.date_time.to_pydatetime(),
            "traffic_volume": int(r.traffic_volume),
            "holiday": r.holiday,
            "is_imputed": bool(r.is_imputed),
            "weather": {
                "temp": float(r.temp), "rain_1h": float(r.rain_1h), "snow_1h": float(r.snow_1h),
                "clouds_all": int(r.clouds_all), "main": r.weather_main,
                "description": r.weather_description,
            },
        }
        for r in df.itertuples(index=False)
    ]
    for i in range(0, len(docs), BATCH):
        coll.insert_many(docs[i:i + BATCH])
    print(f"[mongo] loaded {len(docs)} documents")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--raw", action="store_true", help="CSV is the original Kaggle file (applies basic cleaning)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only", choices=["sql", "mongo"])
    a = p.parse_args()

    df = read_csv(a.csv, a.raw)
    print(f"[data] {len(df)} rows, {df['date_time'].min()} -> {df['date_time'].max()}, "
          f"{int(df['is_imputed'].sum())} imputed")
    if a.dry_run:
        return
    if a.only != "mongo":
        load_sql(df)
    if a.only != "sql":
        load_mongo(df)


if __name__ == "__main__":
    main()
