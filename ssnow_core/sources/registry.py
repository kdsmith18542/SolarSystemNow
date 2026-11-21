"""Adapter registry and factory."""

from __future__ import annotations

from .aurora import AuroraAdapter
from .base import Adapter, SourceSpec
from .cad import CadAdapter
from .cycle import SolarCycleAdapter
from .donki import CMEAdapter, FlareAdapter, GSTAdapter
from .dst import DstAdapter
from .eonet import EONETAdapter
from .fireball import FireballAdapter
from .geomag import GeomagAdapter
from .geomag_poles import GeomagPolesAdapter
from .lsr import LSRAdapter
from .moon import MoonAdapter
from .neows import NeoWsAdapter
from .nws import NWSAlertsAdapter
from .openmeteo import OpenMeteoAdapter
from .proton import ProtonAdapter
from .sentry import SentryAdapter
from .spc import SPCOutlookAdapter
from .sun import SunImageryAdapter
from .solarwind import MagAdapter, SolarWindAdapter
from .swpc import F107Adapter, KpAdapter, KpForecastAdapter, AlertsAdapter, XrayAdapter
from .usgs import USGSAdapter

SPECS: dict[str, SourceSpec] = {
    "usgs": SourceSpec(
        id="usgs",
        name="USGS Earthquakes",
        domain="earthquakes",
        attribution="U.S. Geological Survey (USGS)",
        license="USGS data",
        url="https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson",
        cadence_seconds=600,
    ),
    "eonet": SourceSpec(
        id="eonet",
        name="NASA EONET Natural Events",
        domain="natural-hazards",
        attribution="NASA Earth Observatory Natural Event Tracker (EONET)",
        license="NASA data",
        url="https://eonet.gsfc.nasa.gov/api/v3/events",
        cadence_seconds=1800,
    ),
    "openmeteo": SourceSpec(
        id="openmeteo",
        name="Open-Meteo Weather",
        domain="weather",
        attribution="Open-Meteo",
        license="Open-Meteo Terms of Service",
        url="https://api.open-meteo.com/v1/forecast",
        cadence_seconds=3600,
    ),
    "swpc_kp": SourceSpec(
        id="swpc_kp",
        name="NOAA SWPC Planetary K-index",
        domain="space-weather",
        attribution="NOAA Space Weather Prediction Center",
        license="NOAA data",
        url="https://services.swpc.noaa.gov/json/planetary_k_index_1m.json",
        cadence_seconds=300,
    ),
    "swpc_alerts": SourceSpec(
        id="swpc_alerts",
        name="NOAA SWPC Alerts",
        domain="space-weather-alerts",
        attribution="NOAA Space Weather Prediction Center",
        license="NOAA data",
        url="https://services.swpc.noaa.gov/products/alerts.json",
        cadence_seconds=600,
    ),
    "donki_cme": SourceSpec(
        id="donki_cme",
        name="NASA DONKI CME",
        domain="space-weather-cme",
        attribution="NASA DONKI / CCMC",
        license="NASA data",
        url="https://ccmc.gsfc.nasa.gov/DONKI-API/get/CME",
        cadence_seconds=21600,
    ),
    "donki_flare": SourceSpec(
        id="donki_flare",
        name="NASA DONKI Solar Flares",
        domain="space-weather-flare",
        attribution="NASA DONKI / CCMC",
        license="NASA data",
        url="https://ccmc.gsfc.nasa.gov/DONKI-API/get/FLR",
        cadence_seconds=43200,
    ),
    "swpc_kp_forecast": SourceSpec(
        id="swpc_kp_forecast",
        name="NOAA SWPC 3-day Kp Forecast",
        domain="space-weather",
        attribution="NOAA Space Weather Prediction Center",
        license="NOAA data",
        url="https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json",
        cadence_seconds=21600,
    ),
    "swpc_xray": SourceSpec(
        id="swpc_xray",
        name="NOAA SWPC GOES X-ray Flux",
        domain="space-weather-xray",
        attribution="NOAA Space Weather Prediction Center / GOES",
        license="NOAA data",
        url="https://services.swpc.noaa.gov/json/goes/primary/xrays-1-day.json",
        cadence_seconds=900,
    ),
    "swpc_f107": SourceSpec(
        id="swpc_f107",
        name="NOAA SWPC F10.7 Solar Flux",
        domain="space-weather-f107",
        attribution="NOAA Space Weather Prediction Center",
        license="NOAA data",
        url="https://services.swpc.noaa.gov/json/f107_cm_flux.json",
        cadence_seconds=21600,
    ),
    "swpc_wind": SourceSpec(
        id="swpc_wind",
        name="SWPC Real-Time Solar Wind (RTSW plasma)",
        domain="space-weather-wind",
        attribution="NOAA SWPC (SOLAR-1/ACE/DSCOVR RTSW)",
        license="NOAA data (US public domain)",
        url="https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json",
        cadence_seconds=300,
    ),
    "swpc_mag": SourceSpec(
        id="swpc_mag",
        name="SWPC Interplanetary Magnetic Field (Bz/Bt)",
        domain="space-weather-imf",
        attribution="NOAA SWPC (SOLAR-1/ACE RTSW magnetometer)",
        license="NOAA data (US public domain)",
        url="https://services.swpc.noaa.gov/json/rtsw/rtsw_mag_1m.json",
        cadence_seconds=300,
    ),
    "swpc_proton": SourceSpec(
        id="swpc_proton",
        name="GOES Integral Proton Flux (S-scale)",
        domain="space-weather-proton",
        attribution="NOAA SWPC / GOES",
        license="NOAA data (US public domain)",
        url="https://services.swpc.noaa.gov/json/goes/primary/integral-protons-1-day.json",
        cadence_seconds=900,
    ),
    "swpc_dst": SourceSpec(
        id="swpc_dst",
        name="Kyoto Dst Index (SWPC mirror)",
        domain="space-weather-dst",
        attribution="Kyoto WDC via NOAA SWPC",
        license="NOAA data (US public domain)",
        url="https://services.swpc.noaa.gov/products/kyoto-dst.json",
        cadence_seconds=3600,
    ),
    "jpl_fireball": SourceSpec(
        id="jpl_fireball",
        name="JPL CNEOS Fireballs & Bolides",
        domain="fireballs",
        attribution="NASA JPL CNEOS (US government sensors)",
        license="NASA data (US public domain)",
        url="https://ssd-api.jpl.nasa.gov/fireball.api",
        cadence_seconds=21600,
    ),
    "spc_outlook": SourceSpec(
        id="spc_outlook",
        name="NOAA SPC Convective Outlooks Day 1-3",
        domain="severe-outlook",
        attribution="NOAA Storm Prediction Center",
        license="NOAA data (US public domain)",
        url="https://www.spc.noaa.gov/products/outlook/",
        cadence_seconds=1800,
    ),
    "donki_gst": SourceSpec(
        id="donki_gst",
        name="NASA DONKI Geomagnetic Storms",
        domain="space-weather-gst",
        attribution="NASA DONKI / CCMC",
        license="NASA data",
        url="https://ccmc.gsfc.nasa.gov/DONKI-API/get/GST",
        cadence_seconds=21600,
    ),
    "neows": SourceSpec(
        id="neows",
        name="NASA NeoWs Close Approaches",
        domain="near-earth-objects",
        attribution="NASA JPL CNEOS / NeoWs",
        license="NASA data",
        url="https://api.nasa.gov/neo/rest/v1/feed",
        cadence_seconds=21600,
        requires_key=True,
    ),
    "nws_alerts": SourceSpec(
        id="nws_alerts",
        name="NWS Active Alerts (US + territories)",
        domain="weather-alerts",
        attribution="US National Weather Service",
        license="US public domain data",
        url="https://api.weather.gov/alerts/active",
        cadence_seconds=600,
    ),
    "aurora": SourceSpec(
        id="aurora",
        name="NOAA OVATION Aurora",
        domain="aurora",
        attribution="NOAA Space Weather Prediction Center (OVATION)",
        license="NOAA data",
        url="https://services.swpc.noaa.gov/json/ovation_aurora_latest.json",
        cadence_seconds=3600,
    ),
    "geomag": SourceSpec(
        id="geomag",
        name="WMM Magnetic Declination",
        domain="geomagnetism",
        attribution="NOAA NCEI World Magnetic Model",
        license="NOAA data",
        url="https://www.ngdc.noaa.gov/geomag-web/calculators/calculateDeclination",
        cadence_seconds=86400,
    ),
    "geomag_poles": SourceSpec(
        id="geomag_poles",
        name="NOAA Historical Magnetic Poles",
        domain="geomagnetism",
        attribution="NOAA NCEI World Magnetic Model / IGRF",
        license="NOAA data (US public domain)",
        url="https://www.ngdc.noaa.gov/geomag/data/poles/NP.xy",
        cadence_seconds=604800,
    ),
    "sun_imagery": SourceSpec(
        id="sun_imagery",
        name="NASA SDO Solar Imagery (171Å)",
        domain="sun-imagery",
        attribution="NASA SDO / AIA",
        license="NASA data",
        url="https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0171.jpg",
        cadence_seconds=3600,
    ),
    "sun_sdo193": SourceSpec(
        id="sun_sdo193",
        name="NASA SDO AIA 193Å (coronal holes)",
        domain="sun-imagery",
        attribution="NASA SDO / AIA",
        license="NASA data",
        url="https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0193.jpg",
        cadence_seconds=3600,
    ),
    "sun_sdo304": SourceSpec(
        id="sun_sdo304",
        name="NASA SDO AIA 304Å (chromosphere)",
        domain="sun-imagery",
        attribution="NASA SDO / AIA",
        license="NASA data",
        url="https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0304.jpg",
        cadence_seconds=3600,
    ),
    "sun_lasco_c2": SourceSpec(
        id="sun_lasco_c2",
        name="SOHO LASCO C2 Coronagraph",
        domain="sun-imagery",
        attribution="NASA/ESA SOHO LASCO (NRL realtime)",
        license="NASA/ESA data",
        url="https://soho.nascom.nasa.gov/data/realtime/c2/512/latest.jpg",
        cadence_seconds=3600,
    ),
    "sun_lasco_c3": SourceSpec(
        id="sun_lasco_c3",
        name="SOHO LASCO C3 Coronagraph",
        domain="sun-imagery",
        attribution="NASA/ESA SOHO LASCO (NRL realtime)",
        license="NASA/ESA data",
        url="https://soho.nascom.nasa.gov/data/realtime/c3/512/latest.jpg",
        cadence_seconds=3600,
    ),
    "sun_hmi": SourceSpec(
        id="sun_hmi",
        name="SDO HMI Magnetogram (color)",
        domain="sun-imagery",
        attribution="NASA SDO / HMI",
        license="NASA data",
        url="https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_HMIBC.jpg",
        cadence_seconds=3600,
    ),
    "sentry": SourceSpec(
        id="sentry",
        name="JPL CNEOS Sentry Impact Risk (top 40)",
        domain="near-earth-objects",
        attribution="NASA JPL CNEOS Sentry",
        license="NASA data (US public domain)",
        url="https://ssd-api.jpl.nasa.gov/sentry.api",
        cadence_seconds=86400,
    ),
    "swpc_cycle": SourceSpec(
        id="swpc_cycle",
        name="SWPC Solar Cycle Indices (observed + predicted)",
        domain="solar-cycle",
        attribution="NOAA SWPC",
        license="NOAA data (US public domain)",
        url="https://services.swpc.noaa.gov/json/solar-cycle/observed-solar-cycle-indices.json",
        cadence_seconds=86400,
    ),
    "iem_lsr": SourceSpec(
        id="iem_lsr",
        name="IEM Local Storm Reports (24h)",
        domain="storm-reports",
        attribution="Iowa State IEM / NWS (free for any lawful purpose)",
        license="IEM open data",
        url="https://mesonet.agron.iastate.edu/geojson/lsr.geojson",
        cadence_seconds=3600,
    ),
    "moon": SourceSpec(
        id="moon",
        name="Moon (Skyfield)",
        domain="moon",
        attribution="Computed with Skyfield / JPL ephemeris",
        license="Public domain (computed)",
        url="",
        cadence_seconds=3600,
    ),
    "jpl_cad": SourceSpec(
        id="jpl_cad",
        name="JPL SBDB Close Approaches (asteroids + comets)",
        domain="near-earth-objects",
        attribution="NASA JPL SSD/CNEOS CAD API",
        license="NASA data",
        url="https://ssd-api.jpl.nasa.gov/cad.api",
        cadence_seconds=21600,
    ),
}

