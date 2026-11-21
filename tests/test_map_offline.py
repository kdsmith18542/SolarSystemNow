"""Desktop map must not depend on CDN-hosted MapLibre or tiles."""

from __future__ import annotations

from pathlib import Path


def test_desktop_map_uses_bundled_offline_assets():
    from ssnow_desktop.views import map as map_mod

    assert map_mod.MAPLIBRE_JS == "maplibre-gl.js"
    assert map_mod.MAPLIBRE_CSS == "maplibre-gl.css"
    assert "unpkg.com" not in map_mod.HTML_TEMPLATE
    assert "demotiles.maplibre.org" not in map_mod.HTML_TEMPLATE
    assert "Map requires internet" not in map_mod.HTML_TEMPLATE
    assert "Map assets are unavailable" in map_mod.HTML_TEMPLATE

    base = Path(map_mod.maplibre_dir())
    assert (base / map_mod.MAPLIBRE_JS).is_file()
    assert (base / map_mod.MAPLIBRE_CSS).is_file()

    style = map_mod.offline_style()
    land = style["sources"]["land"]["data"]
    assert land["type"] == "FeatureCollection"
    assert len(land["features"]) > 100
    assert style["sources"]["borders"]["type"] == "geojson"
    assert {"background", "land-fill", "land-outline", "borders"} <= {
        layer["id"] for layer in style["layers"]
    }
