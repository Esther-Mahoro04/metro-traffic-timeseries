"""SQL CRUD against the four-table schema in sql/schema.sql.

Lookups (holidays, weather_conditions) are shared. Creating an observation
inserts those rows only when the name or weather pair is new, then links the
hourly observation to them.
"""

from datetime import datetime

import pymysql

from api.errors import Conflict, NotFound
from api.schemas import ObservationIn

SELECT_OBSERVATION = """
SELECT
    o.obs_id,
    o.date_time,
    o.traffic_volume,
    o.is_imputed,
    h.holiday_name AS holiday,
    r.temp,
    r.rain_1h,
    r.snow_1h,
    r.clouds_all,
    wc.weather_main,
    wc.weather_description
FROM traffic_observations o
JOIN holidays h ON h.holiday_id = o.holiday_id
JOIN weather_readings r ON r.obs_id = o.obs_id
JOIN weather_conditions wc ON wc.weather_id = r.weather_id
"""


def to_record(row: dict) -> dict:
    moment = row["date_time"]
    if isinstance(moment, datetime):
        moment = moment.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "id": row["obs_id"],
        "date_time": moment,
        "traffic_volume": int(row["traffic_volume"]),
        "holiday": row["holiday"],
        "is_imputed": bool(row["is_imputed"]),
        "weather": {
            "temp": float(row["temp"]),
            "rain_1h": float(row["rain_1h"]),
            "snow_1h": float(row["snow_1h"]),
            "clouds_all": int(row["clouds_all"]),
            "main": row["weather_main"],
            "description": row["weather_description"],
        },
    }


def _lookup_holiday(cursor, name: str) -> int:
    cursor.execute(
        """
        INSERT INTO holidays (holiday_name)
        VALUES (%s)
        ON DUPLICATE KEY UPDATE holiday_id = LAST_INSERT_ID(holiday_id)
        """,
        (name,),
    )
    return cursor.lastrowid


def _lookup_weather(cursor, weather) -> int:
    cursor.execute(
        """
        INSERT INTO weather_conditions (weather_main, weather_description)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE weather_id = LAST_INSERT_ID(weather_id)
        """,
        (weather.main, weather.description),
    )
    return cursor.lastrowid


def _one(cursor, clause: str, params: tuple) -> dict | None:
    cursor.execute(SELECT_OBSERVATION + " " + clause, params)
    row = cursor.fetchone()
    return to_record(row) if row else None


def fetch_by_id(connection, obs_id: int) -> dict:
    with connection.cursor() as cursor:
        record = _one(cursor, "WHERE o.obs_id = %s", (obs_id,))
    if record is None:
        raise NotFound(f"No MySQL observation with id {obs_id}")
    return record


def fetch_latest(connection) -> dict:
    with connection.cursor() as cursor:
        record = _one(cursor, "ORDER BY o.date_time DESC LIMIT 1", ())
    if record is None:
        raise NotFound("No MySQL observations stored")
    return record


def fetch_range(connection, start: datetime, end: datetime, limit: int) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            SELECT_OBSERVATION
            + """
            WHERE o.date_time BETWEEN %s AND %s
            ORDER BY o.date_time
            LIMIT %s
            """,
            (start, end, limit),
        )
        return [to_record(row) for row in cursor.fetchall()]


def fetch_page(connection, limit: int, offset: int) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            SELECT_OBSERVATION + " ORDER BY o.date_time LIMIT %s OFFSET %s",
            (limit, offset),
        )
        return [to_record(row) for row in cursor.fetchall()]


def create_observation(connection, payload: ObservationIn) -> dict:
    try:
        with connection.cursor() as cursor:
            holiday_id = _lookup_holiday(cursor, payload.holiday)
            weather_id = _lookup_weather(cursor, payload.weather)
            cursor.execute(
                """
                INSERT INTO traffic_observations
                    (date_time, traffic_volume, holiday_id, is_imputed)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    payload.date_time,
                    payload.traffic_volume,
                    holiday_id,
                    int(payload.is_imputed),
                ),
            )
            obs_id = cursor.lastrowid
            weather = payload.weather
            cursor.execute(
                """
                INSERT INTO weather_readings
                    (obs_id, weather_id, temp, rain_1h, snow_1h, clouds_all)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    obs_id,
                    weather_id,
                    weather.temp,
                    weather.rain_1h,
                    weather.snow_1h,
                    weather.clouds_all,
                ),
            )
        connection.commit()
    except pymysql.err.IntegrityError as exc:
        connection.rollback()
        if exc.args and exc.args[0] == 1062:
            raise Conflict(
                f"An observation already exists at {payload.date_time}"
            ) from exc
        raise
    return fetch_by_id(connection, obs_id)


def update_observation(connection, obs_id: int, payload: ObservationIn) -> dict:
    fetch_by_id(connection, obs_id)
    try:
        with connection.cursor() as cursor:
            holiday_id = _lookup_holiday(cursor, payload.holiday)
            weather_id = _lookup_weather(cursor, payload.weather)
            cursor.execute(
                """
                UPDATE traffic_observations
                SET date_time = %s,
                    traffic_volume = %s,
                    holiday_id = %s,
                    is_imputed = %s
                WHERE obs_id = %s
                """,
                (
                    payload.date_time,
                    payload.traffic_volume,
                    holiday_id,
                    int(payload.is_imputed),
                    obs_id,
                ),
            )
            weather = payload.weather
            cursor.execute(
                """
                UPDATE weather_readings
                SET weather_id = %s,
                    temp = %s,
                    rain_1h = %s,
                    snow_1h = %s,
                    clouds_all = %s
                WHERE obs_id = %s
                """,
                (
                    weather_id,
                    weather.temp,
                    weather.rain_1h,
                    weather.snow_1h,
                    weather.clouds_all,
                    obs_id,
                ),
            )
        connection.commit()
    except pymysql.err.IntegrityError as exc:
        connection.rollback()
        if exc.args and exc.args[0] == 1062:
            raise Conflict(
                f"Another observation already exists at {payload.date_time}"
            ) from exc
        raise
    return fetch_by_id(connection, obs_id)


def delete_observation(connection, obs_id: int) -> None:
    fetch_by_id(connection, obs_id)
    with connection.cursor() as cursor:
        # weather_readings is removed by ON DELETE CASCADE.
        cursor.execute("DELETE FROM traffic_observations WHERE obs_id = %s", (obs_id,))
    connection.commit()
