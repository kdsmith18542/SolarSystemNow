"""Impact cratering simulation.

Based on published pi-scaling for simple impact craters:
Holsapple & Schmidt (1987), Melosh "Impact Cratering: A Geologic Process"
(1989), Collins et al. (2005) "Meteoritics & Planetary Science" 40:817-831.

ORDER-OF-MAGNITUDE ONLY. Labeled SIMULATION — not a forecast.
"""

from __future__ import annotations

import math

from .base import Param, Scenario, ScenarioMeta, register

MEGATON_TNT_J = 4.184e15
SIMPLE_TO_COMPLEX_EARTH_KM = 2.0  # craters above ~2 km on Earth are complex


@register
class ImpactCraterScenario(Scenario):
    meta = ScenarioMeta(
        id="impact_crater",
        title="Impact Crater",
        description=(
            "Estimate kinetic energy and crater size for an asteroid/comet impact. "
            "Order-of-magnitude pi-scaling; not a forecast."
        ),
        citation=(
            "Melosh, H.J. (1989) Impact Cratering: A Geologic Process. "
            "Collins et al. (2005) Meteoritics & Planetary Science 40:817-831."
        ),
        params=[
            Param(
                id="impactor_diameter_km",
                label="Impactor diameter",
                type="number",
                unit="km",
                default=1.0,
                min=0.001,
                max=100.0,
            ),
            Param(
                id="impactor_density_kg_m3",
                label="Impactor density",
                type="number",
                unit="kg/m³",
                default=3000.0,
                min=100.0,
                max=20000.0,
            ),
            Param(
                id="velocity_km_s",
                label="Impact velocity",
                type="number",
                unit="km/s",
                default=17.0,
                min=1.0,
                max=100.0,
            ),
            Param(
                id="angle_degrees",
                label="Impact angle (from horizontal)",
                type="number",
                unit="degrees",
                default=45.0,
                min=1.0,
                max=90.0,
            ),
            Param(
                id="target_density_kg_m3",
                label="Target density",
                type="number",
                unit="kg/m³",
                default=2700.0,
                min=100.0,
                max=10000.0,
            ),
            Param(
                id="gravity_m_s2",
                label="Surface gravity",
                type="number",
                unit="m/s²",
                default=9.81,
                min=0.1,
                max=50.0,
            ),
        ],
        output_labels={
            "energy_j": "Kinetic energy (J)",
            "energy_mt": "Energy (megatons TNT)",
            "transient_crater_km": "Transient crater diameter (km)",
            "final_crater_km": "Final crater diameter (km)",
            "crater_depth_km": "Crater depth (km)",
            "regime": "Crater regime",
        },
    )

    def run(self, parameters: dict) -> dict:
        d_km = float(parameters["impactor_diameter_km"])
        rho_i = float(parameters["impactor_density_kg_m3"])
        v_kms = float(parameters["velocity_km_s"])
        angle_deg = float(parameters["angle_degrees"])
        rho_t = float(parameters["target_density_kg_m3"])
        g = float(parameters["gravity_m_s2"])

        d_m = d_km * 1000.0
        v_ms = v_kms * 1000.0
        mass = (4.0 / 3.0) * math.pi * (d_m / 2.0) ** 3 * rho_i
        energy_j = 0.5 * mass * v_ms**2
        energy_mt = energy_j / MEGATON_TNT_J

        # Pi-scaling: transient crater diameter (m), dimensionally consistent.
        theta = math.radians(angle_deg)
        d_t_m = (
            1.16
            * (rho_i / rho_t) ** (1.0 / 3.0)
            * d_m**0.78
            * v_ms**0.44
            * g ** (-0.22)
            * math.sin(theta) ** (1.0 / 3.0)
        )
        d_t_km = d_t_m / 1000.0

        # Final crater: simple-crater enlargement; regime flag.
        regime = "simple" if d_t_km < SIMPLE_TO_COMPLEX_EARTH_KM else "complex"
        if regime == "simple":
            d_f_km = 1.25 * d_t_km
            depth_km = 0.20 * d_f_km
        else:
            d_f_km = 1.1 * d_t_km  # complex craters collapse; shallower relative depth
            depth_km = 0.10 * d_f_km

        return {
            "energy_j": energy_j,
            "energy_mt": energy_mt,
            "transient_crater_km": d_t_km,
            "final_crater_km": d_f_km,
            "crater_depth_km": depth_km,
            "regime": regime,
            "impactor_mass_kg": mass,
        }
