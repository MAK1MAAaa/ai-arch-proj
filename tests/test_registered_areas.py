"""Synthetic modern register polygons preserve source structure, never make points."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from archsearch import registered_areas as areas
from archsearch.api import create_app
from archsearch.corpus import CORPUS_VERSION
from archsearch.domain import Site
from archsearch.supplement_data import SourceArtifact

URI = (
    "https://gis.environment.gov.au/gispubmap/rest/services/ogc_services/"
    "National_Heritage_List/FeatureServer/0/query?where=PLACE_ID%3D1&outFields=%2A"
    "&returnGeometry=true&outSR=4326&orderByFields=OBJECTID+ASC&f=json"
)
RINGS = [
    [[140, -30], [141, -30], [141, -29], [140, -30]],
    [[140.2, -29.8], [140.3, -29.8], [140.3, -29.7], [140.2, -29.8]],
]


def fixture(tmp_path: Path, value: dict[str, Any] | None = None) -> areas.AreaInput:
    rows = [{"OBJECTID": 1, "PLACE_ID": 1, "STATE": "SA", "FILE_": "fixture"},
            {"OBJECTID": 2, "PLACE_ID": 1, "STATE": "QLD", "FILE_": "fixture"}]
    raw = value if value is not None else {
        "geometryType": "esriGeometryPolygon", "spatialReference": {"wkid": 4326},
        "features": [{"attributes": row, "geometry": {"rings": RINGS}}
                     for row in rows],
    }
    payload = json.dumps(raw).encode()
    (tmp_path / "geometry.json").write_bytes(payload)
    return areas.AreaInput(
        site_id="auth:au-nhl:1", title="Synthetic interstate cultural register",
        place_id=1, artifact=SourceArtifact(filename="geometry.json", uri=URI,
                                          sha256=hashlib.sha256(payload).hexdigest()),
        source_rows=rows, feature_ids=[1, 2], ring_count=4, coordinate_records=16,
    )


def test_all_source_rings_and_interstate_features_remain_unconverted(tmp_path: Path) -> None:
    contract = fixture(tmp_path)
    compiled = areas.compile_source_areas([contract], tmp_path, "a" * 64)
    features = compiled["sites"][contract.site_id]
    assert len(features) == 2
    assert [row["provider_object_id"] for row in features] == [1, 2]
    assert [row["source_index"] for row in features] == [0, 1]
    assert all(row["rings"] == RINGS for row in features)
    assert all(row["geometry_type"] == "esriGeometryPolygon" for row in features)
    assert all(row["source"]["sha256"] == contract.artifact.sha256 for row in features)
    assert all("repr_point" not in row and "centroid" not in row for row in features)
    assert compiled["label"] == "现代遗产登记范围"
    assert "不是古代遗址轮廓" in compiled["note"]


@pytest.mark.parametrize("change", ["missing-feature", "reordered", "changed-attribute",
                                       "wrong-crs", "truncated", "wrong-geometry"])
def test_new_hash_cannot_hide_source_identity_or_completeness_errors(
    tmp_path: Path, change: str,
) -> None:
    fixture(tmp_path)
    value = json.loads((tmp_path / "geometry.json").read_bytes())
    if change == "missing-feature":
        value["features"].pop()
    elif change == "reordered":
        value["features"].reverse()
    elif change == "changed-attribute":
        value["features"][0]["attributes"]["STATE"] = "NT"
    elif change == "wrong-crs":
        value["spatialReference"]["wkid"] = 4283
    elif change == "truncated":
        value["exceededTransferLimit"] = True
    else:
        value["features"][0]["geometry"]["z"] = 1
    contract = fixture(tmp_path, value)
    with pytest.raises(areas.RegisteredAreasError):
        areas.compile_source_areas([contract], tmp_path, "a" * 64)


@pytest.mark.parametrize("point", [[True, -30], [140, float("nan")], [181, 0],
                                    [0, 91], [140, -30, 1], None])
def test_invalid_vertex_cannot_be_coerced_to_a_valid_point(point: Any) -> None:
    with pytest.raises(ValueError):
        areas.RegisteredArea.validate_rings([[point, [141, -30], [141, -29], point]])


def test_changed_bytes_and_wrong_source_query_are_rejected(tmp_path: Path) -> None:
    contract = fixture(tmp_path)
    (tmp_path / "geometry.json").write_bytes(b"{}")
    with pytest.raises(areas.RegisteredAreasError, match="bytes"):
        areas.compile_source_areas([contract], tmp_path, "a" * 64)
    contract = fixture(tmp_path)
    wrong = contract.artifact.model_copy(update={"uri": URI.replace("outSR=4326", "outSR=4283")})
    with pytest.raises(areas.RegisteredAreasError, match="query"):
        areas.compile_source_areas([contract.model_copy(update={"artifact": wrong})],
                                   tmp_path, "a" * 64)


def test_sidecar_failure_is_separate_from_a_site_with_no_area(tmp_path: Path) -> None:
    absent = areas.RegisteredAreasIndex(tmp_path).response("fixture", "v1")
    assert absent.ready and absent.features == [] and absent.reason is None
    (tmp_path / "australia_manifest.json").write_text("{}", encoding="utf8")
    missing = areas.RegisteredAreasIndex(tmp_path).response("fixture", "v1")
    assert not missing.ready and not missing.features
    assert missing.reason and "--rebuild" in missing.reason


def test_bundled_sidecar_preserves_exact_counts_and_returns_defensive_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = fixture(tmp_path)
    payload = areas._bytes(areas.compile_source_areas([record], tmp_path, "a" * 64))
    (tmp_path / areas.AREAS_FILE).write_bytes(payload)
    (tmp_path / "australia_manifest.json").write_text("{}", encoding="utf8")
    monkeypatch.setattr(areas, "AREAS_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(areas, "australia_inputs", lambda _: ([record], "a" * 64))
    index = areas.RegisteredAreasIndex(tmp_path)
    first = index.response(record.site_id, "v2")
    assert first.ready and first.version == areas.AREAS_VERSION and len(first.features) == 2
    first.features[0].rings[0].pop()
    assert len(index.response(record.site_id, "v2").features[0].rings[0]) == 4
    value = json.loads(payload)
    value["sites"][record.site_id].pop()
    incomplete = areas._bytes(value)
    (tmp_path / areas.AREAS_FILE).write_bytes(incomplete)
    monkeypatch.setattr(areas, "AREAS_SHA256", hashlib.sha256(incomplete).hexdigest())
    assert not areas.RegisteredAreasIndex(tmp_path).ready


def test_area_api_is_distinct_from_source_points_and_search(
    tmp_path: Path, sample_sites: list[Site],
) -> None:
    record = fixture(tmp_path).model_copy(update={"site_id": sample_sites[0].id})
    payload = areas.compile_source_areas([record], tmp_path, "a" * 64)
    index = areas.RegisteredAreasIndex(tmp_path)
    index.features = {key: [areas.RegisteredArea.model_validate(row) for row in rows]
                      for key, rows in payload["sites"].items()}
    index.version = areas.AREAS_VERSION
    with TestClient(create_app(home=tmp_path, sites=sample_sites, areas=index)) as client:
        response = client.get("/api/sites/3/areas")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["site_id"] == "3" and body["corpus_version"] == CORPUS_VERSION
        assert body["ready"] and len(body["features"]) == 2
        assert all(feature["rings"] == RINGS for feature in body["features"])
        assert client.get("/api/sites/1/areas").json()["features"] == []
        assert client.get("/api/sites/unknown/areas").status_code == 404
        assert client.get("/api/sites/3").json()["repr_point"] == [12, 35]
        status = client.get("/api/status").json()["registered_areas"]
        fields = ("sites", "features", "rings", "coordinate_records")
        assert {key: status[key] for key in fields} == {
            "sites": 1, "features": 2, "rings": 4, "coordinate_records": 16,
        }
        result = client.post("/api/search", json={"query": "harbor", "mode": "bm25"})
        assert result.status_code == 200


def test_unavailable_area_api_preserves_keyword_search_and_site_evidence(
    tmp_path: Path, sample_sites: list[Site],
) -> None:
    (tmp_path / "australia_manifest.json").write_text("{}", encoding="utf8")
    index = areas.RegisteredAreasIndex(tmp_path)
    with TestClient(create_app(home=tmp_path, sites=sample_sites, areas=index)) as client:
        body = client.get("/api/sites/3/areas").json()
        assert not body["ready"] and body["features"] == [] and "--rebuild" in body["reason"]
        assert not client.get("/api/status").json()["registered_areas"]["ready"]
        assert client.get("/api/sites/3").json() == sample_sites[0].model_dump(mode="json")
        result = client.post("/api/search", json={"query": "harbor", "mode": "bm25"})
        assert result.status_code == 200


def test_explicit_download_is_pinned_atomic_and_reuses_verified_local_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = fixture(tmp_path)
    raw = (tmp_path / "geometry.json").read_bytes()
    download = Mock(return_value=io.BytesIO(raw))
    monkeypatch.setattr(areas, "urlopen", download)
    cache = tmp_path / "cache"
    areas.download_sources([record], cache)
    assert (cache / "geometry.json").read_bytes() == raw
    areas.download_sources([record], cache)
    assert download.call_count == 1
    assert not list(cache.glob("*.part"))


@pytest.mark.parametrize("failure", ["hash", "size", "origin"])
def test_failed_explicit_download_never_publishes_an_unverified_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    record = fixture(tmp_path)
    raw = (tmp_path / "geometry.json").read_bytes()
    download = Mock(return_value=io.BytesIO(b"changed" if failure == "hash" else raw))
    monkeypatch.setattr(areas, "urlopen", download)
    if failure == "size":
        monkeypatch.setattr(areas, "MAX_SOURCE_BYTES", 1)
    if failure == "origin":
        record = record.model_copy(update={
            "artifact": record.artifact.model_copy(update={"uri": "https://example.org/other"}),
        })
    cache = tmp_path / "cache"
    with pytest.raises(areas.RegisteredAreasError):
        areas.download_sources([record], cache)
    assert not (cache / "geometry.json").exists() and not list(cache.glob("*.part"))
    assert download.call_count == (0 if failure == "origin" else 1)
