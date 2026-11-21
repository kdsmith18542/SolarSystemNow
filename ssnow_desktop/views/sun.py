"""Sun / space weather view."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from .base_view import BaseView
from .widgets.sparkline import Sparkline


def fmt_ts(value) -> str:
    if value is None:
        return "—"
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class SunView(BaseView):
    def __init__(self, store, parent=None) -> None:
        super().__init__(store, parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        top = QHBoxLayout()
        self.kp_value = QLabel("—")
        self.kp_value.setObjectName("cardValue")
        self.kp_meta = QLabel("No Kp data yet")
        self.kp_meta.setObjectName("muted")
        top.addWidget(self.kp_value)
        top.addWidget(self.kp_meta)
        top.addStretch(1)
        layout.addLayout(top)

        self.spark = Sparkline()
        layout.addWidget(self.spark)

        img_row = QHBoxLayout()
        self.image_lbl = QLabel("No solar image yet")
        self.image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_lbl.setObjectName("card")
        self.image_lbl.setMinimumHeight(260)
        img_row.addWidget(self.image_lbl)
        img_row.addStretch(1)
        layout.addLayout(img_row)

        form = QFormLayout()
        self.status_lbl = QLabel("—")
        form.addRow("Status:", self.status_lbl)
        self.xray_lbl = QLabel("—")
        form.addRow("GOES X-ray (0.1–0.8 nm):", self.xray_lbl)
        self.f107_lbl = QLabel("—")
        form.addRow("F10.7 flux:", self.f107_lbl)
        self.aurora_lbl = QLabel("—")
        form.addRow("Aurora (OVATION max):", self.aurora_lbl)
        self.forecast_lbl = QLabel("—")
        form.addRow("Kp forecast (3 d max):", self.forecast_lbl)
        self.wind_lbl = QLabel("—")
        form.addRow("Solar wind (RTSW):", self.wind_lbl)
        self.imf_lbl = QLabel("—")
        form.addRow("IMF Bz / Bt (GSM):", self.imf_lbl)
        self.proton_lbl = QLabel("—")
        form.addRow("GOES protons (≥10/50/100 MeV):", self.proton_lbl)
        self.dst_lbl = QLabel("—")
        form.addRow("Dst index:", self.dst_lbl)
        self.decl_lbl = QLabel("—")
        form.addRow("Magnetic declination (loc):", self.decl_lbl)
        self.ssn_lbl = QLabel("—")
        form.addRow("Sunspot number:", self.ssn_lbl)
        self.cme_lbl = QLabel("—")
        self.cme_lbl.setWordWrap(True)
        form.addRow("Latest CME:", self.cme_lbl)
        self.links_lbl = QLabel(
            '<a href="https://sdo.gsfc.nasa.gov/data/">SDO data</a> · '
            '<a href="https://www.swpc.noaa.gov/">NOAA SWPC</a>'
        )
        self.links_lbl.setOpenExternalLinks(True)
        form.addRow("Imagery links:", self.links_lbl)
        layout.addLayout(form)
        layout.addStretch(1)

    def refresh(self) -> None:
        kp = self.store.get_latest_observation("swpc", "swpc:kp")
        if kp:
            self.kp_value.setText(f"{kp.value:.1f}")
            self.kp_meta.setText(f"Planetary K-index · {fmt_ts(kp.ts)} · NOAA SWPC")
            self.status_lbl.setText("Geomagnetic activity: " + ("elevated" if kp.value >= 4 else "quiet"))
            series = self.store.get_recent_series("swpc", "swpc:kp", limit=120)
            if series:
                points = [(o.ts.timestamp(), o.value) for o in series]
                ys = [o.value for o in series]
                self.spark.set_points(points, min_value=0, max_value=max(9.0, max(ys) if ys else 9.0))
            else:
                self.spark.set_points([], min_value=0, max_value=9.0)
        else:
            self.kp_value.setText("—")
            self.kp_meta.setText("No Kp data yet")
            self.status_lbl.setText("—")
            self.spark.set_points([], min_value=0, max_value=9)

        path = self.store.latest_asset("sun_imagery")
        pixmap = QPixmap(path) if path else QPixmap()
        if not pixmap.isNull():
            self.image_lbl.setPixmap(pixmap.scaled(512, 260, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.image_lbl.setText("")
        else:
            self.image_lbl.clear()
            self.image_lbl.setText("No solar image yet")

        xray = self.store.get_latest_observation("swpc", "swpc:xray_flux")
        if xray:
            self.xray_lbl.setText(f"{xray.extra_json.get('class', '?')}-class · {xray.value:.2e} W/m² · {fmt_ts(xray.ts)}")
        else:
            self.xray_lbl.setText("—")
        f107 = self.store.get_latest_observation("swpc", "swpc:f107")
        if f107:
            self.f107_lbl.setText(f"{f107.value:.0f} sfu · {fmt_ts(f107.ts)}")
        else:
            self.f107_lbl.setText("—")
        aurora = self.store.get_latest_observation("aurora", "aurora:intensity_max")
        if aurora:
            txt = f"max {aurora.value:.0f} · {fmt_ts(aurora.ts)}"
            oval = self.store.get_latest_observation("aurora", "aurora:oval_equatorward_deg")
            if oval:
                txt += f" · oval edge {oval.value:.1f}°"
            self.aurora_lbl.setText(txt)
        else:
            self.aurora_lbl.setText("—")
        fc = self.store.get_recent_series("swpc", "swpc:kp_forecast", limit=24)
        if fc:
            self.forecast_lbl.setText(f"max Kp {max(o.value for o in fc):.1f} (next {len(fc) * 3} h)")
        else:
            self.forecast_lbl.setText("—")
        wind = self.store.get_latest_observation("swpc", "swpc:solarwind_speed")
        dens = self.store.get_latest_observation("swpc", "swpc:solarwind_density")
        if wind:
            text = f"{wind.value:.0f} km/s · {fmt_ts(wind.ts)}"
            if dens:
                text += f" · {dens.value:.1f} p/cc"
            sc = wind.extra_json.get("spacecraft")
            if sc:
                text += f" · {sc}"
            self.wind_lbl.setText(text)
        else:
            self.wind_lbl.setText("—")
        bz = self.store.get_latest_observation("swpc", "swpc:imf_bz_gsm")
        bt = self.store.get_latest_observation("swpc", "swpc:imf_bt")
        if bz:
            verdict = "southward (storm coupling)" if bz.value <= -5 else ("unsettled" if bz.value < 0 else "northward (quiet)")
            txt = f"{bz.value:.1f} nT · {verdict} · {fmt_ts(bz.ts)}"
            if bt:
                txt += f" · Bt {bt.value:.1f} nT"
            self.imf_lbl.setText(txt)
        else:
            self.imf_lbl.setText("—")
        proton = self.store.get_latest_observation("swpc", "swpc:proton_flux_gte10MeV")
        if proton:
            v = proton.value
            scale = "S5" if v >= 100000 else ("S4" if v >= 10000 else ("S3" if v >= 1000 else ("S2" if v >= 100 else ("S1" if v >= 10 else "below S1"))))
            p50 = self.store.get_latest_observation("swpc", "swpc:proton_flux_gte50MeV")
            p100 = self.store.get_latest_observation("swpc", "swpc:proton_flux_gte100MeV")
            extra = ""
            if p50:
                extra += f" · ≥50 {p50.value:.2f}"
            if p100:
                extra += f" · ≥100 {p100.value:.2f}"
            self.proton_lbl.setText(f"{v:.1f} pfu · {scale}{extra} · {fmt_ts(proton.ts)}")
        else:
            self.proton_lbl.setText("—")
        dst = self.store.get_latest_observation("swpc", "swpc:dst")
        if dst:
            v = dst.value
            verdict = "intense storm" if v <= -100 else ("moderate storm" if v <= -50 else "quiet")
            self.dst_lbl.setText(f"{v:.0f} nT · {verdict} · {fmt_ts(dst.ts)}")
        else:
            self.dst_lbl.setText("—")
        locations = [loc for loc in (self.store.get_setting("locations") or []) if isinstance(loc, dict)]
        legacy_loc = self.store.get_setting("location")
        if not locations and isinstance(legacy_loc, dict):
            locations = [legacy_loc]
        if locations:
            loc = locations[0]
            key = loc.get("key") or f"{loc.get('lat')},{loc.get('lon')}"
            decl = self.store.get_latest_observation("geomag", f"geomag:{key}:declination")
            if decl:
                self.decl_lbl.setText(
                    f"{decl.value:+.1f}° ({'E' if decl.value >= 0 else 'W'} of true north) · {loc.get('name', '')} · {fmt_ts(decl.ts)}"
                )
            else:
                self.decl_lbl.setText(f"no geomag sample yet for {loc.get('name', 'primary location')}")
        else:
            self.decl_lbl.setText("no location configured")
        ssn = self.store.get_latest_observation("swpc", "swpc:ssn_observed")
        ssn_p = self.store.get_latest_observation("swpc", "swpc:ssn_predicted")
        if ssn:
            txt = f"observed {ssn.value:.0f} · {fmt_ts(ssn.ts)}"
            if ssn_p:
                txt += f" · predicted {ssn_p.value:.0f}"
            self.ssn_lbl.setText(txt)
        else:
            self.ssn_lbl.setText("—")
        # CME arrival watch: latest DONKI CME + SIMULATED ballistic window
        # only when speed/direction/flare inputs are real measurements.
        try:
            from ssnow_core.sim import get_scenario
            from ssnow_core.sim.flare import flare_class_from_flux
            from ssnow_core.sources.donki import is_earth_directed

            cmes = self.store.query_events(categories=["cme"], limit=20)
            if cmes:
                c = cmes[0]  # newest first
                ex = c.extra_json or {}
                try:
                    speed = float(ex.get("speed")) if ex.get("speed") not in (None, "") else None
                except (TypeError, ValueError):
                    speed = None
                ctype = ex.get("type") or "?"
                directed = is_earth_directed(ex)
                base_txt = (
                    f"{fmt_ts(c.occurred_at)} · {speed:.0f} km/s · type {ctype} · "
                    f"{'Earth-directed candidate' if directed else 'not Earth-directed'}"
                    if speed is not None
                    else f"{fmt_ts(c.occurred_at)} · speed not measured · type {ctype} · "
                    f"{'Earth-directed candidate' if directed else 'not Earth-directed'}"
                )
                flare = flare_class_from_flux(float(xray.value)) if xray is not None else None
                if directed and speed is not None and flare is not None:
                    try:
                        now_dt = datetime.now(timezone.utc)
                        age_hours = 0.0
                        if c.occurred_at is not None:
                            age_hours = max(0.0, (now_dt - c.occurred_at).total_seconds() / 3600.0)
                        cls = get_scenario("flare_arrival")
                        res = cls().run({
                            "cme_speed_km_s": speed,
                            "distance_au": 1.0,
                            "flare_class": flare[0],
                            "flare_subclass": flare[1],
                            "elapsed_hours": min(age_hours, 240.0),
                        })
                        total = float(res.get("total_travel_hours") or 0.0)
                        if total > 0 and age_hours > total * 1.25:
                            base_txt += " · SIM window elapsed"
                        else:
                            lo, hi = res["arrival_window_low_hours"], res["arrival_window_high_hours"]
                            base_txt += f" · SIM arrival ~{lo:.0f}–{hi:.0f}h"
                    except Exception:
                        base_txt += " · SIM unavailable"
                elif speed is None:
                    base_txt += " · SIM needs measured speed"
                elif not directed:
                    base_txt += " · SIM needs Earth-directed event"
                else:
                    base_txt += " · SIM needs measured X-ray flux"
                self.cme_lbl.setText(base_txt)
            else:
                self.cme_lbl.setText("No CME in window —")
        except Exception:
            self.cme_lbl.setText("—")
