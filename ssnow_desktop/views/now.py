"""Now dashboard view."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QVBoxLayout,
)

from .base_view import BaseView

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


class _Card(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setFrameStyle(QFrame.Box | QFrame.Plain)
        self.setStyleSheet(
            "QFrame { background: white; border: 1px solid #ddd; border-radius: 8px; }"
            "QLabel#value { font-size: 20px; font-weight: 600; color: #111; }"
            "QLabel#meta { color: #666; font-size: 12px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #444; text-transform: uppercase; letter-spacing: 0.5px;")
        self.value_lbl = QLabel("—")
        self.value_lbl.setObjectName("value")
        self.meta_lbl = QLabel("no data")
        self.meta_lbl.setObjectName("meta")
        self.meta_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)
        layout.addWidget(self.value_lbl)
        layout.addWidget(self.meta_lbl)

    def set_value(self, text: str) -> None:
        self.value_lbl.setText(text)

    def set_meta(self, text: str) -> None:
        self.meta_lbl.setText(text)


class NowView(BaseView):
    def __init__(self, store, parent=None) -> None:
        super().__init__(store, parent)
        self._cards: dict[str, _Card] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        grid = QGridLayout(self)
        grid.setSpacing(12)

        card_titles = [
            "Latest Earthquake",
            "Space Weather (Kp)",
            "Aurora Tonight",
            "Moon Phase",
            "Local Weather",
            "Solar Activity Threat",
        ]
        for position, title in enumerate(card_titles):
            card = _Card(title)
            self._cards[title] = card
            grid.addWidget(card, position // 3, position % 3)

    def refresh(self) -> None:
        cards = self._cards

        # 1. Quake
        quakes = self.store.query_events(categories=["earthquake"], limit=1)
        if quakes:
            q = quakes[0]
            cards["Latest Earthquake"].set_value(f"{q.magnitude:.1f} M" if q.magnitude is not None else "—")
            cards["Latest Earthquake"].set_meta(
                f"{q.category} · {q.title} · {fmt_ts(q.occurred_at)} · {q.latitude:.2f}, {q.longitude:.2f}" if q.latitude is not None else f"{q.title} · {fmt_ts(q.occurred_at)} · USGS"
            )
        else:
            cards["Latest Earthquake"].set_value("—")
            cards["Latest Earthquake"].set_meta("No recent earthquakes")

        # 2. Kp
        current_kp = 0.0
        kp = self.store.latest_observations("swpc", "swpc:kp")
        if kp:
            obs = kp[0]
            current_kp = obs.value
            cards["Space Weather (Kp)"].set_value(f"{obs.value:.1f}")
            cards["Space Weather (Kp)"].set_meta(f"Kp index · {fmt_ts(obs.ts)} · NOAA SWPC")
        else:
            cards["Space Weather (Kp)"].set_value("—")
            cards["Space Weather (Kp)"].set_meta("No Kp data yet")

        # 3. Aurora Tonight Visibility
        locations = self.store.get_setting("locations") or []
        loc = locations[0] if locations else self.store.get_setting("location") or {"lat": 51.5074, "lon": -0.1278, "name": "London"}
        lat = abs(float(loc.get("lat", 51.5)))
        loc_name = loc.get("name", "Local")

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

        if current_kp >= kp_threshold:
            aurora_verdict = "Look Outside Now!"
        elif current_kp >= kp_threshold - 1.0 and kp_threshold > 1:
            aurora_verdict = "Possible on Horizon"
        else:
            aurora_verdict = "Unlikely Tonight"

        cards["Aurora Tonight"].set_value(aurora_verdict)
        cards["Aurora Tonight"].set_meta(
            f"{loc_name} ({lat:.1f}°) needs Kp ≥ {kp_threshold} · Current Kp: {current_kp:.1f}"
        )

        # 4. Moon
        moon_state = self.store.get_setting("moon_state") or {}
        if moon_state:
            illum = moon_state.get("illumination")
            cards["Moon Phase"].set_value(
                f"{moon_state.get('phase_name', '—')} ({illum*100:.0f}%)" if illum is not None else moon_state.get("phase_name", "—")
            )
            cards["Moon Phase"].set_meta(f"distance {moon_state.get('distance_km', 0):,.0f} km · {moon_state.get('source', '—')}")
        else:
            cards["Moon Phase"].set_value("—")
            cards["Moon Phase"].set_meta("No moon data yet")

        # 5. Weather
        if locations:
            primary_loc = locations[0]
            key = primary_loc.get("key") or f"{primary_loc.get('lat')},{primary_loc.get('lon')}"
            temps = self.store.latest_observations("openmeteo", f"weather:{key}:temperature_2m")
            if temps:
                obs = temps[0]
                cards["Local Weather"].set_value(f"{obs.value:.1f}°C")
                aqi = self.store.latest_observations("openmeteo", f"air:{key}:us_aqi")
                aqi_text = f" · AQI {aqi[0].value:.0f}" if aqi else ""
                cards["Local Weather"].set_meta(f"{primary_loc.get('name', 'Location')} · {fmt_ts(obs.ts)} · Open-Meteo{aqi_text}")
            else:
                cards["Local Weather"].set_value("—")
                cards["Local Weather"].set_meta(f"{primary_loc.get('name', 'Location')} — no forecast yet")
        else:
            cards["Local Weather"].set_value("—")
            cards["Local Weather"].set_meta("Add a location in Settings")

        # 6. Solar Activity Threat
        xray = self.store.get_series("swpc", "swpc:xray_flux", limit=1)
        wind = self.store.get_series("swpc", "swpc:solarwind_speed", limit=1)
        bz_s = self.store.get_series("swpc", "swpc:imf_bz_gsm", limit=1)
        proton = self.store.get_series("swpc", "swpc:proton_flux_gte10MeV", limit=1)
        dst_s = self.store.get_series("swpc", "swpc:dst", limit=1)
        flare_class = xray[-1].extra_json.get("class", "A") if xray else "A"
        wind_speed = wind[-1].value if wind else 350.0
        bz = bz_s[-1].value if bz_s else 0.0
        pflux = proton[-1].value if proton else 0.0
        dst = dst_s[-1].value if dst_s else 0.0

        if flare_class.startswith("X") or current_kp >= 7 or pflux >= 1000 or dst <= -100:
            threat = "STORM (Level 4/4)"
        elif flare_class.startswith("M") or current_kp >= 5 or wind_speed >= 600 or bz <= -10 or pflux >= 10:
            threat = "ELEVATED (Level 3/4)"
        elif flare_class.startswith("C") or current_kp >= 4 or wind_speed >= 450 or bz < 0:
            threat = "UNSETTLED (Level 2/4)"
        else:
            threat = "QUIET (Level 1/4)"

        cards["Solar Activity Threat"].set_value(threat)
        cards["Solar Activity Threat"].set_meta(
            f"GOES Flare: {flare_class}-class · Wind: {wind_speed:.0f} km/s · Kp: {current_kp:.1f} · Bz: {bz:.1f} nT"
        )
