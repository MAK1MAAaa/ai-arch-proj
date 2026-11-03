"""Unknown positions and polar coordinates remain searchable without Mercator clipping."""

from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from archsearch.api import create_app
from archsearch.coverage import (
    WEB_MERCATOR_MAX_LATITUDE,
    CatalogueIndex,
    CoverageRegistry,
    load_registry,
    location_status,
)
from archsearch.domain import Geography, Site, SourceReference
from archsearch.index import SemanticIndex
from archsearch.search import SearchEngine, SearchRequest


@pytest.fixture
def antarctic_sites(sample_sites: list[Site]) -> list[Site]:
    source = SourceReference(
        id="ats-fixture", title="Antarctic Treaty HSM fixture",
        uri="https://example.org/ats-hsm", publisher="Antarctic Treaty fixture",
        license="CC BY 4.0",
    )
    sites = []
    for number, title, point in [
        (1, "Antarctic mapped memorial", (179.0, -85.0)),
        (24, "Antarctic polar memorial", (0.0, -89.999)),
        (95, "Antarctic unknown wreck", None),
    ]:
        value = sample_sites[0].model_dump()
        value.update(
            id=f"ats:hsm:{number}", source_kind="ats", title=title,
            description="Antarctic historic heritage with source evidence.",
            types=["historic-site"], periods=[], period_evidence=[], source_refs=[source],
            repr_point=point, geography=Geography(
                authority_id=f"ats:hsm:{number}", countries=[], regions=["antarctica"],
                source=source, point_count=0 if point is None else 1,
            ),
        )
        sites.append(Site.model_validate(value))
    return sites


def test_location_counts_distinguish_records_from_projectable_points(
    sample_sites: list[Site], antarctic_sites: list[Site],
) -> None:
    index = CatalogueIndex(sample_sites[:1] + antarctic_sites, "polar-fixture")
    coverage = index.coverage()
    assert coverage.total == 4
    assert coverage.locations.model_dump() == {"mapped": 2, "polar": 1, "unknown": 1}
    assert coverage.country_unknown == 4
    assert {facet.id: facet.count for facet in coverage.sources} == {"pleiades": 1, "ats": 3}
    assert coverage.countries == []
    assert {facet.id: facet.count for facet in coverage.regions} == {"antarctica": 3}
    catalogue = index.catalogue(region="antarctica")
    assert catalogue.total == len(catalogue.points) == 3
    points = {point.id: point for point in catalogue.points}
    assert points["ats:hsm:24"].repr_point == (0, -89.999)
    assert points["ats:hsm:24"].location_status == "polar"
    assert points["ats:hsm:95"].repr_point is None
    assert points["ats:hsm:95"].location_status == "unknown"
    assert points["ats:hsm:1"].location_status == "mapped"


def test_nullable_ats_points_do_not_relax_existing_source_invariants(
    sample_sites: list[Site],
) -> None:
    value = sample_sites[0].model_dump()
    value["repr_point"] = None
    with pytest.raises(ValidationError, match="valid representative point"):
        Site.model_validate(value)
    value = sample_sites[0].model_dump()
    value["geography"] = Geography(
        countries=[], regions=[], point_count=0,
        source=SourceReference(
            id="fixture", title="Source", uri="https://example.org/source", publisher="Test",
        ),
    )
    with pytest.raises(ValidationError, match="at least one source point"):
        Site.model_validate(value)


@pytest.mark.parametrize("latitude,expected", [
    (-90.0, "polar"), (90.0, "polar"),
    (-WEB_MERCATOR_MAX_LATITUDE, "mapped"), (WEB_MERCATOR_MAX_LATITUDE, "mapped"),
    (-WEB_MERCATOR_MAX_LATITUDE - 1e-9, "polar"),
    (WEB_MERCATOR_MAX_LATITUDE + 1e-9, "polar"),
])
def test_projection_classification_preserves_the_true_coordinate(
    antarctic_sites: list[Site], latitude: float, expected: str,
) -> None:
    site = antarctic_sites[0].model_copy(update={"repr_point": (0, latitude)})
    assert location_status(site) == expected
    assert site.repr_point == (0, latitude)


