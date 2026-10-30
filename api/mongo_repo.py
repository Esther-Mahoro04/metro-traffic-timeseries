"""MongoDB CRUD for the embedded traffic documents in mongodb/sample_documents.json.

Each hour is one document. Weather is nested, matching the collection designed
in Task 2, instead of the separate lookup tables used by MySQL.
"""

from datetime import datetime

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from api.errors import Conflict, NotFound
from api.schemas import ObservationIn


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def to_record(document: dict) -> dict:
    moment = document["date_time"]
    if isinstance(moment, datetime):
        moment = _stamp(moment)
    weather = document["weather"]
    return {
        "id": str(document["_id"]),
        "date_time": moment,
        "traffic_volume": int(document["traffic_volume"]),
        "holiday": document["holiday"],
        "is_imputed": bool(document["is_imputed"]),
        "weather": {
            "temp": float(weather["temp"]),
            "rain_1h": float(weather.get("rain_1h", 0)),
            "snow_1h": float(weather.get("snow_1h", 0)),
            "clouds_all": int(weather["clouds_all"]),
            "main": weather["main"],
            "description": weather["description"],
        },
    }


def _object_id(doc_id: str) -> ObjectId:
    try:
        return ObjectId(doc_id)
    except (InvalidId, TypeError) as exc:
        raise NotFound(f"No MongoDB observation with id {doc_id}") from exc


def _document(payload: ObservationIn) -> dict:
    weather = payload.weather
    return {
        "date_time": payload.date_time.replace(tzinfo=None),
        "traffic_volume": payload.traffic_volume,
        "holiday": payload.holiday,
        "is_imputed": payload.is_imputed,
        "weather": {
            "temp": weather.temp,
            "rain_1h": weather.rain_1h,
            "snow_1h": weather.snow_1h,
            "clouds_all": weather.clouds_all,
            "main": weather.main,
            "description": weather.description,
        },
    }


def fetch_by_id(collection: Collection, doc_id: str) -> dict:
    document = collection.find_one({"_id": _object_id(doc_id)})
    if document is None:
        raise NotFound(f"No MongoDB observation with id {doc_id}")
    return to_record(document)


def fetch_latest(collection: Collection) -> dict:
    document = collection.find_one(sort=[("date_time", -1)])
    if document is None:
        raise NotFound("No MongoDB observations stored")
    return to_record(document)


def fetch_range(collection: Collection, start: datetime, end: datetime, limit: int) -> list[dict]:
    cursor = (
        collection.find({"date_time": {"$gte": start, "$lte": end}})
        .sort("date_time", 1)
        .limit(limit)
    )
    return [to_record(document) for document in cursor]


def fetch_page(collection: Collection, limit: int, offset: int) -> list[dict]:
    cursor = collection.find().sort("date_time", 1).skip(offset).limit(limit)
    return [to_record(document) for document in cursor]


def create_observation(collection: Collection, payload: ObservationIn) -> dict:
    try:
        result = collection.insert_one(_document(payload))
    except DuplicateKeyError as exc:
        raise Conflict(f"An observation already exists at {payload.date_time}") from exc
    return fetch_by_id(collection, str(result.inserted_id))


def update_observation(collection: Collection, doc_id: str, payload: ObservationIn) -> dict:
    fetch_by_id(collection, doc_id)
    try:
        collection.update_one({"_id": _object_id(doc_id)}, {"$set": _document(payload)})
    except DuplicateKeyError as exc:
        raise Conflict(
            f"Another observation already exists at {payload.date_time}"
        ) from exc
    return fetch_by_id(collection, doc_id)


def delete_observation(collection: Collection, doc_id: str) -> None:
    fetch_by_id(collection, doc_id)
    collection.delete_one({"_id": _object_id(doc_id)})
