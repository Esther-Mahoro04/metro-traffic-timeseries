import numpy as np
import pandas as pd

NUM = ["traffic_volume", "temp_k", "rain_1h", "snow_1h", "clouds_all"]
WEATHER = ["weather_main", "weather_description"]

def clean_traffic_data(df, max_gap=6):
    df = df.rename(columns={"date_time": "timestamp", "temp": "temp_k"})
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["holiday"] = df["holiday"].fillna("None")      # "None" is read as NaN by pandas
    df = df.drop_duplicates("timestamp").sort_values("timestamp").set_index("timestamp")

    df.loc[df["temp_k"] <= 0, "temp_k"] = np.nan
    df.loc[df["rain_1h"] > 500, "rain_1h"] = np.nan

    df = df.asfreq("h")
    df["is_imputed"] = df[NUM].isna().any(axis=1).astype(int)

    missing = df["traffic_volume"].isna()
    gap_size = missing.groupby((~missing).cumsum()).transform("sum")
    df = df[~(missing & (gap_size > max_gap))]

    df[NUM] = df[NUM].interpolate(method="time")
    df[WEATHER] = df[WEATHER].ffill()
    df["holiday"] = df["holiday"].fillna("None")      # filled hours are not holidays
    df = df.dropna()
    df["traffic_volume"] = df["traffic_volume"].round().astype(int)
    df["clouds_all"] = df["clouds_all"].round().astype(int)
    return df

def add_features(df):
    out = df.copy()
    out["hour"] = out.index.hour
    out["dayofweek"] = out.index.dayofweek
    out["month"] = out.index.month
    tv = df["traffic_volume"].asfreq("h")             # full grid: NaN where gaps were dropped
    for lag in (1, 24, 168):
        out[f"lag_{lag}"] = tv.shift(lag).reindex(out.index)
    past = tv.shift(1)
    out["ma_24"] = past.rolling(24).mean().reindex(out.index)
    out["ma_168"] = past.rolling(168).mean().reindex(out.index)
    out["is_holiday"] = (out["holiday"] != "None").groupby(out.index.date).transform("max").astype(int)
    return out
