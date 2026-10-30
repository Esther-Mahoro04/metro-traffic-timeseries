"""Task 3 routes: CRUD plus latest-record and date-range queries.

MySQL  -> /sql/observations
MongoDB -> /mongo/observations

Static paths (/latest, /range) are registered before /{id} so those words are
not treated as identifiers.
"""

from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pymongo.collection import Collection

from api.db import get_mongo, get_mysql, ping_databases
from api.mongo_repo import (
    create_observation as create_mongo,
)
from api.mongo_repo import (
    delete_observation as delete_mongo,
)
from api.mongo_repo import (
    fetch_by_id as fetch_mongo,
)
from api.mongo_repo import (
    fetch_latest as latest_mongo,
)
from api.mongo_repo import (
    fetch_page as page_mongo,
)
from api.mongo_repo import (
    fetch_range as range_mongo,
)
from api.mongo_repo import (
    update_observation as update_mongo,
)
from api.errors import Conflict, NotFound
from api.schemas import DeleteResult, ObservationIn, ObservationOut, RecordList
from api.sql_repo import (
    create_observation as create_sql,
)
from api.sql_repo import (
    delete_observation as delete_sql,
)
from api.sql_repo import (
    fetch_by_id as fetch_sql,
)
from api.sql_repo import (
    fetch_latest as latest_sql,
)
from api.sql_repo import (
    fetch_page as page_sql,
)
from api.sql_repo import (
    fetch_range as range_sql,
)
from api.sql_repo import (
    update_observation as update_sql,
)

app = FastAPI(
    title="Metro Interstate Traffic API",
    description=(
        "CRUD and time-series queries for the I-94 hourly traffic dataset. "
        "The same operations are available for MySQL and MongoDB."
    ),
    version="1.0.0",
)


@app.exception_handler(NotFound)
def not_found_handler(_request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(Conflict)
def conflict_handler(_request, exc: Conflict):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


def _bounds(start: str, end: str) -> tuple[datetime, datetime]:
    """Accept a date or a timestamp. A date-only end covers that whole day."""

    def parse(value: str, is_end: bool) -> datetime:
        text = value.strip().replace("T", " ")
        date_only = len(text) == 10
        pattern = "%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M:%S"
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS for start and end.",
            ) from exc
        if date_only and is_end:
            return parsed.replace(hour=23, minute=59, second=59)
        return parsed

    start_at = parse(start, is_end=False)
    end_at = parse(end, is_end=True)
    if start_at > end_at:
        raise HTTPException(status_code=400, detail="start must be earlier than or equal to end.")
    return start_at, end_at


@app.get("/")
def root():
    return {
        "task": "Task 3 — CRUD and time-series queries",
        "docs": "/docs",
        "health": "/health",
        "mysql": "/sql/observations",
        "mongodb": "/mongo/observations",
    }


@app.get("/health")
def health():
    status = ping_databases()
    ready = status["mysql"] == "ok" and status["mongodb"] == "ok"
    return {"ready": ready, **status}


@app.post("/sql/observations", response_model=ObservationOut, status_code=201, tags=["MySQL"])
def sql_create(payload: ObservationIn, connection=Depends(get_mysql)):
    return create_sql(connection, payload)


@app.get("/sql/observations", response_model=RecordList, tags=["MySQL"])
def sql_list(
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    connection=Depends(get_mysql),
):
    records = page_sql(connection, limit, offset)
    return {"count": len(records), "records": records}


@app.get("/sql/observations/latest", response_model=ObservationOut, tags=["MySQL"])
def sql_latest(connection=Depends(get_mysql)):
    return latest_sql(connection)


@app.get("/sql/observations/range", response_model=RecordList, tags=["MySQL"])
def sql_range(
    start: str,
    end: str,
    limit: int = Query(default=1000, ge=1, le=10000),
    connection=Depends(get_mysql),
):
    start_at, end_at = _bounds(start, end)
    records = range_sql(connection, start_at, end_at, limit)
    return {"count": len(records), "records": records}


@app.get("/sql/observations/{obs_id}", response_model=ObservationOut, tags=["MySQL"])
def sql_read(obs_id: int, connection=Depends(get_mysql)):
    return fetch_sql(connection, obs_id)


@app.put("/sql/observations/{obs_id}", response_model=ObservationOut, tags=["MySQL"])
def sql_update(obs_id: int, payload: ObservationIn, connection=Depends(get_mysql)):
    return update_sql(connection, obs_id, payload)


@app.delete("/sql/observations/{obs_id}", response_model=DeleteResult, tags=["MySQL"])
def sql_delete(obs_id: int, connection=Depends(get_mysql)):
    delete_sql(connection, obs_id)
    return {"deleted": True, "id": obs_id}


@app.post("/mongo/observations", response_model=ObservationOut, status_code=201, tags=["MongoDB"])
def mongo_create(payload: ObservationIn, collection: Collection = Depends(get_mongo)):
    return create_mongo(collection, payload)


@app.get("/mongo/observations", response_model=RecordList, tags=["MongoDB"])
def mongo_list(
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    collection: Collection = Depends(get_mongo),
):
    records = page_mongo(collection, limit, offset)
    return {"count": len(records), "records": records}


@app.get("/mongo/observations/latest", response_model=ObservationOut, tags=["MongoDB"])
def mongo_latest(collection: Collection = Depends(get_mongo)):
    return latest_mongo(collection)


@app.get("/mongo/observations/range", response_model=RecordList, tags=["MongoDB"])
def mongo_range(
    start: str,
    end: str,
    limit: int = Query(default=1000, ge=1, le=10000),
    collection: Collection = Depends(get_mongo),
):
    start_at, end_at = _bounds(start, end)
    records = range_mongo(collection, start_at, end_at, limit)
    return {"count": len(records), "records": records}


@app.get("/mongo/observations/{doc_id}", response_model=ObservationOut, tags=["MongoDB"])
def mongo_read(doc_id: str, collection: Collection = Depends(get_mongo)):
    return fetch_mongo(collection, doc_id)


@app.put("/mongo/observations/{doc_id}", response_model=ObservationOut, tags=["MongoDB"])
def mongo_update(doc_id: str, payload: ObservationIn, collection: Collection = Depends(get_mongo)):
    return update_mongo(collection, doc_id, payload)


@app.delete("/mongo/observations/{doc_id}", response_model=DeleteResult, tags=["MongoDB"])
def mongo_delete(doc_id: str, collection: Collection = Depends(get_mongo)):
    delete_mongo(collection, doc_id)
    return {"deleted": True, "id": doc_id}
