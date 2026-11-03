"""Source location sidecars enrich maps without changing corpus or retrieval evidence."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import archsearch.coverage as coverage_module
from archsearch.api import create_app
from archsearch.coverage import CatalogueIndex, CoverageRegistry, load_registry
from archsearch.domain import Geography, Site, SourceReference
from archsearch.history import HistoryStore
from archsearch.spatial_data import SourceLocation, SpatialDataError, WorldLocations


@pytest.fixture
def spatial_sites(sample_sites: list[Site]) -> list[Site]:
    source = SourceReference(
        id="fixture-geo", title="Declared source membership", uri="https://example.org/data",
        publisher="Fixture", license="CC0",
    )
    sites = []
    for site, countries, region in zip(
        sample_sites, [["IT", "FR"], ["IT"], []],
        ["europe-north-america", "europe-north-america", "arab-states"], strict=True,
    ):
        sites.append(site.model_copy(update={"geography": Geography(
            authority_id=site.id, countries=countries, regions=[region], source=source,
        )}))
    sites[1] = sites[1].model_copy(update={"repr_point": (10.0, 30.0)})
    for identifier, point in [(95, None), (80, (1.0, -90.0))]:
        value = sample_sites[0].model_dump()
        value.update(
            id=f"ats:hsm:{identifier}", source_kind="ats", title=f"Antarctic record {identifier}",
            types=["historic-site"], periods=[], period_evidence=[], source_refs=[source],
            repr_point=point, geography=Geography(
                authority_id=f"ats:hsm:{identifier}", countries=[], regions=["antarctica"],
                source=source, point_count=0 if point is None else 1,
            ),
        )
        sites.append(Site.model_validate(value))
    return sites


@pytest.fixture
def spatial_registry() -> CoverageRegistry:
    points = {"3": ((10.0, 30.0), (10.0, 30.0), (11.0, 31.0)),
              "1": ((10.0, 30.0),), "2": ()}
    records = {
        "3": (
            SourceLocation(0, (10.0, 30.0), "First source record", "same-ref"),
            SourceLocation(1, (10.0, 30.0), "Co-located source record", "second-ref"),
            SourceLocation(2, (11.0, 31.0), "Different source coordinate", "same-ref"),
        ),
        "1": (SourceLocation(0, (10.0, 30.0), "Another site's source", "one"),),
        "2": (),
    }
    return CoverageRegistry(
        countries={"IT": "Italy", "FR": "France"},
        regions={"europe-north-america": "Europe", "arab-states": "Arab States",
                 "antarctica": "Antarctica"},
        spatial=WorldLocations(
            version="fixture-spatial-v1", points=points, records=records,
            source={"dataset_id": "whc001", "uri": "https://example.org/data",
                    "modified": "2026-11-02", "records_sha256": "a" * 64,
                    "license": "CC BY-SA 4.0",
                    "license_uri": "https://creativecommons.org/licenses/by-sa/4.0/"},
            counts={"source_points": 4},
        ),
    )


@pytest.fixture
def spatial_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    spatial_sites: list[Site], spatial_registry: CoverageRegistry,
) -> TestClient:
    monkeypatch.setattr(coverage_module, "load_registry", lambda: spatial_registry)
    return TestClient(create_app(home=tmp_path, sites=spatial_sites))


def test_source_sequence_duplicates_and_references_are_preserved(
    spatial_sites: list[Site], spatial_registry: CoverageRegistry,
) -> None:
    index = CatalogueIndex(spatial_sites, "fixture-corpus", spatial_registry)
    catalogue = index.catalogue()
    point = next(item for item in catalogue.points if item.id == "3")
    assert catalogue.total == 5 and catalogue.spatial_version == "fixture-spatial-v1"
    assert point.repr_point == (12.0, 35.0)
    assert point.source_points == [(10, 30), (10, 30), (11, 31)]
    assert [row.source_index for row in point.source_location_records] == [0, 1, 2]
    assert [row.ref for row in point.source_location_records] == [
        "same-ref", "second-ref", "same-ref",
    ]
    assert [row.coordinate for row in point.source_location_records] == point.source_points
    assert point.source_location_records[1].name == "Co-located source record"


def test_display_count_keeps_distinct_representatives_and_cross_site_identities(
    spatial_sites: list[Site], spatial_registry: CoverageRegistry,
) -> None:
    value = CatalogueIndex(spatial_sites, "fixture", spatial_registry).coverage()
    assert value.total == 5
    assert value.locations.model_dump() == {"mapped": 3, "polar": 1, "unknown": 1}
    spatial = value.spatial_locations
    assert spatial is not None and spatial.ready and spatial.reason is None
    assert spatial.records == 3 and spatial.points == 4
    assert spatial.distinct_points == 3 and spatial.duplicate_points == 1
    # Site3 has two source positions plus its old representative. Sites1 and2 each add one.
    assert spatial.display_points == 5
    assert spatial.source is not None and spatial.source.license == "CC BY-SA 4.0"
    assert spatial.source.sha256 == "a" * 64 and spatial.source.version == "2026-11-02"


def test_no_source_point_fabrication_for_empty_nonworld_unknown_and_polar_records(
    spatial_client: TestClient,
) -> None:
    points = {row["id"]: row for row in spatial_client.get("/api/catalogue").json()["points"]}
    assert points["2"]["repr_point"] == [12, 35]
    for identifier in ["2", "ats:hsm:95", "ats:hsm:80"]:
        assert points[identifier]["source_points"] == []
        assert points[identifier]["source_location_records"] == []
    assert points["ats:hsm:95"]["repr_point"] is None
    assert points["ats:hsm:80"]["repr_point"] == [1, -90]
    assert points["ats:hsm:80"]["location_status"] == "polar"


def test_locations_route_separates_sources_and_preserves_identity_and_license(
    spatial_client: TestClient,
) -> None:
    response = spatial_client.get("/api/sites/3/locations")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert "etag" not in response.headers
    value = response.json()
    assert value["site_id"] == "3" and value["representative_point"] == [12, 35]
    assert value["source_points"] == [[10, 30], [10, 30], [11, 31]]
    assert value["source"]["license"] == "CC BY-SA 4.0"
    assert value["spatial_version"] == "fixture-spatial-v1"
    assert "未混入" in value["note"] and "政治归属" in value["note"]
    empty = spatial_client.get("/api/sites/2/locations").json()
    assert empty["source_points"] == [] and empty["source"] is not None
    unknown = spatial_client.get("/api/sites/ats%3Ahsm%3A95/locations").json()
    assert unknown["representative_point"] is None and unknown["source"] is None
    assert spatial_client.get("/api/sites/not-found/locations").status_code == 404


def test_version_identity_is_consistent_across_coverage_status_catalogue_and_detail(
    spatial_client: TestClient,
) -> None:
    coverage = spatial_client.get("/api/coverage").json()
    status = spatial_client.get("/api/status").json()
    catalogue = spatial_client.get("/api/catalogue").json()
    locations = spatial_client.get("/api/sites/3/locations").json()
    assert coverage["spatial_locations"] == status["spatial_locations"]
    assert catalogue["spatial_version"] == coverage["spatial_locations"]["version"]
    assert locations["spatial_version"] == catalogue["spatial_version"]
    assert status["semantic"]["ready"] is False and status["history"]["ready"] is False


def test_filters_and_pagination_count_sites_without_inferring_source_point_countries(
    spatial_client: TestClient,
) -> None:
    catalogue = spatial_client.get("/api/catalogue?country=IT&region=europe-north-america").json()
    assert catalogue["total"] == 2
    assert [row["id"] for row in catalogue["points"]] == ["3", "1"]
    assert catalogue["points"][0]["source_points"] == [[10, 30], [10, 30], [11, 31]]
    pages = [
        spatial_client.get(f"/api/sites?country=IT&limit=1&offset={i}").json() for i in range(2)
    ]
    assert [value["sites"][0]["id"] for value in pages] == ["3", "1"]
    assert all(value["total"] == 2 for value in pages)
    assert spatial_client.get("/api/catalogue?country=IT&region=antarctica").json()["total"] == 0
    assert spatial_client.get("/api/catalogue?country=AQ").status_code == 422


def test_sidecar_does_not_change_search_or_canonical_details(
    spatial_client: TestClient, spatial_sites: list[Site],
) -> None:
    result = spatial_client.post("/api/search", json={"query": "harbor", "mode": "bm25"}).json()
    assert {row["site"]["id"] for row in result["results"]} == {"3", "2"}
    assert result["total_candidates"] == 2
    assert all("source_points" not in row["site"] for row in result["results"])
    by_id = {site.id: site for site in spatial_sites}
    for row in result["results"]:
        assert row["site"] == by_id[row["site"]["id"]].model_dump(mode="json")
    assert spatial_client.get("/api/sites/3").json() == by_id["3"].model_dump(mode="json")


@pytest.mark.parametrize("corrupt", [False, True])
def test_missing_or_corrupt_sidecar_degrades_maps_without_disabling_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_sites: list[Site], corrupt: bool,
) -> None:
    if corrupt:
        (tmp_path / "world_locations_manifest.json").write_text("{not-json", encoding="utf-8")
        (tmp_path / "world_locations.json").write_text("{}", encoding="utf-8")
    registry = load_registry(tmp_path)
    assert registry.spatial is None and registry.spatial_error
    assert "rebuild" in registry.spatial_error
    monkeypatch.setattr(coverage_module, "load_registry", lambda: registry)
    with TestClient(create_app(home=tmp_path, sites=sample_sites)) as client:
        status = client.get("/api/status").json()["spatial_locations"]
        assert status["ready"] is False and status["reason"] == registry.spatial_error
        assert status["version"] is None and status["source"] is None
        assert status["points"] == 0 and status["display_points"] == 3
        catalogue = client.get("/api/catalogue").json()
        assert catalogue["total"] == 3 and catalogue["spatial_version"] is None
        assert all(row["source_points"] == [] for row in catalogue["points"])
        assert client.get("/api/sites/3").status_code == 200
        result = client.post("/api/search", json={"query": "harbor", "mode": "bm25"})
        assert result.status_code == 200
        assert client.get("/api/sites/3/locations").status_code == 503
        assert client.get("/api/sites/no-such-site/locations").status_code == 404


def test_small_legacy_registry_keeps_optional_metadata_and_empty_source_arrays(
    sample_sites: list[Site],
) -> None:
    index = CatalogueIndex(sample_sites, "legacy", CoverageRegistry(countries={}, regions={}))
    assert index.coverage().spatial_locations is None
    assert index.catalogue().spatial_version is None
    assert all(row.source_points == [] for row in index.catalogue().points)


def test_sidecar_from_another_corpus_is_not_partially_applied(
    sample_sites: list[Site], spatial_registry: CoverageRegistry,
) -> None:
    value = CatalogueIndex(sample_sites[:1], "other", spatial_registry)
    coverage = value.coverage().spatial_locations
    assert coverage is not None and not coverage.ready
    assert "身份不匹配" in coverage.reason
    assert coverage.display_points == 1
    assert value.catalogue().points[0].source_points == []
    with pytest.raises(SpatialDataError):
        value.site_locations(sample_sites[0])


def test_spatial_layer_preserves_history_conditional_etags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    spatial_sites: list[Site], spatial_registry: CoverageRegistry,
) -> None:
    history = Mock(spec=HistoryStore)
    history.boundaries.return_value = ({"type": "FeatureCollection", "features": []}, '"fixture"')
    monkeypatch.setattr(coverage_module, "load_registry", lambda: spatial_registry)
    with TestClient(create_app(home=tmp_path, sites=spatial_sites, history=history)) as client:
        assert client.get("/api/sites/3/locations").status_code == 200
        first = client.get("/api/history/boundaries?year=117")
        assert first.status_code == 200 and first.headers["etag"] == 'W/"fixture"'
        assert first.headers["cache-control"] == "private, no-cache"
        unchanged = client.get(
            "/api/history/boundaries?year=117", headers={"If-None-Match": 'W/"fixture"'},
        )
        assert unchanged.status_code == 304 and unchanged.content == b""
