"""Multiple fixed location sources preserve attribution, identity and failure boundaries."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import archsearch.coverage as coverage_module
import archsearch.protection_data as protection
from archsearch.api import create_app
from archsearch.bounds import SpatialBounds
from archsearch.coverage import CatalogueIndex, CoverageRegistry, load_registry
from archsearch.domain import Geography, Site, SourceReference
from archsearch.spatial_data import (
    SourceGroup,
    SourceLocation,
    SpatialDataError,
    WorldLocations,
    load_world_locations,
    merge_world_locations,
)


def locations(dataset: str, identifier: str, point: tuple[float, float]) -> WorldLocations:
    return WorldLocations(
        version=f"{dataset}-locations-v1", points={identifier: (point, point)},
        records={identifier: (SourceLocation(0, point, "Original first", "0"),
                              SourceLocation(1, point, "Original duplicate", "1"))},
        source={"dataset_id": dataset, "uri": f"https://example.org/{dataset}",
                "modified": "2026-11-04", "records_sha256": "a" * 64,
                "license": "CC BY-SA 4.0", "license_uri": "https://example.org/license"},
        counts={"source_points": 2},
    )


def test_composition_keeps_each_sequence_and_source_identity(sample_sites: list[Site]) -> None:
    primary = locations("whc001", "3", (10, 30))
    additional = locations("chp001", "1", (35, 34))
    combined = merge_world_locations(primary, additional)
    assert combined.version == "whc001-locations-v1+chp001-locations-v1"
    assert combined.points["3"] == primary.points["3"]
    assert combined.records["3"] == primary.records["3"]
    assert combined.points["1"] == additional.points["1"]
    assert [group.site_ids for group in combined.source_groups] == [("3",), ("1",)]
    index = CatalogueIndex(sample_sites, "fixture", CoverageRegistry({}, {}, spatial=combined))
    coverage = index.spatial_coverage()
    assert coverage is not None and coverage.ready
    assert (coverage.records, coverage.points, coverage.distinct_points,
            coverage.duplicate_points) == (2, 4, 2, 2)
    sources = coverage.source_groups
    assert sources[0].source.uri == "https://example.org/whc001"
    assert sources[1].source.uri == "https://example.org/chp001"
    assert index.site_locations(sample_sites[0]).source == sources[0].source
    assert index.site_locations(sample_sites[1]).source == sources[1].source
    assert index.site_locations(sample_sites[2]).source is None
    assert primary.source_groups == () and additional.source_groups == ()
    with pytest.raises(TypeError):
        combined.points["3"] = ()  # type: ignore[index]


@pytest.mark.parametrize("malformation", ["same-site", "same-dataset", "unmapped-group",
                                         "sequence", "point", "missing-labels"])
def test_composition_rejects_identity_or_location_corruption(malformation: str) -> None:
    primary = locations("whc001", "3", (10, 30))
    additional = locations("chp001", "1", (35, 34))
    if malformation == "same-site":
        additional = locations("chp001", "3", (35, 34))
    elif malformation == "same-dataset":
        additional = locations("whc001", "1", (35, 34))
    elif malformation == "unmapped-group":
        additional = replace(additional, source_groups=(SourceGroup(
            additional.version, additional.source, ("missing",),
        ),))
    elif malformation == "sequence":
        additional = replace(additional, records={"1": (
            SourceLocation(1, (35, 34), "wrong index", "0"),
            SourceLocation(1, (35, 34), "duplicate", "1"),
        )})
    elif malformation == "point":
        additional = locations("chp001", "1", (181, 34))
    else:
        additional = replace(additional, records={})
    with pytest.raises(SpatialDataError):
        merge_world_locations(primary, additional)


def test_invalid_group_mapping_has_no_partial_source_fallback(sample_sites: list[Site]) -> None:
    combined = merge_world_locations(locations("whc001", "3", (10, 30)),
                                     locations("chp001", "1", (35, 34)))
    broken = replace(combined, source_groups=(SourceGroup(
        combined.version, combined.source, ("3",),
    ),))
    index = CatalogueIndex(sample_sites, "fixture", CoverageRegistry({}, {}, spatial=broken))
    assert index.spatial is None
    assert index.spatial_coverage() is not None and not index.spatial_coverage().ready
    assert index.source_points("3") == index.source_points("1") == []
    assert index.page().spatial_match_mode == "representative-only"


@pytest.mark.parametrize("failure", ["missing", "conflicting-identity"])
def test_unavailable_second_source_keeps_representatives_and_explicit_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    (tmp_path / "protection_manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(coverage_module, "load_world_locations",
                        lambda directory: locations("whc001", "3", (10, 30)))

    def missing(directory: Path) -> WorldLocations:
        if failure == "conflicting-identity":
            return locations("chp001", "3", (35, 34))
        raise protection.ProtectionError("missing or mismatched protection sidecar")

    monkeypatch.setattr(protection, "load_protection_locations", missing)
    registry = load_registry(tmp_path)
    assert registry.spatial is None
    assert registry.spatial_error and "protection_data --rebuild" in registry.spatial_error


def test_combined_source_attribution_and_version_are_serialized_by_real_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_sites: list[Site],
) -> None:
    combined = merge_world_locations(locations("whc001", "3", (10, 30)),
                                     locations("chp001", "1", (35, 34)))
    registry = CoverageRegistry({}, {}, spatial=combined)
    monkeypatch.setattr(coverage_module, "load_registry", lambda: registry)
    with TestClient(create_app(home=tmp_path, sites=sample_sites)) as client:
        detail = client.get("/api/sites/1/locations")
        assert detail.status_code == 200
        assert detail.json()["source"]["uri"] == "https://example.org/chp001"
        assert detail.json()["spatial_version"] == combined.version
        groups = client.get("/api/coverage").json()["spatial_locations"]["source_groups"]
        assert groups[0]["site_ids"] == ["3"] and groups[1]["site_ids"] == ["1"]
        assert groups[0]["source"]["uri"] == "https://example.org/whc001"
        page = client.get("/api/sites", params={"bbox": "34.9,33.9,35.1,34.1"}).json()
        assert page["spatial_version"] == combined.version
        assert page["spatial_match_mode"] == "source-or-representative"
        assert [site["id"] for site in page["sites"]] == ["1"]
        search = client.post("/api/search", json={"query": "port", "mode": "bm25"})
        assert search.status_code == 200


def test_existing_world_sidecar_stays_byte_and_sequence_identical() -> None:
    original = load_world_locations()
    additional = locations("chp001", "auth:unesco-chp:fixture", (35, 34))
    combined = merge_world_locations(original, additional)
    assert len(original.points) == 1033
    assert sum(map(len, original.points.values())) == 5632
    assert all(combined.points[key] == points for key, points in original.points.items())
    assert all(combined.records[key] == records for key, records in original.records.items())
    assert combined.source_groups[0].source == original.source
    assert combined.source_groups[0].version == original.version


def test_reviewed_warehouse_is_preserved_in_audit_but_not_bbox_or_source_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_sites: list[Site],
) -> None:
    source = {"dataset_id": "chp001", "uri": "https://example.org/chp001",
              "modified": "2026-11-04", "records_sha256": "b" * 64,
              "license": "CC BY-SA 4.0", "license_uri": "https://example.org/license"}
    refs = SourceReference(id="qualification:fixture", title="Fixture site",
                           uri=source["uri"], publisher="Fixture", license=source["license"])
    site = Site.model_validate({**sample_sites[0].model_dump(),
        "id": "auth:unesco-chp:626", "source_kind": "supplement", "repr_point": (36, 34),
        "source_refs": [refs], "periods": [], "period_evidence": [], "types": ["historic-site"],
        "geography": Geography(authority_id="supplement:auth:unesco-chp:626", countries=["LB"],
                               regions=["arab-states"], source=refs),
    })
    audit = [
        protection.LocationReview(source_index=0, component_id=626, name_en="Original site",
                                  name_fr="Site", original_coordinate="34,36", coordinate=(36, 34),
                                  map_eligible=True, reason="Cultural original place"),
        protection.LocationReview(source_index=1, component_id=627, name_en="Warehouse",
                                  name_fr="Entrepôt", original_coordinate="35,37",
                                  coordinate=(37, 35),
                                  map_eligible=False, reason="Storage is not the original place"),
    ]
    record = SimpleNamespace(site=site, source_id=626, locations=audit)
    spec = SimpleNamespace(records=[record])
    payload = protection._bytes(protection._locations(spec))
    (tmp_path / protection.LOCATIONS_FILE).write_bytes(payload)
    monkeypatch.setattr(protection, "_spec", lambda directory: spec)
    monkeypatch.setattr(protection, "LOCATIONS_SHA256", protection._hash(payload))
    monkeypatch.setattr(protection, "_manifest", lambda *args: {"source": source})
    actual = protection.load_protection_locations(tmp_path)
    assert actual.points[site.id] == ((36, 34),)
    assert "source_index:0" in actual.records[site.id][0].ref
    assert len(protection._locations(spec)["records"][site.id]) == 2
    assert protection._locations(spec)["records"][site.id][1]["map_eligible"] is False
    index = CatalogueIndex([site], "fixture", CoverageRegistry(
        {"LB": "Lebanon"}, {"arab-states": "Arab States"}, spatial=actual,
    ))
    assert index.page(bbox=SpatialBounds.from_csv("36.9,34.9,37.1,35.1")).total == 0
    assert index.page(bbox=SpatialBounds.from_csv("35.9,33.9,36.1,34.1")).total == 1
