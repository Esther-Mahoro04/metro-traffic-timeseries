"""Load data/traffic_clean.csv into MySQL and MongoDB.

Run this after `docker compose up -d` and before starting the API demo.
It rebuilds both stores from the cleaned hourly series so CRUD calls have
real timestamps to read.
"""

import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import pymysql
from pymongo import MongoClient
from pymongo.errors import PyMongoError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import config  # noqa: E402

CSV_PATH = ROOT / "data" / "traffic_clean.csv"
SCHEMA_PATH = ROOT / "sql" / "docker-init.sql"
BATCH = 2000


def as_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_rows(path: Path) -> list[dict]:
    """Read the cleaned series. Later duplicate hours replace earlier ones."""
    by_time = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            stamp = (raw.get("timestamp") or raw.get("date_time") or "").strip()
            if not stamp:
                continue
            moment = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
            holiday = (raw.get("holiday") or "None").strip() or "None"
            by_time[moment] = {
                "date_time": moment,
                "traffic_volume": int(float(raw["traffic_volume"])),
                "holiday": holiday[:50],
                "is_imputed": as_bool(raw.get("is_imputed", "0")),
                "temp": float(raw.get("temp_k") or raw.get("temp")),
                "rain_1h": float(raw.get("rain_1h") or 0),
                "snow_1h": float(raw.get("snow_1h") or 0),
                "clouds_all": int(float(raw.get("clouds_all") or 0)),
                "main": (raw.get("weather_main") or raw.get("main") or "Unknown")[:30],
                "description": (
                    raw.get("weather_description") or raw.get("description") or "unknown"
                )[:60],
            }
    return [by_time[key] for key in sorted(by_time)]


def connect_mysql():
    last_error = None
    for attempt in range(30):
        try:
            return pymysql.connect(
                host=config.MYSQL_HOST,
                port=config.MYSQL_PORT,
                user=config.MYSQL_USER,
                password=config.MYSQL_PASSWORD,
                database=config.MYSQL_DATABASE,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,
            )
        except pymysql.MySQLError as exc:
            last_error = exc
            print(f"Waiting for MySQL ({attempt + 1}/30): {exc}")
            time.sleep(2)
    raise SystemExit(f"MySQL did not become ready: {last_error}")


def connect_mongo():
    last_error = None
    for attempt in range(30):
        try:
            client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=3000)
            client.admin.command("ping")
            return client
        except PyMongoError as exc:
            last_error = exc
            print(f"Waiting for MongoDB ({attempt + 1}/30): {exc}")
            time.sleep(2)
    raise SystemExit(f"MongoDB did not become ready: {last_error}")


def apply_schema(connection) -> None:
    lines = []
    for line in SCHEMA_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("--"):
            lines.append(line)
    with connection.cursor() as cursor:
        for statement in "\n".join(lines).split(";"):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)
    connection.commit()


def _collapse_case(rows: list[dict], field: str) -> None:
    chosen = {}
    for row in rows:
        chosen.setdefault(row[field].casefold(), row[field])
    for row in rows:
        row[field] = chosen[row[field].casefold()]


def _collapse_case_pair(rows: list[dict], left: str, right: str) -> None:
    chosen = {}
    for row in rows:
        chosen.setdefault((row[left].casefold(), row[right].casefold()), (row[left], row[right]))
    for row in rows:
        row[left], row[right] = chosen[(row[left].casefold(), row[right].casefold())]


def chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def seed_mysql(connection, rows: list[dict]) -> int:
    apply_schema(connection)
    with connection.cursor() as cursor:
        # Delete children first so foreign keys stay valid on a re-seed.
        cursor.execute("DELETE FROM weather_readings")
        cursor.execute("DELETE FROM traffic_observations")
        cursor.execute("DELETE FROM weather_conditions")
        cursor.execute("DELETE FROM holidays")
        cursor.execute("ALTER TABLE traffic_observations AUTO_INCREMENT = 1")
        cursor.execute("ALTER TABLE weather_conditions AUTO_INCREMENT = 1")
        cursor.execute("ALTER TABLE holidays AUTO_INCREMENT = 1")

        # MySQL's default collation treats "Sky is Clear" and "sky is clear" as the same key.
        _collapse_case(rows, "holiday")
        _collapse_case_pair(rows, "main", "description")

        holidays = sorted({row["holiday"] for row in rows})
        cursor.executemany(
            "INSERT INTO holidays (holiday_name) VALUES (%s)",
            [(name,) for name in holidays],
        )
        cursor.execute("SELECT holiday_id, holiday_name FROM holidays")
        holiday_ids = {item["holiday_name"]: item["holiday_id"] for item in cursor.fetchall()}

        conditions = sorted({(row["main"], row["description"]) for row in rows})
        cursor.executemany(
            """
            INSERT INTO weather_conditions (weather_main, weather_description)
            VALUES (%s, %s)
            """,
            conditions,
        )
        cursor.execute(
            "SELECT weather_id, weather_main, weather_description FROM weather_conditions"
        )
        weather_ids = {
            (item["weather_main"], item["weather_description"]): item["weather_id"]
            for item in cursor.fetchall()
        }

        observation_rows = [
            (
                row["date_time"],
                row["traffic_volume"],
                holiday_ids[row["holiday"]],
                int(row["is_imputed"]),
            )
            for row in rows
        ]
        for batch in chunks(observation_rows, BATCH):
            cursor.executemany(
                """
                INSERT INTO traffic_observations
                    (date_time, traffic_volume, holiday_id, is_imputed)
                VALUES (%s, %s, %s, %s)
                """,
                batch,
            )

        cursor.execute("SELECT obs_id, date_time FROM traffic_observations")
        id_by_time = {
            item["date_time"].strftime("%Y-%m-%d %H:%M:%S"): item["obs_id"]
            for item in cursor.fetchall()
        }
        reading_rows = [
            (
                id_by_time[row["date_time"].strftime("%Y-%m-%d %H:%M:%S")],
                weather_ids[(row["main"], row["description"])],
                row["temp"],
                row["rain_1h"],
                row["snow_1h"],
                row["clouds_all"],
            )
            for row in rows
        ]
        for batch in chunks(reading_rows, BATCH):
            cursor.executemany(
                """
                INSERT INTO weather_readings
                    (obs_id, weather_id, temp, rain_1h, snow_1h, clouds_all)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                batch,
            )
    connection.commit()
    return len(rows)


def seed_mongo(client: MongoClient, rows: list[dict]) -> int:
    collection = client[config.MONGO_DB][config.MONGO_COLLECTION]
    collection.drop()
    documents = [
        {
            "date_time": row["date_time"],
            "traffic_volume": row["traffic_volume"],
            "holiday": row["holiday"],
            "is_imputed": row["is_imputed"],
            "weather": {
                "temp": row["temp"],
                "rain_1h": row["rain_1h"],
                "snow_1h": row["snow_1h"],
                "clouds_all": row["clouds_all"],
                "main": row["main"],
                "description": row["description"],
            },
        }
        for row in rows
    ]
    for batch in chunks(documents, BATCH):
        collection.insert_many(batch, ordered=True)
    collection.create_index("date_time", unique=True)
    return collection.count_documents({})


def main() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"Missing cleaned dataset: {CSV_PATH}")
    rows = load_rows(CSV_PATH)
    print(f"Loaded {len(rows)} hourly rows from {CSV_PATH.name}")
    print(f"Time range: {rows[0]['date_time']} to {rows[-1]['date_time']}")

    connection = connect_mysql()
    try:
        sql_count = seed_mysql(connection, rows)
    finally:
        connection.close()
    print(f"MySQL traffic_observations: {sql_count}")

    client = connect_mongo()
    try:
        mongo_count = seed_mongo(client, rows)
    finally:
        client.close()
    print(f"MongoDB traffic documents: {mongo_count}")


if __name__ == "__main__":
    main()
