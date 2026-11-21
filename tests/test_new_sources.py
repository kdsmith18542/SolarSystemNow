"""Tests for gap-check adapters: X-ray, F10.7, Kp forecast, GST, NeoWs, NWS, aurora, geomag, marine/AQ/vortex."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from ssnow_core.sources.aurora import AuroraAdapter
from ssnow_core.sources.cad import CadAdapter
from ssnow_core.sources.cycle import SolarCycleAdapter
from ssnow_core.sources.donki import GSTAdapter
from ssnow_core.sources.dst import DstAdapter
from ssnow_core.sources.fireball import FireballAdapter
from ssnow_core.sources.geomag import GeomagAdapter
from ssnow_core.sources.lsr import LSRAdapter
from ssnow_core.sources.neows import NeoWsAdapter
from ssnow_core.sources.nws import NWSAlertsAdapter
from ssnow_core.sources.openmeteo import OpenMeteoAdapter
from ssnow_core.sources.proton import ProtonAdapter
from ssnow_core.sources.registry import SPECS
from ssnow_core.sources.sentry import SentryAdapter
from ssnow_core.sources.solarwind import MagAdapter, SolarWindAdapter
from ssnow_core.sources.spc import SPCOutlookAdapter
from ssnow_core.sources.swpc import F107Adapter, KpForecastAdapter, XrayAdapter
from ssnow_core.sources.tides import TidesAdapter
from conftest import load_fixture


def _now() -> datetime:
    return datetime(2026, 11, 20, 21, 0, 0, tzinfo=timezone.utc)


def _client(content: bytes, content_type: str = "application/json") -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request, headers={"content-type": content_type})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_xray_downsamples_to_5min(tmp_store):
    adapter = XrayAdapter(SPECS["swpc_xray"])
    report = adapter.ingest(tmp_store, _client(load_fixture("swpc_xray.json")), _now())
    assert report.ok
    series = tmp_store.get_series("swpc", "swpc:xray_flux")
    # 22:20 and 22:21 share a 5-min bucket; only the 0.1-0.8nm band is kept.
    assert len(series) == 2
    assert series[0].extra_json["class"] == "B"
    assert all(o.unit == "W/m^2" for o in series)


def test_kp_forecast_keeps_predicted_only(tmp_store):
    adapter = KpForecastAdapter(SPECS["swpc_kp_forecast"])
    report = adapter.ingest(tmp_store, _client(load_fixture("swpc_kp_forecast.json")), _now())
    assert report.ok
    series = tmp_store.get_series("swpc", "swpc:kp_forecast")
    assert len(series) == 2
    assert all(o.unit == "Kp" for o in series)
    assert tmp_store.get_series("swpc", "swpc:kp") == []


def test_f107_ingest(tmp_store):
    adapter = F107Adapter(SPECS["swpc_f107"])
    report = adapter.ingest(tmp_store, _client(load_fixture("swpc_f107.json")), _now())
    assert report.ok
    series = tmp_store.get_series("swpc", "swpc:f107")
    assert len(series) == 3
    assert series[-1].value == 103.0
    assert series[-1].unit == "sfu"


def test_gst_ingest(tmp_store):
    adapter = GSTAdapter(SPECS["donki_gst"])
    report = adapter.ingest(tmp_store, _client(load_fixture("donki_gst.json")), _now())
    assert report.ok
    assert len(report.events) == 1
    event = report.events[0]
    assert event.category == "geomagnetic_storm"
    assert event.magnitude == 8.0
    assert event.magnitude_unit == "Kp"


def test_neows_ingest(tmp_store):
    adapter = NeoWsAdapter(SPECS["neows"])
    report = adapter.ingest(tmp_store, _client(load_fixture("neows.json")), _now())
    assert report.ok
    assert len(report.events) == 1
    event = report.events[0]
    assert event.category == "neo"
    assert event.magnitude == 23.0
    assert event.magnitude_unit == "H"
    assert event.extra_json["miss_lunar"] == "23.3555544762"
    assert event.latitude is None


def test_nws_ingest_with_centroid(tmp_store):
    adapter = NWSAlertsAdapter(SPECS["nws_alerts"])
    report = adapter.ingest(tmp_store, _client(load_fixture("nws_alerts.json")), _now())
    assert report.ok
    assert len(report.events) == 2
    flood = [e for e in report.events if e.extra_json.get("area") == "Yuma, AZ"][0]
    assert flood.category == "weather_alert"
    assert flood.latitude is not None and flood.longitude is not None
    assert abs(flood.latitude - 32.75) < 0.2
    assert abs(flood.longitude - (-113.9)) < 0.3
    advisory = [e for e in report.events if "Wind Advisory" in e.title][0]
    assert advisory.latitude is None


def test_aurora_summary(tmp_store):
    adapter = AuroraAdapter(SPECS["aurora"])
    report = adapter.ingest(tmp_store, _client(load_fixture("aurora.json")), _now())
    assert report.ok
    max_obs = tmp_store.get_series("aurora", "aurora:intensity_max")
    assert len(max_obs) == 1
    assert max_obs[0].value == 12.0
    oval = tmp_store.get_series("aurora", "aurora:oval_equatorward_deg")
    assert oval[0].value == 60.0


def test_geomag_ingest(tmp_store):
    tmp_store.set_setting("locations", [{"name": "London", "lat": 51.5, "lon": -0.12, "key": "51.5,-0.12"}])
    adapter = GeomagAdapter(SPECS["geomag"])
    report = adapter.ingest(tmp_store, _client(load_fixture("geomag.json")), _now())
    assert report.ok
    series = tmp_store.get_series("geomag", "geomag:51.5,-0.12:declination")
    assert len(series) == 1
    assert abs(series[0].value - 1.23079) < 1e-6


def test_openmeteo_marine_aq_vortex_parse(tmp_store):
    adapter = OpenMeteoAdapter(SPECS["openmeteo"])
    _, mobs = adapter.parse_marine(load_fixture("openmeteo_marine.json"), "k", _now())
    assert [o.series for o in mobs] == [
        "marine:k:wave_height",
        "marine:k:sea_surface_temperature",
        "marine:k:ocean_current_velocity",
    ] * 2 + ["marine:k:wave_height", "marine:k:sea_surface_temperature"]
    _, aobs = adapter.parse_air_quality(load_fixture("openmeteo_aq.json"), "k", _now())
    assert len(aobs) == 6
    assert aobs[0].series == "air:k:us_aqi"
    _, vobs = adapter.parse_vortex(load_fixture("openmeteo_vortex.json"), "vortex:60N:0E", _now())
    assert len(vobs) == 3
    assert vobs[0].series == "strato:vortex:60N:0E:windspeed_10hPa"


def test_solarwind_rtsw_json_active_only(tmp_store):
    adapter = SolarWindAdapter(SPECS["swpc_wind"])
    report = adapter.ingest(tmp_store, _client(load_fixture("rtsw_wind.json")), _now())
    assert report.ok
    speed = tmp_store.get_series("swpc", "swpc:solarwind_speed")
    density = tmp_store.get_series("swpc", "swpc:solarwind_density")
    temp = tmp_store.get_series("swpc", "swpc:solarwind_temp")
    # 21:00 + 21:01 share a 5-min bucket (ACE inactive row ignored) -> 2 buckets.
    assert len(speed) == 2
    assert len(density) == 2
    assert len(temp) == 2
    assert speed[0].value == 450.0
    assert speed[0].unit == "km/s"
    assert speed[0].extra_json["spacecraft"] == "SOLAR1"
    assert density[0].unit == "p/cc"


def test_mag_bz_bt_active_only(tmp_store):
    adapter = MagAdapter(SPECS["swpc_mag"])
    report = adapter.ingest(tmp_store, _client(load_fixture("rtsw_mag.json")), _now())
    assert report.ok
    bz = tmp_store.get_series("swpc", "swpc:imf_bz_gsm")
    bt = tmp_store.get_series("swpc", "swpc:imf_bt")
    # 21:00 + 21:01 share bucket (incl. quoted-string row), ACE ignored -> 2 buckets.
    assert len(bz) == 2
    assert len(bt) == 2
    assert bz[0].value == -5.6
    assert bz[0].unit == "nT"
    assert bz[0].extra_json["spacecraft"] == "SOLAR1"


def test_proton_flux_channels(tmp_store):
    adapter = ProtonAdapter(SPECS["swpc_proton"])
    report = adapter.ingest(tmp_store, _client(load_fixture("goes_protons.json")), _now())
    assert report.ok
    gte10 = tmp_store.get_series("swpc", "swpc:proton_flux_gte10MeV")
    gte100 = tmp_store.get_series("swpc", "swpc:proton_flux_gte100MeV")
    # 21:00 + 21:01 share bucket -> 2 points for >=10 MeV (S1 threshold 10 pfu).
    assert len(gte10) == 2
    assert gte10[0].value == 12.5
    assert gte10[0].unit == "pfu"
    assert len(gte100) == 1


def test_dst_ingest(tmp_store):
    adapter = DstAdapter(SPECS["swpc_dst"])
    report = adapter.ingest(tmp_store, _client(load_fixture("kyoto_dst.json")), _now())
    assert report.ok
    series = tmp_store.get_series("swpc", "swpc:dst")
    assert len(series) == 3
    assert series[0].value == -52.0
    assert series[0].unit == "nT"


def test_fireball_with_and_without_location(tmp_store):
    adapter = FireballAdapter(SPECS["jpl_fireball"])
    report = adapter.ingest(tmp_store, _client(load_fixture("fireball.json")), _now())
    assert report.ok
    assert len(report.events) == 2
    located = [e for e in report.events if e.latitude is not None][0]
    assert located.category == "fireball"
    assert located.latitude == pytest.approx(-41.8)
    assert located.longitude == pytest.approx(-173.1)
    assert located.magnitude == pytest.approx(0.18)
    assert located.magnitude_unit == "kt"
    missing = [e for e in report.events if e.latitude is None][0]
    assert missing.magnitude == pytest.approx(0.25)


def test_spc_outlook_polygons(tmp_store):
    adapter = SPCOutlookAdapter(SPECS["spc_outlook"])
    evs, _ = adapter.parse(load_fixture("spc_day1_cat.geojson"), "application/geo+json", _now())
    assert len(evs) == 2
    enh = [e for e in evs if e.extra_json["label"] == "ENH"][0]
    assert enh.category == "severe_outlook"
    assert enh.magnitude == 5.0
    assert enh.magnitude_unit == "SPC"
    assert enh.latitude is not None and enh.longitude is not None
    assert enh.extra_json["geometry"]["type"] == "MultiPolygon"


def test_tides_ingest(tmp_store):
    tmp_store.set_setting("tide_stations", [{"id": "8454000", "name": "Providence"}])
    adapter = TidesAdapter(SPECS["tides"])
    report = adapter.ingest(tmp_store, _client(load_fixture("tides.json")), _now())
    assert report.ok
    series = tmp_store.get_series("tides", "tides:8454000:height")
    assert len(series) == 4
    assert series[1].value == 1.724
    assert series[1].unit == "m"
    assert series[1].extra_json["type"] == "H"


def test_cad_ingest_asteroids_and_comets(tmp_store):
    adapter = CadAdapter(SPECS["jpl_cad"])
    report = adapter.ingest(tmp_store, _client(load_fixture("jpl_cad.json")), _now())
    assert report.ok
    assert len(report.events) == 3
    by_des = {e.extra_json["des"]: e for e in report.events}
    # Asteroid: tiny, very close, not hazardous
    tiny = by_des["2026 TP128"]
    assert tiny.category == "neo"
    assert tiny.extra_json["is_comet"] is False
    assert tiny.extra_json["dist_lunar"] < 0.1
    # Apophis: PHA candidate (H<=22, within 0.05 au), diameter from feed
    apophis = by_des["99942"]
    assert apophis.extra_json["is_comet"] is False
    assert apophis.extra_json["hazardous_candidate"] is True
    assert apophis.extra_json["diameter_km"] == 0.34
    # Comet: slash designation detected
    halley = by_des["1P"]
    assert halley.extra_json["is_comet"] is True
    assert halley.extra_json["kind"] == "comet"
    assert halley.magnitude == 15.0


def test_sentry_keeps_top_by_palermo(tmp_store):
    adapter = SentryAdapter(SPECS["sentry"])
    report = adapter.ingest(tmp_store, _client(load_fixture("sentry.json")), _now())
    assert report.ok
    assert len(report.events) == 3
    top = report.events[0]
    assert top.category == "neo"
    assert top.extra_json["kind"] == "sentry"
    assert top.extra_json["des"] == "2022 XY"
    assert top.magnitude == pytest.approx(-2.10)
    assert top.magnitude_unit == "PS"
    assert top.latitude is None


def test_solar_cycle_observed_and_predicted(tmp_store):
    obs = load_fixture("solar_cycle_obs.json")
    pred = load_fixture("solar_cycle_pred.json")

    def handler(request: httpx.Request) -> httpx.Response:
        content = pred if "predicted" in str(request.url) else obs
        return httpx.Response(200, content=content, request=request, headers={"content-type": "application/json"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = SolarCycleAdapter(SPECS["swpc_cycle"])
    report = adapter.ingest(tmp_store, client, _now())
    assert report.ok
    ssn = tmp_store.get_series("swpc", "swpc:ssn_observed")
    f107 = tmp_store.get_series("swpc", "swpc:f107_observed")
    psn = tmp_store.get_series("swpc", "swpc:ssn_predicted")
    pf = tmp_store.get_series("swpc", "swpc:f107_predicted")
    assert len(ssn) == 2 and ssn[0].value == 140.2
    # -1.0 sentinel (F10.7 Oct) is dropped; smoothed values not stored.
    assert len(f107) == 1 and f107[0].value == 168.3
    assert len(psn) == 1 and psn[0].value == 130.5
    assert len(pf) == 1 and pf[0].value == 160.2


def test_lsr_reports_as_storm_events(tmp_store):
    adapter = LSRAdapter(SPECS["iem_lsr"])
    report = adapter.ingest(tmp_store, _client(load_fixture("iem_lsr.geojson"), "application/geo+json"), _now())
    assert report.ok
    assert len(report.events) == 2
    hail = [e for e in report.events if e.extra_json["lsr_type"] == "H"][0]
    assert hail.category == "storm"
    assert hail.latitude == pytest.approx(41.6)
    assert hail.longitude == pytest.approx(-93.6)
    assert hail.magnitude == pytest.approx(1.75)
    assert hail.magnitude_unit == "IN"
    assert "Des Moines" in hail.title
    tornado = [e for e in report.events if e.extra_json["lsr_type"] == "T"][0]
    assert tornado.category == "storm"


def test_sun_imagery_channels_ingest(tmp_store):
    from ssnow_core.sources.sun import SunImageryAdapter

    jpeg = b"\xff\xd8\xff" + b"\x00" * 100

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=jpeg, request=request, headers={"content-type": "image/jpeg"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    for spec_id in ("sun_imagery", "sun_sdo193", "sun_sdo304", "sun_hmi", "sun_lasco_c2", "sun_lasco_c3"):
        adapter = SunImageryAdapter(SPECS[spec_id])
        report = adapter.ingest(tmp_store, client, _now())
        assert report.ok
        assert tmp_store.latest_asset(spec_id) is not None


def test_event_ids_stable_and_unique():
    """IDs must survive refetches unchanged (notifications, AI labels, collab refs)."""
    from ssnow_core.sources.spc import SPCOutlookAdapter
    from ssnow_core.sources.fireball import FireballAdapter
    from ssnow_core.sources.lsr import LSRAdapter

    spc = SPCOutlookAdapter(SPECS["spc_outlook"])
    a1, _ = spc.parse(load_fixture("spc_day1_cat.geojson"), "application/geo+json", _now())
    a2, _ = spc.parse(load_fixture("spc_day1_cat.geojson"), "application/geo+json", _now())
    assert [e.id for e in a1] == [e.id for e in a2]
    assert len({e.id for e in a1}) == len(a1) > 0
    assert all(e.id.startswith("spc:day1:cat:") for e in a1)

    fb = FireballAdapter(SPECS["jpl_fireball"])
    f1, _ = fb.parse(load_fixture("fireball.json"), "application/json", _now())
    f2, _ = fb.parse(load_fixture("fireball.json"), "application/json", _now())
    assert [e.id for e in f1] == [e.id for e in f2]
    assert len({e.id for e in f1}) == len(f1) == 2

    lsr = LSRAdapter(SPECS["iem_lsr"])
    l1, _ = lsr.parse(load_fixture("iem_lsr.geojson"), "application/geo+json", _now())
    assert len({e.id for e in l1}) == len(l1) == 2
