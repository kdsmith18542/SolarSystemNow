"""NASA SDO solar imagery adapter."""

from __future__ import annotations

from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SunImageryAdapter:
    def __init__(self, spec) -> None:
        self.spec = spec
        self.client_headers = {
            "User-Agent": "ss-now/0.1 (solar-system-now real-data platform)",
            "Accept": "*/*",
        }

    def ingest(self, store, client, now=None) -> FetchResult:
        if now is None:
            now = _utcnow()

        store.begin_attempt(self.spec.id, now)
        try:
            response = client.get(self.spec.url, headers=self.client_headers, timeout=60.0, follow_redirects=True)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "image/jpeg")
            if not response.content.startswith(b"\xff\xd8\xff"):
                raise ValueError("response is not a JPEG image")
            store.save_asset(self.spec.id, str(response.url), response.content, content_type, status_code=response.status_code, fetched_at=now)
        except Exception as exc:  # noqa: BLE001
            store.record_failure(self.spec.id, now, str(exc), self.spec.cadence_seconds)
            return FetchResult(self.spec.id, None, str(self.spec.url), "", [], [], error=str(exc))

        store.record_success(self.spec.id, now, 1, self.spec.cadence_seconds)
        return FetchResult(self.spec.id, response.status_code, str(response.url), content_type, [], [], assets=1)


class FetchResult:
    def __init__(
        self,
        source_id: str,
        status_code: int | None,
        url: str,
        content_type: str,
        events: list,
        observations: list,
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
