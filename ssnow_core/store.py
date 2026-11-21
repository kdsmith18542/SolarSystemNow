"""SQLite-backed storage layer."""

from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import (
    default_asset_dir,
    default_db_path,
    default_snapshot_dir,
)
from .logging_config import get_logger
from .models import Event, EVENT_LIMIT, Observation, SnapshotRecord, SourceState

logger = get_logger("store")


def _locked(method):
    """Serialize SQLite access from worker threads (FastAPI runs sync
    endpoints in a thread pool). RLock is re-entrant, so methods that use
    `with self.transaction()` remain safe to decorate."""
    import functools

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper

PRAGMA_STATEMENTS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
)

SCHEMA_VERSION = 2

# Lifetime context series must survive the generic 90-day observation prune.
CYCLE_SERIES = (
    "swpc:ssn_observed",
    "swpc:f107_observed",
    "swpc:ssn_predicted",
    "swpc:f107_predicted",
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    upstream_id TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    occurred_at TEXT NOT NULL,
    updated_at TEXT,
    latitude REAL,
    longitude REAL,
    depth_km REAL,
    magnitude REAL,
    magnitude_unit TEXT,
    url TEXT,
    raw_ref TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}',
    ingested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_time ON events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS events_category ON events(category);
CREATE INDEX IF NOT EXISTS events_geo ON events(latitude, longitude);
CREATE INDEX IF NOT EXISTS events_source_time ON events(source, occurred_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS events_rtree USING rtree(
    rowid,
    min_lat, max_lat,
    min_lon, max_lon
);

CREATE TABLE IF NOT EXISTS observations (
    source TEXT NOT NULL,
    series TEXT NOT NULL,
    ts TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (source, series, ts)
);
CREATE INDEX IF NOT EXISTS observations_series_ts ON observations(source, series, ts DESC);

CREATE TABLE IF NOT EXISTS snapshots (
    sha256 TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT,
    fetched_at TEXT NOT NULL,
    content_type TEXT,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status_code INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS snapshots_source ON snapshots(source, fetched_at DESC);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    content_type TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status_code INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS assets_source_time ON assets(source, fetched_at DESC);

CREATE TABLE IF NOT EXISTS source_state (
    source_id TEXT PRIMARY KEY,
    last_attempt TEXT,
    last_success TEXT,
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    next_due TEXT,
    records_ingested INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    event_id TEXT,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    severity TEXT NOT NULL,
    fired_at TEXT NOT NULL,
    dismissed_at TEXT,
    delivered_desktop INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS notifications_fired ON notifications(fired_at DESC);
"""

def _schema_columns() -> dict[str, list[tuple[str, str]]]:
    """Parse SCHEMA_SQL into {table: [(column_name, column_definition), ...]}.

    Used by Store._ensure_columns() to self-heal databases created before a
    column was introduced. Constraint lines (PRIMARY KEY / FOREIGN KEY /
    UNIQUE / CHECK) and virtual tables are skipped.
    """
    result: dict[str, list[tuple[str, str]]] = {}
    for block in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);", SCHEMA_SQL, re.DOTALL):
        table, body = block.group(1), block.group(2)
        columns: list[tuple[str, str]] = []
        depth = 0
        current: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            depth += stripped.count("(") - stripped.count(")")
            current.append(stripped)
            if depth > 0:
                continue
            fragment = " ".join(current).rstrip(",")
            current = []
            if not fragment:
                continue
            head = fragment.split(None, 1)[0].upper()
            if head in ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"):
                continue
            name = fragment.split(None, 1)[0]
            definition = fragment.split(None, 1)[1].strip()
            columns.append((name, definition))
        if columns:
            result[table] = columns
    return result


INSERT_OR_REPLACE_EVENT = """
INSERT INTO events (
    id, source, upstream_id, category, title, description, occurred_at, updated_at,
    latitude, longitude, depth_km, magnitude, magnitude_unit, url, raw_ref, extra_json, ingested_at
) VALUES (
    :id, :source, :upstream_id, :category, :title, :description, :occurred_at, :updated_at,
    :latitude, :longitude, :depth_km, :magnitude, :magnitude_unit, :url, :raw_ref, :extra_json, :ingested_at
)
ON CONFLICT(id) DO UPDATE SET
    source=excluded.source,
    upstream_id=excluded.upstream_id,
    category=excluded.category,
    title=excluded.title,
    description=excluded.description,
    occurred_at=excluded.occurred_at,
    updated_at=excluded.updated_at,
    latitude=excluded.latitude,
    longitude=excluded.longitude,
    depth_km=excluded.depth_km,
    magnitude=excluded.magnitude,
    magnitude_unit=excluded.magnitude_unit,
    url=excluded.url,
    raw_ref=excluded.raw_ref,
    extra_json=excluded.extra_json,
    ingested_at=excluded.ingested_at
"""


def _dt_to_iso(value: datetime | str | None) -> str | None:
    """Serialize to canonical UTC (+00:00).

    Strings are parsed first (so upstream offsets such as ``-06:00`` are
    converted instead of stored lexically), naive values are treated as UTC,
    and unparseable strings are returned unchanged as a last resort.
    """
    if value is None:
        return None
    if isinstance(value, str):
        parsed = _dt_from_iso(value)
        if parsed is None:
            return value
        value = parsed
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _dt_from_iso(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class Store:
    def __init__(self, db_path: Path | None = None, snapshots_dir: Path | None = None, assets_dir: Path | None = None) -> None:
        if db_path is None:
            db_path = default_db_path()
        if snapshots_dir is None:
            snapshots_dir = default_snapshot_dir()
        if assets_dir is None:
            assets_dir = default_asset_dir()

        self.db_path = Path(db_path)
        self.snapshots_dir = Path(snapshots_dir)
        self.assets_dir = Path(assets_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.initialize()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cursor = self._conn.cursor()
            try:
                yield cursor
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def initialize(self) -> None:
        for statement in PRAGMA_STATEMENTS:
            self._conn.execute(statement)
        self._conn.executescript(SCHEMA_SQL)
        # Destructive/structural migrations must run before the additive
        # self-heal pass (ALTER cannot add a PRIMARY KEY column).
        self._migrate_assets_table()
        self._ensure_columns()
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()
        else:
            current = int(row[0])
            if current < SCHEMA_VERSION:
                self.migrate(current)
        self._normalize_legacy_event_timestamps()
        self._backfill_rtree()
        self._scrub_persisted_secrets()
        self._purge_removed_sources()
        self._conn.commit()

    def _purge_removed_sources(self) -> None:
        """Remove data for sources deleted from the product (idempotent)."""
        from pathlib import Path

        rows = self._conn.execute(
            "SELECT path FROM snapshots WHERE source = 'tides' OR source LIKE 'tides:%'"
        ).fetchall()
        for (path,) in rows:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        self._conn.execute("DELETE FROM snapshots WHERE source = 'tides' OR source LIKE 'tides:%'")
        self._conn.execute("DELETE FROM observations WHERE source = 'tides'")
        self._conn.execute("DELETE FROM source_state WHERE source_id = 'tides'")
        self._conn.execute("DELETE FROM settings WHERE key = 'tide_stations'")
        self._conn.commit()

    def _migrate_assets_table(self) -> None:
        """Legacy assets keyed by source only (one row per channel); rebuild
        as append-per-fetch so pruning can actually delete old files."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(assets)").fetchall()}
        if not cols or "id" in cols:
            return
        logger.warning("migrating legacy assets table to append-per-fetch (%s)", self.db_path)
        self._conn.executescript(
            """
            ALTER TABLE assets RENAME TO assets_legacy;
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                url TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                content_type TEXT NOT NULL,
                path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                status_code INTEGER,
                error TEXT
            );
            INSERT INTO assets (source, url, fetched_at, content_type, path, size_bytes, status_code, error)
                SELECT source, url, fetched_at, content_type, path, size_bytes, status_code, error
                FROM assets_legacy;
            DROP TABLE assets_legacy;
            CREATE INDEX IF NOT EXISTS assets_source_time ON assets(source, fetched_at DESC);
            """
        )
        self._conn.commit()

    def _normalize_legacy_event_timestamps(self) -> None:
        """One-time rewrite of legacy event timestamps to canonical UTC.

        Older versions stored upstream offsets verbatim (e.g. NWS ``-06:00``),
        which made lexical SQL ordering/filtering wrong.
        """
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'timestamps_utc_version'"
        ).fetchone()
        if row is not None and row[0] == "1":
            return
        rows = self._conn.execute(
            "SELECT id, occurred_at, updated_at, ingested_at FROM events"
        ).fetchall()
        updates = []
        for item in rows:
            new_values = (
                _dt_to_iso(item["occurred_at"]),
                _dt_to_iso(item["updated_at"]),
                _dt_to_iso(item["ingested_at"]),
            )
            if new_values != (item["occurred_at"], item["updated_at"], item["ingested_at"]):
                updates.append((*new_values, item["id"]))
        if updates:
            self._conn.executemany(
                "UPDATE events SET occurred_at = ?, updated_at = ?, ingested_at = ? WHERE id = ?",
                updates,
            )
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('timestamps_utc_version', '1')"
        )
        self._conn.commit()

    def _backfill_rtree(self) -> None:
        """Remove orphan R-tree rows and index geolocated events once."""
        try:
            self._conn.execute(
                "DELETE FROM events_rtree WHERE rowid NOT IN (SELECT rowid FROM events)"
            )
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = 'rtree_backfill_version'"
            ).fetchone()
            if row is None or row[0] != "1":
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO events_rtree(rowid, min_lat, max_lat, min_lon, max_lon)
                    SELECT rowid, latitude, latitude, longitude, longitude FROM events
                    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                      AND rowid NOT IN (SELECT rowid FROM events_rtree)
                    """
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('rtree_backfill_version', '1')"
                )
        except sqlite3.Error as exc:
            logger.warning("R-tree backfill skipped: %s", exc)

    def _scrub_persisted_secrets(self) -> None:
        """One-time redaction of keys leaked by older versions into snapshot
        URLs and source-state error strings."""
        from .redact import redact_secrets, redact_url

        try:
            rows = self._conn.execute(
                "SELECT sha256, url FROM snapshots WHERE url LIKE '%api_key=%' OR url LIKE '%apikey=%' OR url LIKE '%access_token=%' OR url LIKE '%token=%'"
            ).fetchall()
            for sha, url in rows:
                self._conn.execute(
                    "UPDATE snapshots SET url = ? WHERE sha256 = ?", (redact_url(url), sha)
                )
            rows = self._conn.execute(
                "SELECT source_id, last_error FROM source_state WHERE last_error LIKE '%api_key=%' OR last_error LIKE '%apikey=%' OR last_error LIKE '%access_token=%' OR last_error LIKE '%token=%'"
            ).fetchall()
            for source_id, error in rows:
                self._conn.execute(
                    "UPDATE source_state SET last_error = ? WHERE source_id = ?",
                    (redact_secrets(error), source_id),
                )
        except sqlite3.Error as exc:
            logger.warning("secret scrub skipped: %s", exc)

    def _ensure_columns(self) -> None:
        """Self-heal older databases: add any table columns that exist in
        SCHEMA_SQL but not in the physical table (CREATE TABLE IF NOT EXISTS
        never amends existing tables). Idempotent, data-preserving."""
        for table, columns in _schema_columns().items():
            try:
                existing = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
            except sqlite3.Error:
                continue  # table absent -> executescript above created it
            if not existing:
                continue
            for name, definition in columns:
                if name in existing:
                    continue
                # ALTER TABLE ADD COLUMN rejects NOT NULL without a default;
                # backfill a type-appropriate one (upserts always supply values).
                if re.search(r"\bNOT NULL\b", definition) and not re.search(r"\bDEFAULT\b", definition, re.IGNORECASE):
                    if re.search(r"\b(TEXT|CLOB|CHAR)\b", definition, re.IGNORECASE):
                        definition = definition.rstrip() + " DEFAULT ''"
                    else:
                        definition = definition.rstrip() + " DEFAULT 0"
                try:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                    logger.warning("schema self-heal: added column %s.%s (%s)", table, name, self.db_path)
                except sqlite3.OperationalError as exc:
                    # Duplicate column from a concurrent opener is benign.
                    if "duplicate column" not in str(exc).lower():
                        raise

    def migrate(self, current_version: int) -> None:
        """Apply versioned schema migrations in order (complex/destructive
        changes only; simple column additions are auto-healed above)."""
        _MIGRATIONS: dict[int, str] = {
            # 2: assets are append-per-fetch; rebuilt in _migrate_assets_table().
            2: "CREATE INDEX IF NOT EXISTS assets_source_time ON assets(source, fetched_at DESC);",
        }
        for version in sorted(k for k in _MIGRATIONS if k > current_version):
            self._conn.executescript(_MIGRATIONS[version])
            self._conn.execute(
                "UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(version),)
            )
            self._conn.commit()

    # ---- settings -----------------------------------------------------

    @_locked
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute(
            "SELECT value_json FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return default

    @_locked
    def set_setting(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO settings(key, value_json) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        self._conn.commit()

    def set_settings(self, values: dict[str, Any]) -> None:
        """Atomically write multiple validated settings."""
        with self.transaction() as cursor:
            for key, value in values.items():
                cursor.execute(
                    "INSERT OR REPLACE INTO settings(key, value_json) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )

    # ---- events -------------------------------------------------------

    def upsert_events(self, events: list[Event]) -> int:
        count = 0
        with self.transaction() as cursor:
            for event in events:
                payload = event.model_dump(mode="json")
                payload["occurred_at"] = _dt_to_iso(payload.get("occurred_at"))
                payload["updated_at"] = _dt_to_iso(payload.get("updated_at"))
                payload["ingested_at"] = _dt_to_iso(payload.get("ingested_at"))
                payload["extra_json"] = json.dumps(payload.get("extra_json") or {})
                old = cursor.execute(
                    "SELECT rowid FROM events WHERE id = ?", (event.id,)
                ).fetchone()
                if old is not None:
                    # REPLACE reuses rowids; clear the old spatial row even
                    # when the new record has no coordinates.
                    cursor.execute("DELETE FROM events_rtree WHERE rowid = ?", (old[0],))
                cursor.execute(INSERT_OR_REPLACE_EVENT, payload)
                count += 1

                # Populate R-Tree for spatial queries
                if event.latitude is not None and event.longitude is not None:
                    row = cursor.execute("SELECT rowid FROM events WHERE id = ?", (event.id,)).fetchone()
                    if row:
                        cursor.execute(
                            "INSERT OR REPLACE INTO events_rtree VALUES (?, ?, ?, ?, ?)",
                            (row[0], event.latitude, event.latitude, event.longitude, event.longitude),
                        )
        return count

    @_locked
    def delete_events_not_in(self, source: str, keep_ids: list[str]) -> int:
        """Replace a source's current-state set (e.g. Sentry top-N)."""
        params: list[Any] = [source]
        if keep_ids:
            placeholders = ",".join("?" for _ in keep_ids)
            sql = f"DELETE FROM events WHERE source = ? AND id NOT IN ({placeholders})"
            params.extend(keep_ids)
        else:
            sql = "DELETE FROM events WHERE source = ?"
        cursor = self._conn.execute(sql, params)
        deleted = cursor.rowcount or 0
        self._conn.execute(
            "DELETE FROM events_rtree WHERE rowid NOT IN (SELECT rowid FROM events)"
        )
        self._conn.commit()
        return deleted

    def get_event_by_id(self, event_id: str) -> Event | None:
        """O(1) primary-key lookup for a single event."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM events WHERE id = ? LIMIT 1", (event_id,)
            ).fetchone()
        return self._row_to_event(row) if row else None

    @_locked
    def query_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        categories: list[str] | None = None,
        min_magnitude: float | None = None,
        limit: int = EVENT_LIMIT,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> list[Event]:
        conditions = ["1=1"]
        params: list[Any] = []
        if start is not None:
            conditions.append("occurred_at >= ?")
            params.append(_dt_to_iso(start))
        if end is not None:
            conditions.append("occurred_at <= ?")
            params.append(_dt_to_iso(end))
        if categories:
            placeholders = ",".join("?" for _ in categories)
            conditions.append(f"category IN ({placeholders})")
            params.extend(categories)
        if min_magnitude is not None:
            conditions.append("magnitude IS NOT NULL AND magnitude >= ?")
            params.append(min_magnitude)
        if bbox:
            min_lat, max_lat, min_lon, max_lon = bbox
            # Prefer the R-tree for map-viewport queries (only geolocated events
            # are indexed there). Rows are joined back to events by rowid, so
            # all other filters still apply.
            conditions.append(
                "events.rowid IN (SELECT rowid FROM events_rtree "
                "WHERE min_lat <= ? AND max_lat >= ? AND min_lon <= ? AND max_lon >= ?)"
            )
            params.extend([max_lat, min_lat, max_lon, min_lon])

        sql = f"SELECT * FROM events WHERE {' AND '.join(conditions)} ORDER BY occurred_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_event(row) for row in rows]

    @_locked
    def find_nearby_event(
        self,
        source: str,
        occurred_at: datetime,
        latitude: float,
        longitude: float,
        max_degrees: float = 1.5,
        max_hours: int = 2,
    ) -> Event | None:
        start = occurred_at - timedelta(hours=max_hours)
        end = occurred_at + timedelta(hours=max_hours)
        rows = self._conn.execute(
            """
            SELECT * FROM events
            WHERE source = ?
              AND occurred_at >= ? AND occurred_at <= ?
              AND latitude BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
            ORDER BY ABS(julianday(occurred_at) - julianday(?)) ASC
            LIMIT 1
            """,
            (
                source,
                _dt_to_iso(start),
                _dt_to_iso(end),
                latitude - max_degrees,
                latitude + max_degrees,
                longitude - max_degrees,
                longitude + max_degrees,
                _dt_to_iso(occurred_at),
            ),
        ).fetchall()
        if not rows:
            return None
        return self._row_to_event(rows[0])

    @_locked
    def event_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        return Event(
            id=row["id"],
            source=row["source"],
            upstream_id=row["upstream_id"],
            category=row["category"],
            title=row["title"],
            description=row["description"],
            occurred_at=_dt_from_iso(row["occurred_at"]),
            updated_at=_dt_from_iso(row["updated_at"]),
            latitude=row["latitude"],
            longitude=row["longitude"],
            depth_km=row["depth_km"],
            magnitude=row["magnitude"],
            magnitude_unit=row["magnitude_unit"],
            url=row["url"],
            raw_ref=row["raw_ref"],
            ingested_at=_dt_from_iso(row["ingested_at"]),
            extra_json=json.loads(row["extra_json"] or "{}"),
        )

    # ---- observations -------------------------------------------------

    def upsert_observations(self, observations: list[Observation]) -> int:
        count = 0
        with self.transaction() as cursor:
            for obs in observations:
                cursor.execute(
                    """
                    INSERT INTO observations (source, series, ts, value, unit, extra_json)
                    VALUES (:source, :series, :ts, :value, :unit, :extra_json)
                    ON CONFLICT(source, series, ts) DO UPDATE SET
                        value=excluded.value, unit=excluded.unit, extra_json=excluded.extra_json
                    """,
                    {
                        "source": obs.source,
                        "series": obs.series,
                        "ts": _dt_to_iso(obs.ts),
                        "value": obs.value,
                        "unit": obs.unit,
                        "extra_json": json.dumps(obs.extra_json),
                    },
                )
                count += 1
        return count

    def _observation_from_row(self, row: sqlite3.Row) -> Observation:
        return Observation(
            source=row["source"],
            series=row["series"],
            ts=_dt_from_iso(row["ts"]),
            value=row["value"],
            unit=row["unit"],
            extra_json=json.loads(row["extra_json"] or "{}"),
        )

    @_locked
    def latest_observations(self, source: str, prefix: str, since: datetime | None = None) -> list[Observation]:
        """Newest observation per matching series (SQL window query)."""
        conditions = ["source = ?", "series LIKE ?"]
        params: list[Any] = [source, f"{prefix}%"]
        if since is not None:
            conditions.append("ts >= ?")
            params.append(_dt_to_iso(since))
        sql = (
            "SELECT * FROM ("
            "  SELECT *, ROW_NUMBER() OVER (PARTITION BY series ORDER BY ts DESC) AS rn"
            f"  FROM observations WHERE {' AND '.join(conditions)}"
            ") WHERE rn = 1 ORDER BY series ASC"
        )
        rows = self._conn.execute(sql, params).fetchall()
        return [self._observation_from_row(row) for row in rows]

    @_locked
    def get_latest_observation(self, source: str, series: str) -> Observation | None:
        """Single newest observation for an exact source/series."""
        row = self._conn.execute(
            "SELECT * FROM observations WHERE source = ? AND series = ? "
            "ORDER BY ts DESC LIMIT 1",
            (source, series),
        ).fetchone()
        return self._observation_from_row(row) if row else None

    @_locked
    def get_series(
        self,
        source: str,
        series: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 10000,
        order: str = "asc",
    ) -> list[Observation]:
        conditions = ["source = ?", "series = ?"]
        params: list[Any] = [source, series]
        if start is not None:
            conditions.append("ts >= ?")
            params.append(_dt_to_iso(start))
        if end is not None:
            conditions.append("ts <= ?")
            params.append(_dt_to_iso(end))
        direction = "DESC" if str(order).lower() == "desc" else "ASC"
        safe_limit = max(1, int(limit))
        sql = (
            f"SELECT * FROM observations WHERE {' AND '.join(conditions)} "
            f"ORDER BY ts {direction} LIMIT ?"
        )
        params.append(safe_limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._observation_from_row(row) for row in rows]

    def get_recent_series(self, source: str, series: str, limit: int = 120) -> list[Observation]:
        """Newest *limit* observations, returned oldest-first for charts."""
        rows = self.get_series(source, series, limit=limit, order="desc")
        return list(reversed(rows))

    # ---- snapshots ----------------------------------------------------

    def _snapshot_path(self, sha256: str) -> Path:
        return self.snapshots_dir / sha256[:2] / sha256[2:4] / f"{sha256}.json.gz"

    def save_snapshot(
        self,
        source: str,
        url: str,
        payload: bytes,
        content_type: str,
        status_code: int | None = None,
        error: str | None = None,
        fetched_at: datetime | None = None,
        compress: bool = True,
    ) -> SnapshotRecord:
        import hashlib

        from .redact import redact_secrets, redact_url

        url = redact_url(url) or ""
        error = redact_secrets(error)
        # Include the source so identical payloads from different feeds do not
        # overwrite each other's provenance row.
        sha256 = hashlib.sha256(source.encode("utf-8") + b"\0" + payload).hexdigest()
        path = self._snapshot_path(sha256)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            if compress:
                with gzip.open(path, "wb") as handle:
                    handle.write(payload)
            else:
                path.write_bytes(payload)
        fetched_at = fetched_at or datetime.now(timezone.utc)
        record = SnapshotRecord(
            source=source,
            url=url,
            fetched_at=fetched_at,
            content_type=content_type,
            path=str(path),
            size_bytes=len(payload),
            status_code=status_code,
            error=error,
        )
        with self.transaction() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO snapshots (sha256, source, url, fetched_at, content_type, path, size_bytes, status_code, error)
                VALUES (:sha256, :source, :url, :fetched_at, :content_type, :path, :size_bytes, :status_code, :error)
                """,
                {
                    "sha256": sha256,
                    "source": source,
                    "url": url,
                    "fetched_at": _dt_to_iso(record.fetched_at),
                    "content_type": record.content_type,
                    "path": record.path,
                    "size_bytes": record.size_bytes,
                    "status_code": record.status_code,
                    "error": record.error,
                },
            )
        return record

    def save_asset(
        self,
        source: str,
        url: str,
        payload: bytes,
        content_type: str,
        status_code: int | None = None,
        error: str | None = None,
        fetched_at: datetime | None = None,
    ) -> None:
        fetched_at = fetched_at or datetime.now(timezone.utc)
        suffix = os.path.splitext(url.split("?")[0])[-1] or ".bin"
        # Microseconds keep multiple fetches in the same second distinct.
        name = f"{source}-{int(fetched_at.timestamp() * 1_000_000)}{suffix}"
        path = self.assets_dir / name
        path.write_bytes(payload)
        with self.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO assets (source, url, fetched_at, content_type, path, size_bytes, status_code, error)
                VALUES (:source, :url, :fetched_at, :content_type, :path, :size_bytes, :status_code, :error)
                """,
                {
                    "source": source,
                    "url": url,
                    "fetched_at": _dt_to_iso(fetched_at),
                    "content_type": content_type,
                    "path": str(path),
                    "size_bytes": len(payload),
                    "status_code": status_code,
                    "error": error,
                },
            )

    @_locked
    def latest_asset(self, source: str) -> str | None:
        row = self._conn.execute(
            "SELECT path FROM assets WHERE source = ? ORDER BY fetched_at DESC LIMIT 1",
            (source,),
        ).fetchone()
        return row[0] if row is not None else None

    @_locked
    def prune_observations_before(
        self,
        source: str,
        series_like: str,
        cutoff: datetime,
        exclude_series: tuple[str, ...] | list[str] | None = None,
    ) -> int:
        sql = "DELETE FROM observations WHERE source = ? AND series LIKE ? AND ts < ?"
        params: list[Any] = [source, series_like, _dt_to_iso(cutoff)]
        if exclude_series:
            placeholders = ",".join("?" for _ in exclude_series)
            sql += f" AND series NOT IN ({placeholders})"
            params.extend(exclude_series)
        cursor = self._conn.execute(sql, params)
        self._conn.commit()
        return cursor.rowcount if cursor.rowcount is not None else 0

    def prune_observations(self, retention_days: int | None = None) -> int:
        """Prune per-series retention policies, preserving solar-cycle context."""
        days = int(retention_days if retention_days is not None else (self.get_setting("retention_days") or 90))
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        policies: list[tuple[str, str, tuple[str, ...] | None]] = [
            ("swpc", "swpc:%", CYCLE_SERIES),
            ("aurora", "aurora:%", None),
            ("openmeteo", "weather:%", None),
            ("openmeteo", "air:%", None),
            ("openmeteo", "marine:%", None),
            ("openmeteo", "strato:%", None),
            ("geomag", "geomag:%", None),
            ("moon", "moon:%", None),
            ("solarwind", "solarwind:%", None),
        ]
        deleted = 0
        for source, prefix, exclude in policies:
            deleted += self.prune_observations_before(source, prefix, cutoff, exclude)
        return deleted

    @_locked
    def prune_snapshots_for_source(self, source: str, retention_days: int) -> int:
        from pathlib import Path as _Path

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        rows = self._conn.execute(
            "SELECT sha256, path FROM snapshots WHERE source = ? AND fetched_at < ?",
            (source, _dt_to_iso(cutoff)),
        ).fetchall()
        for row in rows:
            try:
                _Path(row["path"]).unlink(missing_ok=True)
            except OSError:
                pass
        self._conn.execute(
            "DELETE FROM snapshots WHERE source = ? AND fetched_at < ?",
            (source, _dt_to_iso(cutoff)),
        )
        self._conn.commit()
        return len(rows)

    @_locked
    def prune_snapshots(self, retention_days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        rows = self._conn.execute(
            "SELECT sha256, path FROM snapshots WHERE fetched_at < ?",
            (_dt_to_iso(cutoff),),
        ).fetchall()
        for row in rows:
            try:
                Path(row["path"]).unlink(missing_ok=True)
            except OSError:
                pass
        self._conn.execute(
            "DELETE FROM snapshots WHERE fetched_at < ?",
            (_dt_to_iso(cutoff),),
        )
        self._conn.commit()
        return len(rows)

    def prune_assets_for_source(self, source: str, keep_latest: int = 7, *, prefix: bool = False) -> int:
        """Keep only the N most recent assets, delete older files.

        ``prefix=True`` applies the keep-latest budget *per channel* (e.g. all
        ``sun_*`` channels) instead of treating them as one pool.
        """
        if prefix:
            with self._lock:
                sources = [
                    row[0]
                    for row in self._conn.execute(
                        "SELECT DISTINCT source FROM assets WHERE source LIKE ?", (f"{source}%",)
                    ).fetchall()
                ]
            return sum(
                self.prune_assets_for_source(item, keep_latest=keep_latest)
                for item in sources
            )
        with self._lock:
            rows = self._conn.execute(
                "SELECT path FROM assets WHERE source = ? ORDER BY fetched_at DESC",
                (source,),
            ).fetchall()
        paths_to_delete = [r[0] for r in rows[keep_latest:]]
        deleted = 0
        for path in paths_to_delete:
            try:
                Path(path).unlink(missing_ok=True)
                deleted += 1
            except OSError:
                pass
        if paths_to_delete:
            with self._lock:
                placeholders = ",".join("?" * len(paths_to_delete))
                self._conn.execute(
                    f"DELETE FROM assets WHERE source = ? AND path IN ({placeholders})",
                    [source] + paths_to_delete,
                )
                self._conn.commit()
        return deleted

    def _maybe_auto_prune(self) -> None:
        """Run retention pruning at most once per 24 hours."""
        last_raw = self.get_setting("last_prune_at")
        if last_raw:
            try:
                last = _dt_from_iso(last_raw)
                if last and (datetime.now(timezone.utc) - last).total_seconds() < 86400:
                    return
            except Exception:
                pass
        days = int(self.get_setting("retention_days") or 90)
        try:
            self.prune_snapshots(days)
            self.prune_observations(days)
            self.prune_assets_for_source("sun", keep_latest=14, prefix=True)
            self.set_setting("last_prune_at", datetime.now(timezone.utc).isoformat())
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto-prune failed: %s", exc)

    # ---- notifications ------------------------------------------------

    def add_notification(
        self,
        notif_id: str,
        event_id: str | None,
        category: str,
        title: str,
        severity: str,
        fired_at: datetime,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO notifications (id, event_id, category, title, severity, fired_at) VALUES (?, ?, ?, ?, ?, ?)",
                (notif_id, event_id, category, title, severity, _dt_to_iso(fired_at)),
            )
            self._conn.commit()

    def pending_notifications(self, since: datetime | None = None) -> list[dict]:
        """Return undelivered notifications."""
        with self._lock:
            if since:
                rows = self._conn.execute(
                    "SELECT id, event_id, category, title, severity, fired_at FROM notifications WHERE delivered_desktop = 0 AND fired_at >= ? ORDER BY fired_at DESC",
                    (_dt_to_iso(since),),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, event_id, category, title, severity, fired_at FROM notifications WHERE delivered_desktop = 0 ORDER BY fired_at DESC"
                ).fetchall()
        return [
            {"id": r[0], "event_id": r[1], "category": r[2], "title": r[3], "severity": r[4], "fired_at": r[5]}
            for r in rows
        ]

    def mark_notification_delivered(self, notif_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE notifications SET delivered_desktop = 1 WHERE id = ?", (notif_id,)
            )
            self._conn.commit()

    def dismiss_notification(self, notif_id: str) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._conn.execute(
                "UPDATE notifications SET dismissed_at = ? WHERE id = ?", (_dt_to_iso(now), notif_id)
            )
            self._conn.commit()

    # ---- source state -------------------------------------------------

    def upsert_source_state(self, state: SourceState) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO source_state (
                    source_id, last_attempt, last_success, last_error,
                    consecutive_failures, next_due, records_ingested
                ) VALUES (
                    :source_id, :last_attempt, :last_success, :last_error,
                    :consecutive_failures, :next_due, :records_ingested
                )
                """,
                {
                    "source_id": state.source_id,
                    "last_attempt": _dt_to_iso(state.last_attempt),
                    "last_success": _dt_to_iso(state.last_success),
                    "last_error": state.last_error,
                    "consecutive_failures": state.consecutive_failures,
                    "next_due": _dt_to_iso(state.next_due),
                    "records_ingested": state.records_ingested,
                },
            )

    @_locked
    def all_source_states(self) -> list[SourceState]:
        rows = self._conn.execute(
            "SELECT * FROM source_state ORDER BY source_id"
        ).fetchall()
        return [
            SourceState(
                source_id=row["source_id"],
                last_attempt=_dt_from_iso(row["last_attempt"]),
                last_success=_dt_from_iso(row["last_success"]),
                last_error=row["last_error"],
                consecutive_failures=row["consecutive_failures"],
                next_due=_dt_from_iso(row["next_due"]),
                records_ingested=row["records_ingested"],
            )
            for row in rows
        ]

    @_locked
    def begin_attempt(self, source_id: str, now: datetime) -> None:
        row = self._conn.execute(
            "SELECT * FROM source_state WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO source_state (source_id, last_attempt, next_due, consecutive_failures) VALUES (?, ?, ?, 0)",
                (source_id, _dt_to_iso(now), _dt_to_iso(now)),
            )
        else:
            self._conn.execute(
                "UPDATE source_state SET last_attempt = ? WHERE source_id = ?",
                (_dt_to_iso(now), source_id),
            )
        self._conn.commit()

    @_locked
    def record_success(self, source_id: str, now: datetime, records: int = 0, cadence_seconds: int = 3600) -> None:
        row = self._conn.execute(
            "SELECT records_ingested FROM source_state WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        existing = row[0] if row is not None else 0
        state = SourceState(
            source_id=source_id,
            last_attempt=now,
            last_success=now,
            last_error=None,
            consecutive_failures=0,
            next_due=now + timedelta(seconds=cadence_seconds),
            records_ingested=existing + records,
        )
        self.upsert_source_state(state)
        self._maybe_auto_prune()

    @_locked
    def record_failure(self, source_id: str, now: datetime, error: str, cadence_seconds: int = 3600) -> None:
        from .redact import redact_secrets

        error = redact_secrets(error) or ""
        row = self._conn.execute(
            "SELECT consecutive_failures, records_ingested, last_success FROM source_state WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row is None:
            failures = 1
            records = 0
            last_success = None
        else:
            failures = row[0] + 1
            records = row[1]
            last_success = _dt_from_iso(row[2])
        state = SourceState(
            source_id=source_id,
            last_attempt=now,
            last_success=last_success,
            last_error=error,
            consecutive_failures=failures,
            next_due=now + timedelta(seconds=min(cadence_seconds * (2 ** min(failures, 8)), 21600)),
            records_ingested=records,
        )
        self.upsert_source_state(state)

    @_locked
    def due_sources(self, now: datetime) -> list[str]:
        tracked = {
            row[0]
            for row in self._conn.execute(
                "SELECT source_id FROM source_state WHERE next_due IS NOT NULL AND next_due > ?",
                (_dt_to_iso(now),),
            ).fetchall()
        }
        # All known specs minus already-tracked sources that are not yet due.
        return [sid for sid in self._known_sources() if sid not in tracked]

    def _known_sources(self) -> list[str]:
        from .sources.registry import SPECS

        return sorted(SPECS.keys())


    # ---- stats / backup ----------------------------------------------

    @_locked
    def counts(self) -> dict[str, int]:
        """SQL-only counts (no filesystem walk) for SSE/health payloads."""
        return {
            "events": int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
            "observations": int(self._conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]),
            "snapshots": int(self._conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]),
            "assets": int(self._conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]),
        }

    @_locked
    def stats(self) -> dict[str, Any]:
        event_count = int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        obs_count = int(self._conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0])
        snap_count = self._conn.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM snapshots").fetchone()
        asset_count = int(self._conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0])
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        snap_total = sum(f.stat().st_size for f in self.snapshots_dir.rglob("*") if f.is_file())
        asset_total = sum(f.stat().st_size for f in self.assets_dir.rglob("*") if f.is_file())
        return {
            "events": event_count,
            "observations": obs_count,
            "snapshots": snap_count[0],
            "snapshot_bytes": snap_count[1] or 0,
            "assets": asset_count,
            "asset_bytes": asset_total,
            "db_bytes": db_size,
            "snapshots_dir": str(self.snapshots_dir),
            "assets_dir": str(self.assets_dir),
            "db_path": str(self.db_path),
        }

    def export_backup(self, dest: Path) -> Path:
        import tarfile

        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_db = dest.parent / f"{dest.name}.tmpdb"
        if tmp_db.exists():
            tmp_db.unlink()
        backup_conn = sqlite3.connect(str(tmp_db))
        with self._lock:
            self._conn.backup(backup_conn)
        backup_conn.close()
        dest.unlink(missing_ok=True)
        with tarfile.open(dest, "w:gz") as tar:
            tar.add(tmp_db, arcname="ssnow.sqlite")
            for f in sorted(self.snapshots_dir.rglob("*")):
                if f.is_file():
                    tar.add(f, arcname=str(f.relative_to(self.snapshots_dir.parent)))
            for f in sorted(self.assets_dir.rglob("*")):
                if f.is_file():
                    tar.add(f, arcname=str(f.relative_to(self.assets_dir.parent)))
        tmp_db.unlink(missing_ok=True)
        return dest

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
