"""Now dashboard view — the broadcast hero screen."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from .base_view import BaseView
from .widgets.sparkline import Sparkline

CATEGORIES = [
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


def fmt_ts(value) -> str:
    if value is None:
        return "—"
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class ThreatDial(QWidget):
    """Four-arc composite threat gauge (QUIET → STORM)."""

    LEVELS = ("QUIET", "UNSETTLED", "ELEVATED", "STORM")
    COLORS = (theme.OK, theme.WARN, theme.ORANGE, theme.DANGER)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.level = -1
        self.subtitle = "no data"
        self.setMinimumSize(190, 130)

    def set_level(self, level: int, subtitle: str = "") -> None:
        self.level = max(0, min(int(level), 3))
        self.subtitle = subtitle
        self.update()

    def set_unknown(self, subtitle: str = "no data") -> None:
        self.level = -1
        self.subtitle = subtitle
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h * 0.76
        radius = min(w * 0.42, h * 0.62)
        start_deg, span_deg = 200.0, 140.0
        # Track
        track = QPen(QColor(theme.BORDER), 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(
            int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2),
            int(start_deg * 16), int(-span_deg * 16),
        )
        # Filled portion up to current level (no fill when data is unknown).
        known = self.level >= 0
        frac = (self.level + 1) / 4.0 if known else 0.0
        color = self.COLORS[self.level] if known else theme.TEXT_FAINT
        if known:
            pen = QPen(QColor(color), 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(
                int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2),
                int(start_deg * 16), int(-span_deg * frac * 16),
            )
        # Level ticks
        for i in range(4):
            ang = math.radians(start_deg - span_deg * (i + 0.5) / 4.0)
            x = cx + (radius + 14) * math.cos(ang)
            y = cy - (radius + 14) * math.sin(ang)
            painter.setPen(QPen(QColor(self.COLORS[i]), 3))
            painter.drawPoint(QPointF(x, y))
        # Label
        font = QFont()
        font.setPixelSize(20)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(color)))
        painter.drawText(
            int(cx - radius), int(cy - radius * 0.62), int(radius * 2), 30,
            Qt.AlignmentFlag.AlignCenter,
            self.LEVELS[self.level] if known else "NO DATA",
        )
        font.setPixelSize(10)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QPen(QColor(theme.TEXT_FAINT)))
        painter.drawText(
            int(cx - radius), int(cy - radius * 0.62) + 30, int(radius * 2), 18,
            Qt.AlignmentFlag.AlignCenter, f"{self.level + 1} / 4" if known else "waiting for data",
        )
        if self.subtitle:
            painter.drawText(
                int(cx - radius), int(cy + 4), int(radius * 2), 18,
                Qt.AlignmentFlag.AlignCenter, self.subtitle[:64],
            )


class _Card(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setStyleSheet(theme.card_style())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(3)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("cardTitle")
        self.value_lbl = QLabel("—")
        self.value_lbl.setObjectName("cardValue")
        self.meta_lbl = QLabel("no data")
        self.meta_lbl.setObjectName("cardMeta")
        self.meta_lbl.setWordWrap(True)
        layout.addWidget(self.title_lbl)
        layout.addWidget(self.value_lbl)
        layout.addWidget(self.meta_lbl)
        layout.addStretch(1)

    def set_value(self, text: str, color: str | None = None) -> None:
        self.value_lbl.setText(text)
        # Long verdicts/names need a smaller size to fit the card width.
        size = 26 if len(text) > 14 else 30
        css = f"font-size: {size}px;"
        if color:
            css += f" color: {color};"
        self.value_lbl.setStyleSheet(css if color or len(text) > 14 else "")

    def set_meta(self, text: str) -> None:
        self.meta_lbl.setText(text)

    def set_accent(self, color: str | None) -> None:
        self.setStyleSheet(theme.card_style(color))


class NowView(BaseView):
    def __init__(self, store, parent=None) -> None:
        super().__init__(store, parent)
        self._cards: dict[str, _Card] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(14)

        head = QLabel("SOLAR SYSTEM NOW")
        head.setObjectName("h2")
        outer.addWidget(head)

        grid = QGridLayout()
        grid.setSpacing(12)
        for col in range(3):
            grid.setColumnStretch(col, 1)

        card_titles = [
            "Solar Activity Threat",
            "Space Weather (Kp)",
            "Aurora Tonight",
            "Latest Earthquake",
            "Moon Phase",
            "Local Weather",
            "Next Close Approach",
            "Latest CME",
        ]
        for title in card_titles:
            self._cards[title] = _Card(title)

        # Threat dial card (col 0, row 0).
        self._dial_card = QFrame()
        self._dial_card.setObjectName("card")
        self._dial_card.setStyleSheet(theme.card_style())
        dial_layout = QVBoxLayout(self._dial_card)
        dial_layout.setContentsMargins(14, 10, 14, 10)
        dial_layout.setSpacing(0)
        dial_title = QLabel("Composite Threat")
        dial_title.setObjectName("cardTitle")
        dial_layout.addWidget(dial_title)
        self.dial = ThreatDial()
        dial_layout.addWidget(self.dial, 1)

        grid.addWidget(self._dial_card, 0, 0)
        grid.addWidget(self._cards["Solar Activity Threat"], 0, 1)
        grid.addWidget(self._cards["Space Weather (Kp)"], 0, 2)
        grid.addWidget(self._cards["Aurora Tonight"], 1, 0)
        grid.addWidget(self._cards["Latest Earthquake"], 1, 1)
        grid.addWidget(self._cards["Moon Phase"], 1, 2)
        grid.addWidget(self._cards["Local Weather"], 2, 0)
        grid.addWidget(self._cards["Next Close Approach"], 2, 1)
        grid.addWidget(self._cards["Latest CME"], 2, 2)

        # Wide Kp trend strip — fills the hero screen and reads well on stream.
        trend_card = QFrame()
        trend_card.setObjectName("card")
        trend_card.setStyleSheet(theme.card_style())
        trend_layout = QVBoxLayout(trend_card)
        trend_layout.setContentsMargins(16, 12, 16, 10)
        trend_layout.setSpacing(2)
        trend_title = QLabel("Geomagnetic Trend — planetary K-index")
        trend_title.setObjectName("cardTitle")
        self.trend_spark = Sparkline()
        self.trend_spark.setMinimumHeight(96)
        trend_layout.addWidget(trend_title)
        trend_layout.addWidget(self.trend_spark)
        grid.addWidget(trend_card, 3, 0, 1, 3)

        outer.addLayout(grid)

        self.footer = QLabel(
            "32 live sources · USGS · NOAA SWPC/SPC/NWS · NASA JPL/SDO/DONKI · EONET · Open-Meteo · IEM"
        )
        self.footer.setObjectName("source")
        outer.addWidget(self.footer)
        outer.addStretch(1)

    def refresh(self) -> None:
        cards = self._cards

        # --- Gather inputs once -------------------------------------------
        quakes = self.store.query_events(categories=["earthquake"], limit=1)
        kp_obs = self.store.get_latest_observation("swpc", "swpc:kp")
        current_kp = kp_obs.value if kp_obs else None
        locations = [loc for loc in (self.store.get_setting("locations") or []) if isinstance(loc, dict)]
        legacy_loc = self.store.get_setting("location")
        loc = (
            locations[0]
            if locations
            else (legacy_loc if isinstance(legacy_loc, dict) else {"lat": 51.5074, "lon": -0.1278, "name": "London"})
        )
        try:
            lat = abs(float(loc.get("lat", 51.5)))
        except (TypeError, ValueError):
            lat = 51.5
        loc_name = loc.get("name") or "Local"
        moon_state = self.store.get_setting("moon_state") or {}
        xray = self.store.get_latest_observation("swpc", "swpc:xray_flux")
        wind = self.store.get_latest_observation("swpc", "swpc:solarwind_speed")
        bz_s = self.store.get_latest_observation("swpc", "swpc:imf_bz_gsm")
        proton = self.store.get_latest_observation("swpc", "swpc:proton_flux_gte10MeV")
        dst_s = self.store.get_latest_observation("swpc", "swpc:dst")
        flare_class = (xray.extra_json.get("class") if xray else None)
        wind_speed = wind.value if wind else None
        bz = bz_s.value if bz_s else None
        pflux = proton.value if proton else None
        dst = dst_s.value if dst_s else None

        # --- Threat (4-level composite, only from real inputs) ------------
        has_inputs = any(v is not None for v in (current_kp, flare_class, wind_speed, bz, pflux, dst))
        level = 0
        if flare_class and flare_class.startswith("X"):
            level = 3
        elif flare_class and flare_class.startswith("M"):
            level = max(level, 2)
        elif flare_class and flare_class.startswith("C"):
            level = max(level, 1)
        if current_kp is not None:
            level = max(level, 3 if current_kp >= 7 else 2 if current_kp >= 5 else 1 if current_kp >= 4 else 0)
        if wind_speed is not None:
            level = max(level, 2 if wind_speed >= 600 else 1 if wind_speed >= 450 else 0)
        if bz is not None:
            level = max(level, 2 if bz <= -10 else 1 if bz < 0 else 0)
        if pflux is not None:
            level = max(level, 3 if pflux >= 1000 else 2 if pflux >= 10 else 0)
        if dst is not None and dst <= -100:
            level = 3
        threat = ThreatDial.LEVELS[level]
        threat_parts = []
        if flare_class:
            threat_parts.append(f"Flare {flare_class}-class")
        if wind_speed is not None:
            threat_parts.append(f"Wind {wind_speed:.0f} km/s")
        if bz is not None:
            threat_parts.append(f"Bz {bz:.1f} nT")
        if current_kp is not None:
            threat_parts.append(f"Kp {current_kp:.1f}")
        if pflux is not None:
            threat_parts.append(f"p+ {pflux:.1f} pfu")
        if dst is not None:
            threat_parts.append(f"Dst {dst:.0f} nT")
        if not has_inputs:
            self.dial.set_unknown("waiting for Kp / X-ray / wind")
            cards["Solar Activity Threat"].set_value("NO DATA", theme.TEXT_FAINT)
            cards["Solar Activity Threat"].set_meta("No space-weather observations yet")
            cards["Solar Activity Threat"].set_accent(None)
        else:
            color = ThreatDial.COLORS[level]
            dial_sub = " · ".join(
                part for part in (
                    f"Kp {current_kp:.1f}" if current_kp is not None else "",
                    f"Bz {bz:.1f} nT" if bz is not None else "",
                ) if part
            ) or "partial data"
            self.dial.set_level(level, dial_sub)
            cards["Solar Activity Threat"].set_value(f"{threat} ({level + 1}/4)", color)
            cards["Solar Activity Threat"].set_meta(" · ".join(threat_parts))
            cards["Solar Activity Threat"].set_accent(color)

        # --- Kp ------------------------------------------------------------
        if kp_obs:
            obs = kp_obs
            kp_color = theme.DANGER if obs.value >= 6 else (theme.WARN if obs.value >= 4 else theme.OK)
            cards["Space Weather (Kp)"].set_value(f"{obs.value:.1f}", kp_color)
            cards["Space Weather (Kp)"].set_meta(f"Planetary K-index · {fmt_ts(obs.ts)} · NOAA SWPC")
            cards["Space Weather (Kp)"].set_accent(kp_color)
        else:
            cards["Space Weather (Kp)"].set_value("—", theme.TEXT_FAINT)
            cards["Space Weather (Kp)"].set_meta("No Kp data yet")
            cards["Space Weather (Kp)"].set_accent(None)

        # --- Aurora --------------------------------------------------------
        if lat >= 65:
            kp_threshold = 1
        elif lat >= 60:
            kp_threshold = 2
        elif lat >= 55:
            kp_threshold = 4
        elif lat >= 50:
            kp_threshold = 6
        elif lat >= 45:
            kp_threshold = 7
        else:
            kp_threshold = 8

        aurora_max = self.store.get_latest_observation("aurora", "aurora:intensity_max")
        aurora_oval = self.store.get_latest_observation("aurora", "aurora:oval_equatorward_deg")
        ovation = ""
        if aurora_max or aurora_oval:
            parts = []
            if aurora_max:
                parts.append(f"OVATION max {aurora_max.value:.0f}")
            if aurora_oval:
                parts.append(f"oval edge {aurora_oval.value:.1f}°")
            ovation = f" · {' · '.join(parts)}"
        if current_kp is None:
            cards["Aurora Tonight"].set_value("—", theme.TEXT_FAINT)
            cards["Aurora Tonight"].set_meta(f"{loc_name} ({lat:.1f}°) · no Kp data yet{ovation}")
            cards["Aurora Tonight"].set_accent(None)
        else:
            if current_kp >= kp_threshold:
                verdict, aurora_color = "Look outside now", theme.OK
            elif current_kp >= kp_threshold - 1.0 and kp_threshold > 1:
                verdict, aurora_color = "Possible on horizon", theme.WARN
            else:
                verdict, aurora_color = "Unlikely tonight", theme.TEXT_DIM
            cards["Aurora Tonight"].set_value(verdict, aurora_color)
            cards["Aurora Tonight"].set_meta(
                f"{loc_name} ({lat:.1f}°) needs Kp ≥ {kp_threshold} · now {current_kp:.1f}{ovation}"
            )
            cards["Aurora Tonight"].set_accent(aurora_color if aurora_color != theme.TEXT_DIM else None)

        # --- Earthquake ----------------------------------------------------
        if quakes:
            q = quakes[0]
            quake_color = theme.DANGER if (q.magnitude or 0) >= 6 else (theme.WARN if (q.magnitude or 0) >= 5 else theme.TEXT)
            cards["Latest Earthquake"].set_value(f"M {q.magnitude:.1f}" if q.magnitude is not None else "—", quake_color)
            tsunami = " · 🌊 TSUNAMI" if (q.extra_json or {}).get("tsunami") in (1, True) else ""
            cards["Latest Earthquake"].set_meta(f"{q.title} · {fmt_ts(q.occurred_at)}{tsunami}")
            cards["Latest Earthquake"].set_accent(quake_color if quake_color != theme.TEXT else None)
        else:
            cards["Latest Earthquake"].set_value("—", theme.TEXT_FAINT)
            cards["Latest Earthquake"].set_meta("No recent earthquakes")
            cards["Latest Earthquake"].set_accent(None)

        # --- Moon ----------------------------------------------------------
        if moon_state:
            illum = moon_state.get("illumination")
            cards["Moon Phase"].set_value(
                f"{illum * 100:.0f}%" if illum is not None else "—", theme.VIOLET
            )
            distance = moon_state.get("distance_km")
            distance_text = f"{float(distance):,.0f} km" if distance is not None else "distance —"
            cards["Moon Phase"].set_meta(f"{moon_state.get('phase_name', '—')} · {distance_text}")
            cards["Moon Phase"].set_accent(theme.VIOLET)
        else:
            cards["Moon Phase"].set_value("—", theme.TEXT_FAINT)
            cards["Moon Phase"].set_meta("No moon data yet")
            cards["Moon Phase"].set_accent(None)

        # --- Weather -------------------------------------------------------
        primary_loc = loc if isinstance(loc, dict) else None
        if primary_loc:
            key = primary_loc.get("key") or f"{primary_loc.get('lat')},{primary_loc.get('lon')}"
            temp = self.store.get_latest_observation("openmeteo", f"weather:{key}:temperature_2m")
            if temp:
                cards["Local Weather"].set_value(f"{temp.value:.1f}°C", theme.ACCENT)
                aqi = self.store.get_latest_observation("openmeteo", f"air:{key}:us_aqi")
                aqi_text = f" · AQI {aqi.value:.0f}" if aqi else ""
                marine = self.store.get_latest_observation("openmeteo", f"marine:{key}:wave_height")
                marine_text = f" · waves {marine.value:.1f} m" if marine else ""
                wind_obs = self.store.get_latest_observation("openmeteo", f"weather:{key}:wind_speed_10m")
                wind_text = f" · wind {wind_obs.value:.0f} km/h" if wind_obs else ""
                cards["Local Weather"].set_meta(f"{primary_loc.get('name', 'Location')} · {fmt_ts(temp.ts)}{aqi_text}{wind_text}{marine_text}")
                cards["Local Weather"].set_accent(theme.ACCENT)
            else:
                cards["Local Weather"].set_value("—", theme.TEXT_FAINT)
                cards["Local Weather"].set_meta(f"{primary_loc.get('name', 'Location')} — no forecast yet")
                cards["Local Weather"].set_accent(None)
        else:
            cards["Local Weather"].set_value("—", theme.TEXT_FAINT)
            cards["Local Weather"].set_meta("Add a location in Settings")
            cards["Local Weather"].set_accent(None)

        # --- Next close approach (future only) ------------------------------
        try:
            now_dt = datetime.now(timezone.utc)
            neos = self.store.query_events(categories=["neo"], limit=500)
            upcoming = []
            for n in neos:
                ex = n.extra_json or {}
                if (ex.get("kind") or "") == "sentry":
                    continue
                if n.occurred_at is None or n.occurred_at < now_dt:
                    continue
                try:
                    raw = ex.get("dist_lunar")
                    ld = float(raw) if raw not in (None, "") else float(ex.get("miss_lunar"))
                except (TypeError, ValueError):
                    ld = None
                upcoming.append((n.occurred_at, n, ld))
            if upcoming:
                _, n, ld = min(upcoming, key=lambda item: item[0])
                ex = n.extra_json or {}
                hazardous = bool(ex.get("hazardous") or ex.get("hazardous_candidate")) and not ex.get("is_comet")
                name = ex.get("fullname") or ex.get("des") or n.title
                cards["Next Close Approach"].set_value(
                    f"{ld:.2f} LD" if ld is not None else "—",
                    theme.DANGER if hazardous or (ld is not None and ld < 1) else theme.LIME,
                )
                kind = ex.get("kind") or ("comet" if ex.get("is_comet") else "asteroid")
                cards["Next Close Approach"].set_meta(f"{str(name)[:48]} · {kind} · {fmt_ts(n.occurred_at)}")
                cards["Next Close Approach"].set_accent(theme.DANGER if hazardous else theme.LIME)
            else:
                cards["Next Close Approach"].set_value("—", theme.TEXT_FAINT)
                cards["Next Close Approach"].set_meta("No upcoming close approaches")
                cards["Next Close Approach"].set_accent(None)
        except Exception:
            cards["Next Close Approach"].set_value("—", theme.TEXT_FAINT)
            cards["Next Close Approach"].set_meta("No upcoming close approaches")
            cards["Next Close Approach"].set_accent(None)

        # --- Latest CME (+ labelled SIM only with measured inputs) ---------
        try:
            from ssnow_core.sim import get_scenario
            from ssnow_core.sim.flare import flare_class_from_flux
            from ssnow_core.sources.donki import is_earth_directed

            cmes = self.store.query_events(categories=["cme"], limit=20)
            if cmes:
                c = cmes[0]  # query_events is newest-first
                ex = c.extra_json or {}
                try:
                    speed_val = float(ex.get("speed")) if ex.get("speed") not in (None, "") else None
                except (TypeError, ValueError):
                    speed_val = None
                directed = is_earth_directed(ex)
                ctype = ex.get("type") or "?"
                cards["Latest CME"].set_value(
                    f"{speed_val:.0f} km/s" if speed_val is not None else "—",
                    theme.PINK if directed else theme.TEXT_DIM,
                )
                meta = f"type {ctype} · {'Earth-directed' if directed else 'not Earth-directed'} · {fmt_ts(c.occurred_at)}"
                flare = flare_class_from_flux(float(xray.value)) if xray is not None else None
                if directed and speed_val is not None and flare is not None:
                    try:
                        age_hours = 0.0
                        if c.occurred_at is not None:
                            age_hours = max(0.0, (now_dt - c.occurred_at).total_seconds() / 3600.0)
                        scenario = get_scenario("flare_arrival")
                        res = scenario().run({
                            "cme_speed_km_s": speed_val,
                            "distance_au": 1.0,
                            "flare_class": flare[0],
                            "flare_subclass": flare[1],
                            "elapsed_hours": min(age_hours, 240.0),
                        })
                        total = float(res.get("total_travel_hours") or 0.0)
                        if total > 0 and age_hours > total * 1.25:
                            meta += " · SIM window elapsed"
                        else:
                            meta += f" · SIM ~{res['arrival_window_low_hours']:.0f}–{res['arrival_window_high_hours']:.0f}h"
                    except Exception:
                        meta += " · SIM unavailable"
                elif speed_val is None:
                    meta += " · SIM needs measured speed"
                elif not directed:
                    meta += " · SIM needs Earth-directed event"
                else:
                    meta += " · SIM needs measured X-ray flux"
                cards["Latest CME"].set_meta(meta)
                cards["Latest CME"].set_accent(theme.PINK if directed else None)
            else:
                cards["Latest CME"].set_value("—", theme.TEXT_FAINT)
                cards["Latest CME"].set_meta("No CME in window")
                cards["Latest CME"].set_accent(None)
        except Exception:
            cards["Latest CME"].set_value("—", theme.TEXT_FAINT)
            cards["Latest CME"].set_meta("No CME in window")
            cards["Latest CME"].set_accent(None)

        # --- Kp trend -------------------------------------------------------
        try:
            series = self.store.get_recent_series("swpc", "swpc:kp", limit=120)
            if series:
                pts = [(o.ts.timestamp(), o.value) for o in series]
                ys = [o.value for o in series]
                self.trend_spark.set_points(pts, min_value=0, max_value=max(9.0, max(ys)))
            else:
                self.trend_spark.set_points([], min_value=0, max_value=9)
        except Exception:
            self.trend_spark.set_points([], min_value=0, max_value=9)
