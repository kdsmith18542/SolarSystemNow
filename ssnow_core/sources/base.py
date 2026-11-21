"""Adapter interface and base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from ..logging_config import get_logger
from ..models import Event, Observation
from ..store import Store

logger = get_logger("adapter")


@dataclass(frozen=True)
class SourceSpec:
    id: str
    name: str
    domain: str
    attribution: str
    license: str
    url: str
    cadence_seconds: int = 3600
    requires_key: bool = False
    enabled: bool = True


class FetchResult:
    def __init__(
        self,
        source_id: str,
        status_code: int | None,
        url: str,
        content_type: str,
        events: list[Event],
        observations: list[Observation],
        assets: int = 0,
        error: str | None = None,
    ) -> None:
        self.source_id = source_id
        self.status_code = status_code
        self.url = url
        self.content_type = content_type
        self.events = events
        self.observations = observations
        self.assets = assets
        self.error = error

    @property
    def ok(self) -> bool:
        return self.error is None


class Adapter(ABC):
    spec: SourceSpec

    @abstractmethod
    def ingest(self, store: Store, client: httpx.Client, now: datetime | None = None) -> FetchResult:
        """Run one ingestion cycle against the store."""


class HttpAdapter(Adapter, ABC):
    def __init__(self, spec: SourceSpec) -> None:
        self.spec = spec
        self.client_headers = {
            "User-Agent": "ss-now/0.1 (solar-system-now real-data platform)",
            "Accept": "*/*",
        }

    def request(self, client: httpx.Client) -> httpx.Response:
        method, url, params, headers = self.build_request()
        merged_headers = {**self.client_headers, **headers}
        return client.request(method, url, params=params, headers=merged_headers, timeout=30.0)

    @abstractmethod
    def build_request(self, now=None) -> tuple[str, str, dict[str, Any] | None, dict[str, str]]:
        ...

    @abstractmethod
    def parse(self, payload: bytes, content_type: str, now=None) -> tuple[list[Event], list[Observation]]:
        ...

    def ingest(self, store: Store, client: httpx.Client, now=None) -> FetchResult:
        if now is None:
            now = datetime.now(timezone.utc)

        logger.info("Ingesting source: %s", self.spec.id)
        store.begin_attempt(self.spec.id, now)
        self.before_request(store)
        try:
            response = self.request(client)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fetch failed for %s: %s", self.spec.id, exc)
            store.record_failure(self.spec.id, now, str(exc), self.spec.cadence_seconds)
            return FetchResult(
                self.spec.id,
                getattr(getattr(exc, "response", None), "status_code", None),
                str(getattr(getattr(exc, "request", None), "url", "")),
                "",
                [],
                [],
                error=str(exc),
            )

        try:
            store.save_snapshot(
                self.spec.id,
                str(response.url),
                response.content,
                response.headers.get("content-type", ""),
                status_code=response.status_code,
                fetched_at=now,
            )
            events, observations = self.parse(response.content, response.headers.get("content-type", ""), now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Parse failed for %s: %s", self.spec.id, exc)
            store.record_failure(self.spec.id, now, f"parse: {exc}", self.spec.cadence_seconds)
            return FetchResult(
                self.spec.id,
                response.status_code,
                str(response.url),
                response.headers.get("content-type", ""),
                [],
                [],
                error=f"parse: {exc}",
            )

        self.persist(store, events, observations, now)
        store.record_success(self.spec.id, now, len(events) + len(observations), self.spec.cadence_seconds)
        logger.info(
            "Ingested %s: %d events, %d observations",
            self.spec.id,
            len(events),
            len(observations),
        )
        return FetchResult(
            self.spec.id,
            response.status_code,
            str(response.url),
            response.headers.get("content-type", ""),
            events,
            observations,
        )

    def persist(self, store: Store, events: list[Event], observations: list[Observation], now=None) -> None:
        store.upsert_events(events)
        store.upsert_observations(observations)

    def before_request(self, store: Store) -> None:
        """Hook called before the HTTP request; store is available for settings/keys."""
        return None
