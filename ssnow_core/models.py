"""Shared domain models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Category = Literal[
    "earthquake",
    "volcano",
    "wildfire",
    "storm",
    "flood",
    "space_weather_alert",
    "geomagnetic_storm",
    "cme",
    "solar_flare",
    "neo",
    "fireball",
    "severe_outlook",
    "weather_alert",
    "other",
]

EVENT_LIMIT = 1000


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class Event(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    source: str
    upstream_id: str
    category: str = Field(default="other")
    title: str
    description: str | None = None
    occurred_at: datetime
    updated_at: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    depth_km: float | None = None
    magnitude: float | None = None
    magnitude_unit: str | None = None
    url: str | None = None
    raw_ref: str | None = None
    extra_json: dict[str, Any] = Field(default_factory=dict)
    ingested_at: datetime = Field(default_factory=utcnow)

    @field_validator("occurred_at", "updated_at", "ingested_at", mode="before")
    @classmethod
    def _coerce_datetime(cls, value: Any) -> datetime | None:
        return parse_datetime(value)


class Observation(BaseModel):
    source: str
    series: str
    ts: datetime
    value: float
    unit: str | None = None
    extra_json: dict[str, Any] = Field(default_factory=dict)


class SnapshotRecord(BaseModel):
    source: str
    url: str
    fetched_at: datetime
    content_type: str
    path: str
    size_bytes: int
    status_code: int | None = None
    error: str | None = None


class SourceState(BaseModel):
    source_id: str
    last_attempt: datetime | None = None
    last_success: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    next_due: datetime | None = None
    records_ingested: int = 0
