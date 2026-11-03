"""Pinned source location sequences, metadata alignment and independent integrity contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from archsearch import spatial_data as spatial
from archsearch.corpus import load_corpus


def record(identifier: str = "123") -> dict[str, Any]:
    points = [[179, 10], [-179, 11], [179, 10]]
    return {
        "id_no": identifier,
        "category": "Cultural",
        "coordinates": {
            "type": "Feature", "geometry": {"type": "MultiPoint", "coordinates": points},
        },
        "components_count": 3,
        "components_list": json.dumps([
            {"name": name, "ref": ref, "longitude": point[0], "latitude": point[1]}
            for point, name, ref in zip(
                points, ["Eastern location", "", "Same coordinate, different record"],
                ["123-001", "123-001", "123-003"], strict=True,
            )
        ]),
    }


def empty_record(identifier: str = "456") -> dict[str, Any]:
    row = record(identifier)
    row.update(coordinates=None, components_count=0, components_list="[]")
    return row


@pytest.fixture
def bundled_copy(tmp_path: Path) -> Path:
    for filename in (spatial.LOCATIONS_FILENAME, spatial.MANIFEST_FILENAME):
        shutil.copyfile(spatial.DATA_DIR / filename, tmp_path / filename)
    return tmp_path


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8")


def test_normalization_retains_dateline_order_repeated_positions_and_nonunique_refs() -> None:
    values = spatial.normalize_locations([record()], {"123": "wd:Q123"})
    row = values["wd:Q123"]
    assert row["authority_id"] == "123" and row["geometry_type"] == "MultiPoint"
    assert [point["coordinate"] for point in row["points"]] == [
        [179, 10], [-179, 11], [179, 10],
    ]
    assert [point["source_index"] for point in row["points"]] == [0, 1, 2]
    assert [point["ref"] for point in row["points"]] == ["123-001", "123-001", "123-003"]
    assert row["points"][1]["name"] == ""


def test_zero_and_pole_coordinates_survive_without_clipping_or_placeholder_fabrication() -> None:
    row = record()
    row["coordinates"]["geometry"] = {"type": "Point", "coordinates": [0, -90]}
    row["components_count"] = 1
    row["components_list"] = json.dumps([
        {"longitude": 0, "latitude": -90, "name": "Explicit pole", "ref": "123-001"},
    ])
    normalized = spatial.normalize_locations([row], {"123": "whc:123"})
    assert normalized["whc:123"]["points"][0]["coordinate"] == [0, -90]


def test_absent_geometry_remains_empty_and_natural_properties_are_not_imported() -> None:
    natural = record("789")
    natural["category"] = "Natural"
    normalized = spatial.normalize_locations(
        [record(), empty_record(), natural], {"123": "wd:Q123", "456": "whc:456"},
    )
    assert set(normalized) == {"wd:Q123", "whc:456"}
    assert normalized["whc:456"] == {
        "authority_id": "456", "geometry_type": None, "points": [],
    }


@pytest.mark.parametrize("mode", ["name_type", "ref_type", "count", "reverse", "missing"])
def test_metadata_must_match_each_geometry_position_without_inferred_alignment(mode: str) -> None:
    row = record()
    components = json.loads(row["components_list"])
    if mode == "name_type":
        components[0]["name"] = None
    elif mode == "ref_type":
        components[0]["ref"] = 123
    elif mode == "count":
        row["components_count"] = 99
    elif mode == "reverse":
        components[0], components[1] = components[1], components[0]
    else:
        components.pop()
    row["components_list"] = json.dumps(components)
    with pytest.raises(spatial.SpatialDataError):
        spatial.normalize_locations([row], {"123": "whc:123"})


@pytest.mark.parametrize(
    "position", [[181, 10], [10, -91], [True, 10], ["179", 10], [float("nan"), 10]],
)
def test_invalid_wgs84_points_are_rejected_instead_of_coerced_or_dropped(
    position: list[Any],
) -> None:
    row = record()
    row["coordinates"]["geometry"]["coordinates"][0] = position
    with pytest.raises(spatial.SpatialDataError, match="invalid WGS84"):
        spatial.normalize_locations([row], {"123": "whc:123"})


@pytest.mark.parametrize("mode", ["authority", "duplicate_source", "duplicate_site", "missing"])
def test_identity_bridge_requires_complete_unique_authority_mapping(mode: str) -> None:
    rows = [record()]
    bridge = {"123": "whc:123"}
    if mode == "authority":
        rows[0]["id_no"] = "bad"
    elif mode == "duplicate_source":
        rows.append(record())
    elif mode == "duplicate_site":
        rows.append(empty_record())
        bridge["456"] = "whc:123"
    else:
        bridge["456"] = "whc:456"
    with pytest.raises(spatial.SpatialDataError):
        spatial.normalize_locations(rows, bridge)


def test_bundled_source_points_do_not_change_site_representatives() -> None:
    sites = load_corpus()
    originals = [site.model_dump(mode="json") for site in sites]
    locations = spatial.load_world_locations()
    assert locations.version == "world-locations-v1"
    assert dict(locations.counts) == spatial.EXPECTED_COUNTS
    assert len(locations.points) == 1033
    assert sum(len(points) for points in locations.points.values()) == 5632
    assert len({point for points in locations.points.values() for point in points}) == 5327
    assert locations.points["whc:868"] == locations.points["whc:1567"] == ()
    assert len(locations.points["whc:1718"]) == 277
    assert len(locations.points["whc:874"]) == 758
    assert locations.source["license"] == "CC BY-SA 4.0"
    assert locations.source["records_sha256"] == spatial.catalogue.RECORDS_SHA256
    assert all(not key.startswith("ats:") for key in locations.points)
    assert [site.model_dump(mode="json") for site in sites] == originals
    assert any(
        site.source_kind == "global" and site.id in locations.points
        and site.repr_point != locations.points[site.id][0]
        for site in sites
    )
    for site in sites:
        if site.id in locations.points:
            assert site.geography is not None
            assert site.geography.point_count == max(1, len(locations.points[site.id]))


def test_loaded_metadata_and_mappings_are_immutable() -> None:
    locations = spatial.load_world_locations()
    first = locations.records["whc:1718"][0]
    assert first.source_index == 0 and first.coordinate == locations.points["whc:1718"][0]
    with pytest.raises(FrozenInstanceError):
        first.name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        locations.points["whc:1718"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        locations.source["license"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize("field", ["coordinate", "site_id", "name", "ref", "source_index"])
def test_payload_cannot_resign_itself_using_a_changed_manifest(
    bundled_copy: Path, field: str,
) -> None:
    path = bundled_copy / spatial.LOCATIONS_FILENAME
    value = json.loads(path.read_text("utf-8"))
    point = value["whc:1718"]["points"][0]
    if field == "coordinate":
        point["coordinate"][0] += 0.01
    elif field == "site_id":
        value["whc:999999"] = value.pop("whc:1718")
    else:
        point[field] = 2 if field == "source_index" else "changed"
    write_json(path, value)
    manifest_path = bundled_copy / spatial.MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["files"][spatial.LOCATIONS_FILENAME]["sha256"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    write_json(manifest_path, manifest)
    with pytest.raises(spatial.SpatialDataError, match="independent pin"):
        spatial.load_world_locations(bundled_copy)


@pytest.mark.parametrize("field", ["version", "license", "counts", "processing", "schema_bool"])
def test_manifest_schema_license_counts_and_processing_are_fixed(
    bundled_copy: Path, field: str,
) -> None:
    path = bundled_copy / spatial.MANIFEST_FILENAME
    manifest = json.loads(path.read_text("utf-8"))
    if field == "license":
        manifest["source"]["license"] = "public domain"
    elif field == "counts":
        manifest["counts"]["source_points"] -= 305
    elif field == "processing":
        manifest["processing"]["coordinates"] = "Deduplicated"
    elif field == "schema_bool":
        manifest["schema_version"] = True
    else:
        manifest["version"] = "other"
    write_json(path, manifest)
    with pytest.raises(spatial.SpatialDataError, match="contract differs"):
        spatial.load_world_locations(bundled_copy)


def test_missing_files_have_an_explicit_prepare_hint(tmp_path: Path) -> None:
    with pytest.raises(spatial.SpatialDataError, match="--rebuild"):
        spatial.load_world_locations(tmp_path)


def test_rebuild_rejects_unpinned_cache_before_writing_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "records.json").write_text("[]", "utf-8")
    with pytest.raises(spatial.SpatialDataError, match="checksum differs"):
        spatial.rebuild_world_locations(cache, tmp_path)
    assert not (tmp_path / spatial.LOCATIONS_FILENAME).exists()


def test_normalizer_is_deterministic_without_mutating_source_rows() -> None:
    row = record()
    before = copy.deepcopy(row)
    first = spatial.normalize_locations([row], {"123": "wd:Q123"})
    second = spatial.normalize_locations([row], {"123": "wd:Q123"})
    assert first == second and row == before
