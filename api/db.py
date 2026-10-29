"""MySQL and MongoDB connections used by the request handlers."""

from collections.abc import Iterator

import pymysql
from fastapi import HTTPException
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from api import config

_mongo_client: MongoClient | None = None


def mysql_connection():
    """Open one MySQL connection. Caller commits and closes it."""
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
        raise HTTPException(
            status_code=503,
            detail=f"MySQL is not reachable at {config.MYSQL_HOST}:{config.MYSQL_PORT}. {exc}",
        ) from exc


def get_mysql() -> Iterator:
    """FastAPI dependency: one transaction per request."""
    connection = mysql_connection()
    try:
        yield connection
    finally:
        connection.close()


def mongo_collection() -> Collection:
    """Return the traffic collection, creating the time index on first use."""
    global _mongo_client
    try:
        if _mongo_client is None:
            _mongo_client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=3000)
            _mongo_client.admin.command("ping")
        collection = _mongo_client[config.MONGO_DB][config.MONGO_COLLECTION]
        collection.create_index("date_time", unique=True)
        return collection
    except PyMongoError as exc:
        _mongo_client = None
        raise HTTPException(
            status_code=503,
            detail=f"MongoDB is not reachable at {config.MONGO_URI}. {exc}",
        ) from exc


def get_mongo() -> Iterator[Collection]:
    yield mongo_collection()


def ping_databases() -> dict:
    """Used by GET /health. Reports each store separately so a partial outage is obvious."""
    status = {"mysql": "ok", "mongodb": "ok"}
    try:
        connection = mysql_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        finally:
            connection.close()
    except HTTPException as exc:
        status["mysql"] = exc.detail

    try:
        mongo_collection().database.client.admin.command("ping")
    except HTTPException as exc:
        status["mongodb"] = exc.detail
    return status
