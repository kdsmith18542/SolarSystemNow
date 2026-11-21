"""Ingestion scheduler: runs due adapters sequentially."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .logging_config import get_logger
from .sources.registry import build_adapter, spec_for
from .store import Store

logger = get_logger("scheduler")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def run_due(store: Store, client: httpx.Client | None = None, now: datetime | None = None) -> list:
    if now is None:
        now = utcnow()
    if client is None:
        client = httpx.Client()
        own_client = True
    else:
        own_client = False
    reports = []
    try:
        due = store.due_sources(now)
        # Deterministic ordering: USGS before EONET for quake cross-linking.
        priority = ["usgs", "eonet", "nws_alerts", "openmeteo", "tides", "swpc_kp", "swpc_kp_forecast", "swpc_alerts", "swpc_xray", "swpc_f107", "swpc_wind", "donki_cme", "donki_gst", "neows", "aurora", "geomag", "sun_imagery", "moon"]
        due = sorted(due, key=lambda sid: (priority.index(sid) if sid in priority else 99, sid))
        logger.info("Found %d due sources to ingest", len(due))
        for source_id in due:
            spec = spec_for(source_id)
            if spec is None or not spec.enabled:
                continue
            adapter = build_adapter(source_id)
            report = adapter.ingest(store, client, now)
            reports.append(report)
            if report.ok:
                logger.info("Source %s completed ok (%d events, %d obs)", source_id, len(report.events), len(report.observations))
            else:
                logger.warning("Source %s failed: %s", source_id, report.error)
    finally:
        if own_client:
            client.close()
    return reports
