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
        kp = self.store.latest_observations("swpc", "swpc:kp")
        if kp:
            obs = kp[0]
            self.kp_value.setText(f"{obs.value:.1f}")
            self.kp_meta.setText(f"Planetary K-index · {fmt_ts(obs.ts)} · NOAA SWPC")
            self.status_lbl.setText("Geomagnetic activity: " + ("elevated" if obs.value >= 4 else "quiet"))
            points = [(obs.ts.timestamp(), obs.value)]
            # recent series
            series = self.store.get_series("swpc", "swpc:kp", limit=120)
            if series:
                points = [(o.ts.timestamp(), o.value) for o in series]
                ys = [o.value for o in series]
                self.spark.set_points(points, min_value=0, max_value=max(9.0, max(ys) if ys else 9.0))
            else:
                self.spark.set_points(points, min_value=0, max_value=9.0)
        else:
            self.spark.set_points([(0, 0), (1, 0)], min_value=0, max_value=9)

        path = self.store.latest_asset("sun_imagery")
        if path:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.image_lbl.setPixmap(pixmap.scaled(512, 260, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.image_lbl.setText("")

        xray = self.store.get_series("swpc", "swpc:xray_flux", limit=1)
        if xray:
            o = xray[-1]
            self.xray_lbl.setText(f"{o.extra_json.get('class', '?')}-class · {o.value:.2e} W/m² · {fmt_ts(o.ts)}")
        else:
            self.xray_lbl.setText("—")
        f107 = self.store.get_series("swpc", "swpc:f107", limit=1)
        if f107:
            o = f107[-1]
            self.f107_lbl.setText(f"{o.value:.0f} sfu · {fmt_ts(o.ts)}")
        else:
            self.f107_lbl.setText("—")
        aurora = self.store.get_series("aurora", "aurora:intensity_max", limit=1)
        if aurora:
            o = aurora[-1]
            txt = f"max {o.value:.0f} · {fmt_ts(o.ts)}"
            oval = self.store.get_series("aurora", "aurora:oval_equatorward_deg", limit=1)
            if oval:
                txt += f" · oval edge {oval[-1].value:.1f}°"
            self.aurora_lbl.setText(txt)
        else:
            self.aurora_lbl.setText("—")
        fc = self.store.get_series("swpc", "swpc:kp_forecast", limit=24)
        if fc:
            self.forecast_lbl.setText(f"max Kp {max(o.value for o in fc):.1f} (next {len(fc) * 3} h)")
        else:
            self.forecast_lbl.setText("—")
        wind = self.store.get_series("swpc", "swpc:solarwind_speed", limit=1)
        dens = self.store.get_series("swpc", "swpc:solarwind_density", limit=1)
        if wind:
            o = wind[-1]
            text = f"{o.value:.0f} km/s · {fmt_ts(o.ts)}"
            if dens:
                text += f" · {dens[-1].value:.1f} p/cc"
            sc = o.extra_json.get("spacecraft")
            if sc:
                text += f" · {sc}"
            self.wind_lbl.setText(text)
        else:
            self.wind_lbl.setText("—")
        bz = self.store.get_series("swpc", "swpc:imf_bz_gsm", limit=1)
        bt = self.store.get_series("swpc", "swpc:imf_bt", limit=1)
        if bz:
            o = bz[-1]
            verdict = "southward (storm coupling)" if o.value <= -5 else ("unsettled" if o.value < 0 else "northward (quiet)")
            txt = f"{o.value:.1f} nT · {verdict} · {fmt_ts(o.ts)}"
            if bt:
                txt += f" · Bt {bt[-1].value:.1f} nT"
            self.imf_lbl.setText(txt)
        else:
            self.imf_lbl.setText("—")
        proton = self.store.get_series("swpc", "swpc:proton_flux_gte10MeV", limit=1)
        if proton:
            o = proton[-1]
            v = o.value
            scale = "S4" if v >= 10000 else ("S3" if v >= 1000 else ("S2" if v >= 100 else ("S1" if v >= 10 else "below S1")))
            p50 = self.store.get_series("swpc", "swpc:proton_flux_gte50MeV", limit=1)
            p100 = self.store.get_series("swpc", "swpc:proton_flux_gte100MeV", limit=1)
            extra = ""
            if p50:
                extra += f" · ≥50 {p50[-1].value:.2f}"
            if p100:
                extra += f" · ≥100 {p100[-1].value:.2f}"
            self.proton_lbl.setText(f"{v:.1f} pfu · {scale}{extra} · {fmt_ts(o.ts)}")
        else:
            self.proton_lbl.setText("—")
        dst = self.store.get_series("swpc", "swpc:dst", limit=1)
        if dst:
            o = dst[-1]
            v = o.value
            verdict = "intense storm" if v <= -100 else ("moderate storm" if v <= -50 else "quiet")
            self.dst_lbl.setText(f"{v:.0f} nT · {verdict} · {fmt_ts(o.ts)}")
        else:
            self.dst_lbl.setText("—")
        locations = self.store.get_setting("locations") or []
        if locations:
            loc = locations[0]
            key = loc.get("key") or f"{loc['lat']},{loc['lon']}"
            decl = self.store.get_series("geomag", f"geomag:{key}:declination", limit=1)
            if decl:
                d = decl[-1]
                self.decl_lbl.setText(
                    f"{d.value:+.1f}° ({'E' if d.value >= 0 else 'W'} of true north) · {loc.get('name', '')} · {fmt_ts(d.ts)}"
                )
            else:
                self.decl_lbl.setText(f"no geomag sample yet for {loc.get('name', 'primary location')}")
        else:
            self.decl_lbl.setText("no location configured")
        ssn = self.store.get_series("swpc", "swpc:ssn_observed", limit=1)
        ssn_p = self.store.get_series("swpc", "swpc:ssn_predicted", limit=1)
        if ssn:
            o = ssn[-1]
            txt = f"observed {o.value:.0f} · {fmt_ts(o.ts)}"
            if ssn_p:
                txt += f" · predicted {ssn_p[-1].value:.0f}"
            self.ssn_lbl.setText(txt)
        else:
            self.ssn_lbl.setText("—")
        # CME arrival watch: latest DONKI CME + SIMULATED ballistic window
        # (flare_arrival scenario, constant-speed assumption — model, not observation).
        try:
            cmes = self.store.query_events(categories=["cme"], limit=5)
            if cmes:
                def _score(e):
                    exx = e.extra_json or {}
                    try:
                        sp = float(exx.get("speed") or 0)
                    except (TypeError, ValueError):
                        sp = 0.0
                    directed = exx.get("type") in ("S", "C") or (exx.get("half_angle") or 0) >= 60
                    return (directed, sp)

                c = max(cmes, key=_score)
                ex = c.extra_json or {}
                speed = float(ex.get("speed") or 500.0)
                ctype = ex.get("type", "?")
                directed = "Earth-directed candidate" if (ctype in ("S", "C") or (ex.get("half_angle") or 0) >= 60) else "limb/backside likely"
                base_txt = (
                    f"{fmt_ts(c.occurred_at)} · {speed:.0f} km/s · type {ctype} · {directed}"
                    if ex.get("speed") else f"{fmt_ts(c.occurred_at)} · {directed}"
                )
                try:
                    from ssnow_core.sim import get_scenario

                    cls = get_scenario("flare_arrival")
                    letter = "C"
                    xray_s = self.store.get_series("swpc", "swpc:xray_flux", limit=1)
                    if xray_s:
                        letter = str(xray_s[-1].extra_json.get("class", "C"))[:1].upper()
                        if letter not in ("A", "B", "C", "M", "X"):
                            letter = "C"
                    res = cls().run({"cme_speed_km_s": speed, "distance_au": 1.0, "flare_class": letter, "flare_subclass": 5.0})
                    lo, hi = res["arrival_window_low_hours"], res["arrival_window_high_hours"]
                    base_txt += f" · SIM arrival ~{lo:.0f}–{hi:.0f}h"
                except Exception:
                    pass
                self.cme_lbl.setText(base_txt)
            else:
                self.cme_lbl.setText("No CME in window —")
        except Exception:
            self.cme_lbl.setText("—")
