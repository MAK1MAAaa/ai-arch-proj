"""Physical browsing uses real source/representative positions, not country inference."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import archsearch.coverage as coverage_module
from archsearch.api import create_app
from archsearch.bounds import SpatialBounds
from archsearch.corpus import CORPUS_VERSION, load_corpus
from archsearch.coverage import CatalogueIndex, CoverageRegistry
from archsearch.domain import Geography, Site, SourceReference
from archsearch.spatial_data import SourceLocation, WorldLocations


@pytest.mark.parametrize("text", [
    "", " ", "1,2,3", "1,2,3,4,5", "nan,0,1,2", "0,-1,inf,1",
    "-181,-1,1,1", "-1,-91,1,1", "-1,-1,181,1", "-1,-1,1,91",
    "0,0,0,1", "180,-1,-180,1", "-1,1,1,1", "-1,2,1,1",
    "0x10,0,20,1", "1_0,0,20,1", "一,0,2,1", "1,0,2,null",
    "0,0,1e9999,1", "0,0,1,1" + " " * 201,
])
def test_invalid_rectangles_are_rejected_instead_of_becoming_global(text: str) -> None:
    with pytest.raises(ValueError):
        SpatialBounds.from_csv(text)


def test_numeric_bounds_reject_booleans_and_non_finite_values() -> None:
    for value in (True, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            SpatialBounds(west=value, south=0, east=1, north=1)


def test_closed_rectangle_preserves_prime_meridian_and_both_date_line_aliases() -> None:
    ordinary = SpatialBounds.from_csv(" -1e0 , -.5 , +1.0 , .5 ")
    assert ordinary.as_tuple() == (-1, -0.5, 1, 0.5)
    assert ordinary.contains((0, 0))
    assert ordinary.contains((-1, -0.5)) and ordinary.contains((1, 0.5))
    assert not ordinary.contains((1.001, 0))
    assert not ordinary.contains((float("inf"), 0))
    assert not SpatialBounds.from_csv("170,-10,-170,10").contains((181, 0))
    for box in ("170,-10,-170,10", "170,-10,180,10", "-180,-10,-170,10"):
        selected = SpatialBounds.from_csv(box)
        assert selected.contains((180, 0)) and selected.contains((-180, 0))
        assert not selected.contains((0, 0))
    world = SpatialBounds.from_csv("-180,-90,180,90")
    assert all(world.contains(point) for point in ((180, 90), (-180, -90), (0, 0)))


@pytest.fixture
def located_sites(sample_sites: list[Site]) -> list[Site]:
    source = SourceReference(
        id="fixture-culture", title="Fixture culture record", uri="https://example.org/record",
        publisher="Fixture authority", excerpt="Fixture named cultural place.",
    )
    sites = [
        sample_sites[0].model_copy(update={"title": "A source property", "geography": Geography(
            countries=["FR", "JP"], regions=["asia-pacific"], source=source,
        )}),
        sample_sites[1].model_copy(update={
            "title": "B Greenwich bath", "repr_point": (0.0, 0.0),
            "geography": Geography(countries=["FR"], regions=["europe-north-america"],
                                   source=source),
        }),
        sample_sites[2].model_copy(update={
            "title": "C date-line harbor", "repr_point": (-180.0, 1.0),
            "geography": Geography(countries=["US"], regions=["asia-pacific"], source=source),
        }),
    ]
    for identifier, kind, point, countries, regions in [
        ("auth:fixture:unknown", "supplement", None, ["FR"], ["asia-pacific"]),
        ("ats:hsm:1", "ats", (30.0, -89.0), [], ["antarctica"]),
    ]:
        value = sample_sites[0].model_dump()
        value.update(
            id=identifier, source_kind=kind, title=identifier, repr_point=point,
            types=["historic-site"], periods=[], period_evidence=[], source_refs=[source],
            geography=Geography(
                authority_id="supplement:" + identifier if kind == "supplement" else identifier,
                countries=countries, regions=regions, source=source,
                point_count=0 if point is None else 1,
            ),
        )
        sites.append(Site.model_validate(value))
    return sites


@pytest.fixture
def registry() -> CoverageRegistry:
    points = {"3": ((178.0, 1.0), (-178.0, 1.0), (178.0, 1.0)), "1": ((60.0, 0.0),)}
    return CoverageRegistry(
        countries={"FR": "France", "JP": "Japan", "US": "United States"},
        regions={"asia-pacific": "Asia/Pacific", "europe-north-america": "Europe/North America",
                 "antarctica": "Antarctica"},
        spatial=WorldLocations(
            version="fixture-spatial-v1", points=points,
            records={key: tuple(SourceLocation(index, point, "Source", str(index))
                                for index, point in enumerate(values))
                     for key, values in points.items()},
            source={"dataset_id": "fixture", "uri": "https://example.org/data", "modified": "v1",
                    "records_sha256": "a" * 64, "license": "CC0",
                    "license_uri": "https://example.org/license"},
            counts={"source_points": 4},
        ),
    )


def test_any_original_or_source_point_selects_one_identity_without_rewriting_records(
    located_sites: list[Site], registry: CoverageRegistry,
) -> None:
    index = CatalogueIndex(located_sites, "fixture", registry)
    before = [site.model_dump() for site in located_sites]
    wrapped = SpatialBounds.from_csv("170,-10,-170,10")
    page = index.page(bbox=wrapped)
    assert [site.id for site in page.sites] == ["3", "2"]
    assert page.total == 2 and page.bbox == (170, -10, -170, 10)
    assert page.spatial_match_mode == "source-or-representative"
    assert page.spatial_version == "fixture-spatial-v1"
    assert page.sites[0].repr_point == (12, 35)
    assert index.site_locations(page.sites[0]).source_points == [(178, 1), (-178, 1), (178, 1)]
    assert [site.model_dump() for site in located_sites] == before
    assert index.page(bbox=SpatialBounds.from_csv("-1,-1,1,1")).sites[0].repr_point == (0, 0)
    assert index.page(bbox=SpatialBounds.from_csv("59,-1,61,1")).sites[0].id == "1"
    assert index.page(bbox=SpatialBounds.from_csv("-180,-90,180,-86")).sites[0].repr_point == (
        30, -89,
    )
    assert index.page(bbox=SpatialBounds.from_csv("-180,-90,180,90")).total == 4
    assert index.page().total == 5


def test_bbox_intersects_source_membership_type_and_stable_pagination(
    located_sites: list[Site], registry: CoverageRegistry,
) -> None:
    index = CatalogueIndex(located_sites, "fixture", registry)
    box = SpatialBounds.from_csv("170,-10,-170,10")
    assert [site.id for site in index.page(country="FR", bbox=box).sites] == ["3"]
    assert index.page(country="JP", region="europe-north-america", bbox=box).total == 0
    assert index.page(kind="bath", bbox=box).total == 0
    pages = [index.page(offset=offset, limit=1, bbox=box) for offset in range(3)]
    assert [site.id for page in pages for site in page.sites] == ["3", "2"]
    assert all(page.total == 2 and page.bbox == box.as_tuple() for page in pages)
    assert index.page(bbox=SpatialBounds.from_csv("70,20,71,21")).sites == []


def test_missing_sidecar_uses_only_known_representatives_and_declares_the_limit(
    located_sites: list[Site], registry: CoverageRegistry,
) -> None:
    index = CatalogueIndex(
        located_sites, "fixture", replace(registry, spatial=None, spatial_error="fixture absent"),
    )
    page = index.page(bbox=SpatialBounds.from_csv("170,-10,-170,10"))
    assert [site.id for site in page.sites] == ["2"]
    assert page.spatial_match_mode == "representative-only" and page.spatial_version is None
    assert index.page().total == 5


def test_real_amazonia_component_is_browsable_without_substituting_its_representative() -> None:
    index = CatalogueIndex(load_corpus(), CORPUS_VERSION)
    box = SpatialBounds.from_csv("-60.05,-3.16,-60.00,-3.10")
    page = index.page(country="BR", bbox=box, limit=100)
    theater = next(site for site in page.sites if site.id == "whc:1774")
    assert theater.repr_point == (-48.4937027777, -1.4530277778)
    assert not box.contains(theater.repr_point)
    assert index.site_locations(theater).source_location_records[1].name == "Teatro Amazonas"
    assert index.site_locations(theater).source_points == [
        (-48.4937027777, -1.4530277778), (-60.0233972223, -3.1302805556),
    ]
    assert page.spatial_version == "world-locations-v1"
    assert page.spatial_match_mode == "source-or-representative"


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    located_sites: list[Site], registry: CoverageRegistry,
) -> TestClient:
    monkeypatch.setattr(coverage_module, "load_registry", lambda: registry)
    return TestClient(create_app(home=tmp_path, sites=located_sites))


def test_api_echoes_physical_filter_without_mutating_global_catalogue_or_search(
    client: TestClient,
) -> None:
    global_ids = [point["id"] for point in client.get("/api/catalogue").json()["points"]]
    query = {"query": "harbor", "mode": "bm25"}
    before = client.post("/api/search", json=query).json()["results"]
    response = client.get("/api/sites", params={"bbox": "170,-10,-170,10", "limit": 1})
    assert response.status_code == 200
    page = response.json()
    assert page["bbox"] == [170, -10, -170, 10] and page["total"] == 2
    assert page["sites"][0]["id"] == "3" and page["sites"][0]["repr_point"] == [12, 35]
    assert page["spatial_match_mode"] == "source-or-representative"
    assert page["spatial_version"] == "fixture-spatial-v1"
    assert client.get("/api/sites", params={"bbox": "170,-10,-170,10", "type": "bath"}).json()[
        "total"
    ] == 0
    assert [point["id"] for point in client.get("/api/catalogue").json()["points"]] == global_ids
    assert client.post("/api/search", json=query).json()["results"] == before
    assert client.post(
        "/api/search", json={**query, "bbox": [170, -10, -170, 10]},
    ).status_code == 422
    assert client.get("/api/catalogue", params={"bbox": "170,-10,-170,10"}).status_code == 422


@pytest.mark.parametrize("suffix", [
    "bbox=", "bbox=0,0,0,1", "bbox=nan,0,1,2", "bbox=0,-91,1,2",
    "bbox=180,0,-180,1", "bbox=170,-10,-170,10&bbox=170,-10,-170,10",
])
def test_api_never_silently_widens_an_invalid_or_repeated_bounds_request(
    client: TestClient, suffix: str,
) -> None:
    assert client.get("/api/sites?" + suffix).status_code == 422
