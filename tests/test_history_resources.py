"""Small offline geographic reference ships with its pinned source and license."""

import hashlib
import json

from archsearch.config import STATIC_DIR


def test_local_land_reference_matches_frozen_source_and_is_not_a_political_basemap() -> None:
    folder = STATIC_DIR / "data"
    source = json.loads((folder / "land-source.json").read_text("utf-8"))
    payload = (folder / "land.geojson").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == source["sha256"]
    assert source["license"] == "Public domain"
    assert source["commit"] in source["uri"]
    assert "No ancient coastline reconstruction" in source["processing"]
    data = json.loads(payload)
    assert data["type"] == "FeatureCollection" and data["features"]
    assert all(row["geometry"]["type"] in {"Polygon", "MultiPolygon"} for row in data["features"])