ADAPTER_CLASSES: dict[str, type[Adapter]] = {
    "usgs": USGSAdapter,
    "eonet": EONETAdapter,
    "openmeteo": OpenMeteoAdapter,
    "swpc_kp": KpAdapter,
    "swpc_kp_forecast": KpForecastAdapter,
    "swpc_alerts": AlertsAdapter,
    "swpc_wind": SolarWindAdapter,
    "swpc_mag": MagAdapter,
    "swpc_proton": ProtonAdapter,
    "swpc_dst": DstAdapter,
    "jpl_fireball": FireballAdapter,
    "spc_outlook": SPCOutlookAdapter,
    "swpc_xray": XrayAdapter,
    "swpc_f107": F107Adapter,
    "donki_cme": CMEAdapter,
    "donki_flare": FlareAdapter,
    "donki_gst": GSTAdapter,
    "neows": NeoWsAdapter,
    "jpl_cad": CadAdapter,
    "nws_alerts": NWSAlertsAdapter,
    "aurora": AuroraAdapter,
    "geomag": GeomagAdapter,
    "geomag_poles": GeomagPolesAdapter,
    "sun_imagery": SunImageryAdapter,
    "sun_sdo193": SunImageryAdapter,
    "sun_sdo304": SunImageryAdapter,
    "sun_lasco_c2": SunImageryAdapter,
    "sun_lasco_c3": SunImageryAdapter,
    "sun_hmi": SunImageryAdapter,
    "sentry": SentryAdapter,
    "swpc_cycle": SolarCycleAdapter,
    "iem_lsr": LSRAdapter,
    "moon": MoonAdapter,
}


def all_specs() -> list[SourceSpec]:
    return list(SPECS.values())


def spec_for(source_id: str) -> SourceSpec | None:
    return SPECS.get(source_id)


def build_adapter(source_id: str) -> Adapter | None:
    cls = ADAPTER_CLASSES.get(source_id)
    spec = SPECS.get(source_id)
    if cls is None or spec is None:
        return None
    return cls(spec)
