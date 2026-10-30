"""Small HTTP client for the Task 3 API.

Only the two time-series endpoints are needed by the forecast script:

    GET /{store}/observations/latest
    GET /{store}/observations/range?start=...&end=...&limit=...

`store` is "sql" (MySQL) or "mongo" (MongoDB). Both return the same JSON
shape (api/schemas.py: ObservationOut), so the rest of the pipeline does not
care which database the records came from.

Uses only the standard library, like scripts/demo_task3.py.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

STORES = {"sql": "MySQL", "mongo": "MongoDB"}
STAMP = "%Y-%m-%d %H:%M:%S"
MAX_RANGE_LIMIT = 10000  # upper bound enforced by the API on /range


class ApiError(RuntimeError):
    """Raised when the API cannot be reached or answers with an error."""


class TrafficApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # -- low level -----------------------------------------------------------
    def _get(self, path: str, params: dict | None = None) -> dict:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body).get("detail", body)
            except json.JSONDecodeError:
                detail = body
            raise ApiError(f"GET {path} returned {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(
                f"Could not reach the API at {self.base_url} ({exc.reason}). "
                "Start it with: python -m uvicorn api.main:app --host 127.0.0.1 --port 8000"
            ) from exc

    @staticmethod
    def _check_store(store: str) -> None:
        if store not in STORES:
            raise ValueError(f"store must be one of {sorted(STORES)}, got {store!r}")

    # -- endpoints -----------------------------------------------------------
    def health(self) -> dict:
        return self._get("/health")

    def latest(self, store: str) -> dict:
        """Most recent hourly record in the chosen database."""
        self._check_store(store)
        return self._get(f"/{store}/observations/latest")

    def date_range(self, store: str, start: datetime, end: datetime) -> list[dict]:
        """All records with start <= date_time <= end, oldest first."""
        self._check_store(store)
        payload = self._get(
            f"/{store}/observations/range",
            {"start": start.strftime(STAMP), "end": end.strftime(STAMP), "limit": MAX_RANGE_LIMIT},
        )
        return payload["records"]