def test_ats_authority_numbers_do_not_inflate_unesco_coverage(
    antarctic_sites: list[Site],
) -> None:
    fake_number_collision = antarctic_sites[0].model_copy(update={
        "geography": antarctic_sites[0].geography.model_copy(update={"authority_id": "11"})
    })
    registry = CoverageRegistry(
        countries={}, regions={"antarctica": "南极"}, authority_ids=frozenset({"11"}),
        source={
            "dataset_id": "whc-fixture", "uri": "https://example.org/whc", "modified": "v1",
            "records_sha256": "hash-whc", "license": "CC0",
            "license_uri": "https://example.org/license",
        },
        polar_ids=frozenset({"ats:hsm:1", "ats:hsm:24", "ats:hsm:95", "ats:hsm:96"}),
        polar_source={
            "dataset_id": "ats-hsm", "uri": "https://example.org/ats", "accessed": "2026-11-04",
            "sha256": "hash-ats", "license": "CC BY 4.0",
            "license_uri": "https://creativecommons.org/licenses/by/4.0/",
        }, polar_excluded_types={"ASPA": 84, "ASMA": 7},
    )
    index = CatalogueIndex([fake_number_collision] + antarctic_sites[1:], "fixture", registry)
    coverage = index.coverage()
    assert coverage.authority is not None and coverage.authority.covered == 0
    assert coverage.authority.missing == 1
    assert coverage.polar_authority is not None
    assert coverage.polar_authority.covered == 3 and coverage.polar_authority.missing == 1
    assert coverage.polar_authority.eligible_total == 4
    assert coverage.polar_authority.excluded_types == {"ASPA": 84, "ASMA": 7}


def test_registry_merges_the_independent_antarctic_manifest_without_adding_countries(
    tmp_path: Path,
) -> None:
    (tmp_path / "catalogue_manifest.json").write_text(
        '{"countries":[{"id":"CN","label":"China"}],'
        '"regions":[{"id":"asia-pacific","label":"亚太地区"}]}', encoding="utf-8",
    )
    (tmp_path / "polar_manifest.json").write_text(
        '{"regions":[{"id":"antarctica","label":"南极"}],'
        '"partition":{"active_ids":["ats:hsm:95"],"excluded_types":{"ASPA":84,"ASMA":7}},'
        '"source":{"dataset_id":"ats-hsm"}}', encoding="utf-8",
    )
    registry = load_registry(tmp_path)
    assert registry.countries == {"CN": "China"}
    assert registry.regions == {"asia-pacific": "亚太地区", "antarctica": "南极"}
    assert registry.polar_ids == frozenset({"ats:hsm:95"})
    assert registry.polar_source == {"dataset_id": "ats-hsm"}
    assert registry.polar_excluded_types == {"ASPA": 84, "ASMA": 7}


def test_search_and_pages_keep_unknown_and_polar_sites(
    tmp_path: Path, antarctic_sites: list[Site],
) -> None:
    semantic = Mock(spec=SemanticIndex)
    semantic.sites = antarctic_sites
    semantic.ready = True
    semantic.reason = None
    semantic.scores.return_value = np.asarray([0.1, 0.2, 0.9], dtype=np.float32)
    engine = SearchEngine(antarctic_sites, semantic)
    for mode in ("semantic", "bm25"):
        hits, total = engine.search(SearchRequest(
            query="Antarctic", mode=mode, region="antarctica",
        ))
        assert total == 3 and {hit.site.id for hit in hits} == {site.id for site in antarctic_sites}
    with TestClient(create_app(home=tmp_path, sites=antarctic_sites, semantic=semantic)) as client:
        coverage = client.get("/api/coverage").json()
        assert coverage["locations"] == {"mapped": 1, "polar": 1, "unknown": 1}
        catalogue = client.get("/api/catalogue?region=antarctica").json()
        assert catalogue["total"] == len(catalogue["points"]) == 3
        unknown = next(point for point in catalogue["points"] if point["id"] == "ats:hsm:95")
        assert unknown["repr_point"] is None and unknown["location_status"] == "unknown"
        page = client.get("/api/sites?region=antarctica&limit=100").json()
        assert page["total"] == len(page["sites"]) == 3
        detail = client.get("/api/sites/ats%3Ahsm%3A95")
        assert detail.status_code == 200 and detail.json()["repr_point"] is None
        assert detail.json()["geography"]["point_count"] == 0
        result = client.post("/api/search", json={"query": "Antarctic", "region": "antarctica"})
        assert result.status_code == 200
        assert result.json()["results"][0]["site"]["repr_point"] is None
        assert result.json()["results"][0]["site"]["id"] == "ats:hsm:95"
        assert client.get("/api/catalogue?country=AQ").status_code == 422
