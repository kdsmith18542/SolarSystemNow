"""Solar flare / CME arrival simulation.

Estimates CME travel time to a target (e.g. Earth) and a geomagnetic
storm proxy from CME speed and flare class. Based on published empirical
relations (Richardson & Cane 2010; NOAA SWPC G-scale). ORDER-OF-MAGNITUDE
ONLY. Labeled SIMULATION — not a forecast.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .base import Param, Scenario, ScenarioMeta, register

AU_KM = 149_597_870.7

# GOES soft X-ray peak flux (W/m^2) per class letter.
CLASS_BASE = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}


def flare_class_from_flux(flux_w_m2: float) -> tuple[str, float] | None:
    """Derive (letter, subclass) from a measured GOES flux; no assumptions."""
    for letter, base in (("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7), ("A", 1e-8)):
        if flux_w_m2 >= base:
            return letter, max(1.0, min(9.9, flux_w_m2 / base))
    return None


@register
class FlareArrivalScenario(Scenario):
    meta = ScenarioMeta(
        id="flare_arrival",
        title="Flare / CME Arrival",
        description=(
            "Estimate CME travel time to a target body and a geomagnetic "
            "storm proxy from CME speed and flare class."
        ),
        citation=(
            "Richardson & Cane (2010) Solar Physics 264:189-212. "
            "NOAA SWPC G-scale (geomagnetic storm levels)."
        ),
        params=[
            Param(
                id="cme_speed_km_s",
                label="CME speed",
                type="number",
                unit="km/s",
                default=800.0,
                min=100.0,
                max=3000.0,
            ),
            Param(
                id="distance_au",
                label="Target distance from Sun",
                type="number",
                unit="AU",
                default=1.0,
                min=0.1,
                max=5.0,
            ),
            Param(
                id="flare_class",
                label="Flare class",
                type="select",
                default="M",
                options=[
                    {"label": "A", "value": "A"},
                    {"label": "B", "value": "B"},
                    {"label": "C", "value": "C"},
                    {"label": "M", "value": "M"},
                    {"label": "X", "value": "X"},
                ],
            ),
            Param(
                id="flare_subclass",
                label="Flare subclass",
                type="number",
                unit="×10⁻⁵ W/m² (M/X scale)",
                default=5.0,
                min=1.0,
                max=9.0,
            ),
            Param(
                id="elapsed_hours",
                label="Elapsed since launch",
                type="number",
                unit="hours",
                default=0.0,
                min=0.0,
                max=240.0,
            ),
        ],
        output_labels={
            "arrival_hours": "Estimated arrival (hours from now)",
            "arrival_utc": "Estimated arrival (UTC)",
            "arrival_window_hours": "Uncertainty window (±hours)",
            "peak_flux_w_m2": "Peak soft X-ray flux (W/m²)",
            "storm_proxy": "Geomagnetic storm proxy",
            "notes": "Notes",
        },
    )

    def run(self, parameters: dict) -> dict:
        speed = float(parameters["cme_speed_km_s"])
        dist_au = float(parameters["distance_au"])
        flare_class = str(parameters["flare_class"])
        subclass = float(parameters["flare_subclass"])
        elapsed = max(0.0, float(parameters.get("elapsed_hours", 0.0) or 0.0))

        distance_km = dist_au * AU_KM
        total_hours = distance_km / (speed * 3600.0)
        hours = max(0.0, total_hours - elapsed)
        window_hours = total_hours * 0.25  # ±25% empirical spread
        arrival_utc = datetime.now(timezone.utc) + timedelta(hours=hours)

        # Peak flux (GOES).
        peak_flux = CLASS_BASE[flare_class] * subclass

        # Storm proxy: speed tier modified by flare magnitude.
        if speed < 500:
            base = "G0 (minor)"
        elif speed < 1000:
            base = "G1-G2 (minor-moderate)"
        elif speed < 1500:
            base = "G2-G3 (moderate-strong)"
        else:
            base = "G3-G4 (strong-severe)"
        if peak_flux >= 1e-4:
            base = base.replace("G0", "G1").replace("G1-G2", "G2-G3")

        return {
            "arrival_hours": hours,
            "arrival_utc": arrival_utc.isoformat(),
            "arrival_window_hours": window_hours,
            "arrival_window_low_hours": max(0.0, hours - window_hours),
            "arrival_window_high_hours": hours + window_hours,
            "total_travel_hours": total_hours,
            "elapsed_hours": elapsed,
            "peak_flux_w_m2": peak_flux,
            "flare_class": flare_class,
            "flare_subclass": subclass,
            "storm_proxy": base,
            "notes": (
                "Empirical travel-time estimate; actual arrival depends on "
                "solar-wind drag, CME deflection, and magnetic orientation. "
                "Storm proxy is indicative only."
            ),
        }
