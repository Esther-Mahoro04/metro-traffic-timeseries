# Metro Interstate Traffic Volume — time-series pipeline

Hourly westbound traffic on I-94 (Minneapolis–St Paul), from the Metro Interstate Traffic Volume dataset. The series runs from **2012-10-02 09:00** to **2018-09-30 23:00**. The prediction target is `traffic_volume`. Each hour also records holiday, temperature (Kelvin), rain, snow, cloud cover, and a weather description.

This repository folder holds the group project. **Task 3** (this API) exposes the MySQL schema and the MongoDB collection from Task 2\.

## Layout

| Path | What it is |
| :---- | :---- |
| `data/traffic_clean.csv` | Cleaned hourly series used to fill both databases |
| `sql/schema.sql` | Graded MySQL schema (4 tables) |
| `sql/queries.sql` | Task 2 SQL queries |
| `sql/docker-init.sql` | Same tables, applied automatically by Docker |
| `mongodb/sample_documents.json` | Example embedded documents |
| `mongodb/queries.js` | Task 2 MongoDB queries |
| `api/` | Task 3 FastAPI application |
| `scripts/seed_databases.py` | Loads the CSV into MySQL and MongoDB |
| `scripts/demo_task3.py` | Calls every endpoint and writes `results/task3_api_results.md` |

## Task 3 endpoints

The same operations exist for both databases. MySQL ids are integers (`obs_id`). MongoDB ids are document ids.

| Action | MySQL | MongoDB |
| :---- | :---- | :---- |
| Create | `POST /sql/observations` | `POST /mongo/observations` |
| List | `GET /sql/observations?limit=50&offset=0` | `GET /mongo/observations?limit=50&offset=0` |
| Read one | `GET /sql/observations/{id}` | `GET /mongo/observations/{id}` |
| Update | `PUT /sql/observations/{id}` | `PUT /mongo/observations/{id}` |
| Delete | `DELETE /sql/observations/{id}` | `DELETE /mongo/observations/{id}` |
| Latest record | `GET /sql/observations/latest` | `GET /mongo/observations/latest` |
| Date range | `GET /sql/observations/range?start=2012-10-02 09:00:00&end=2012-10-02 12:00:00` | `GET /mongo/observations/range?start=2012-10-02&end=2012-10-02` |

`start` and `end` accept `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. A date-only `end` includes that entire day.

MySQL writes go through the normalized tables: `holidays`, `weather_conditions`, `traffic_observations`, and `weather_readings`. MongoDB stores one embedded document per hour in the `traffic` collection of database `traffic_db`, matching `mongodb/sample_documents.json`.

Interactive docs: [http\://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Run it

Docker Desktop has to be running. From this folder:

```powershell
docker compose up -d
py -m pip install -r requirements.txt
py scripts/seed_databases.py
py -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

&nbsp;

In a second terminal:

```powershell
py scripts/demo_task3.py
```

&nbsp;

That writes `results/task3_api_results.md` with the status code and JSON for each call. Use those responses in the PDF report.

Defaults (also listed in `.env.example`): MySQL `root` / `root` on port 3306, MongoDB on port 27017, database name `traffic_db`.

If `docker compose` fails because Docker reports that virtualization is unavailable, turn on Virtual Machine Platform (or Hyper-V) in Windows and restart Docker Desktop. The API itself only needs a reachable MySQL 8 database and a MongoDB server. Copy `.env.example` to `.env` if those servers are not on `127.0.0.1` with the default password.

### Example body

```json
{
  "date_time": "2099-01-01 12:00:00",
  "traffic_volume": 1111,
  "holiday": "None",
  "is_imputed": false,
  "weather": {
    "temp": 280.0,
    "rain_1h": 0,
    "snow_1h": 0,
    "clouds_all": 20,
    "main": "Clear",
    "description": "sky is clear"
  }
}
```

`PUT` replaces the stored hour with this same shape. `date_time` is unique in both databases, so a second `POST` for an hour that already exists returns `409`.

&nbsp;