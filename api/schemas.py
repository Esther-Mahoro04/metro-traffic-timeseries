"""Request and response bodies shared by the MySQL and MongoDB routes.

Both databases return the same JSON shape so a caller (including the Task 4
forecast script) can switch stores without changing how it reads a record.
"""

from datetime import datetime
from typing import Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WeatherIn(BaseModel):
    temp: float = Field(description="Temperature in Kelvin (cleaned column temp_k).")
    rain_1h: float = Field(default=0, ge=0)
    snow_1h: float = Field(default=0, ge=0)
    clouds_all: int = Field(ge=0, le=100)
    main: str = Field(min_length=1, max_length=30, description="weather_main, e.g. Clouds.")
    description: str = Field(min_length=1, max_length=60)


class WeatherOut(BaseModel):
    temp: float
    rain_1h: float
    snow_1h: float
    clouds_all: int
    main: str
    description: str


class ObservationIn(BaseModel):
    """Full observation used by POST and PUT."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "date_time": "2018-09-30 23:00:00",
                "traffic_volume": 2500,
                "holiday": "None",
                "is_imputed": False,
                "weather": {
                    "temp": 288.15,
                    "rain_1h": 0,
                    "snow_1h": 0,
                    "clouds_all": 40,
                    "main": "Clouds",
                    "description": "scattered clouds",
                },
            }
        }
    )

    date_time: datetime
    traffic_volume: int = Field(ge=0)
    holiday: str = Field(default="None", min_length=1, max_length=50)
    is_imputed: bool = False
    weather: WeatherIn

    @field_validator("date_time", mode="before")
    @classmethod
    def accept_dataset_timestamps(cls, value):
        # The cleaned CSV uses "2012-10-02 09:00:00" rather than a T separator.
        if isinstance(value, str) and "T" not in value and " " in value:
            return value.replace(" ", "T", 1)
        return value

    @field_validator("date_time", mode="after")
    @classmethod
    def store_naive_timestamp(cls, value: datetime) -> datetime:
        # MySQL DATETIME and the Mongo documents keep a timezone-naive hour.
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value


class ObservationOut(BaseModel):
    id: Union[int, str]
    date_time: str
    traffic_volume: int
    holiday: str
    is_imputed: bool
    weather: WeatherOut


class RecordList(BaseModel):
    count: int
    records: list[ObservationOut]


class DeleteResult(BaseModel):
    deleted: bool
    id: Union[int, str]
