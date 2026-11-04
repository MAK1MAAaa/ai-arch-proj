"""Third-source response contracts use isolated synthetic locations, never real sources."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from archsearch import coverage, nps_data, nps_spatial_data, protection_data
from archsearch.bounds import SpatialBounds
from archsearch.domain import Geography, Site, SourceReference
from archsearch.spatial_data import SourceLocation, WorldLocations

NPS_ID = "auth:nps-nris:00000001"
WORLD_ID = "auth:fixture:world"
HAGUE_ID = "auth:fixture:hague"
FIRST = (144.1, 13.1)
SECOND = (144.2, 13.2)


def locations(
    identifier: str, points: tuple[tuple[float, float], ...],
    source: dict[str, str], version: str,
) -> WorldLocations:
    records = tuple(SourceLocation(index, point, "Synthetic well", f"fixture:{index}")
                    for index, point in enumerate(points))
    return WorldLocations(
        version=version, points=MappingProxyType({identifier: points}),
        records=MappingProxyType({identifier: records}), source=MappingProxyType(source),
        counts=MappingProxyType({"source_points": len(points)}),
    )


def site(identifier: str, point: tuple[float, float] | None) -> Site:
    reference = SourceReference(
        id="fixture:" + identifier, title="Synthetic source only",
        uri="https://example.org/fixture", publisher="Synthetic fixture",
    )
    return Site(
        id=identifier, title="Synthetic place " + identifier, description="Fixture only.",
        names=[], types=["historic-site"], periods=[], repr_point=point,
        source_uri=reference.uri, contributors=["Synthetic fixture"], period_evidence=[],
        source_kind="supplement", source_refs=[reference],
        geography=Geography(
            authority_id="supplement:" + identifier,
            countries=["GU"], regions=["nps-pacific"], source=reference,
            point_count=int(point is not None),
        ),
    )


@pytest.fixture
def registry_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Site]:
    (tmp_path / "catalogue_manifest.json").write_text(json.dumps({
        "countries": [{"id": "GU", "label": "Synthetic Guam"}],
        "regions": [{"id": "nps-pacific", "label": "Synthetic project grouping"}],
    }), encoding="utf-8")
    for filename in ["protection_manifest.json", "nps_pacific_manifest.json"]:
        (tmp_path / filename).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(nps_data, "new_country_labels", lambda _: {})
    monkeypatch.setattr(nps_data, "project_region_labels", lambda _: {})
    monkeypatch.setattr(nps_data, "SPEC_SHA256", "a" * 64)
    for module, name, identifier, dataset, point, version in [
        (coverage, "load_world_locations", WORLD_ID, "whc001", (140.0, 10.0),
         "world-fixture-v1"),
        (protection_data, "load_protection_locations", HAGUE_ID, "chp001", (141.0, 11.0),
         "hague-fixture-v1"),
    ]:
        value = locations(identifier, (point,), {
            "dataset_id": dataset, "uri": "https://example.org/" + dataset,
            "modified": "synthetic-" + dataset, "records_sha256": dataset[0] * 64,
            "license": "Synthetic original licence " + dataset,
            "license_uri": "https://example.org/licence/" + dataset,
        }, version)
        monkeypatch.setattr(module, name, lambda _, value=value: value)
    additional = locations(NPS_ID, (FIRST, SECOND), nps_spatial_data._source(),
                           nps_spatial_data.LOCATIONS_VERSION)
    monkeypatch.setattr(nps_spatial_data, "load_nps_locations", lambda _: additional)
    return [site(WORLD_ID, (140.0, 10.0)), site(HAGUE_ID, (141.0, 11.0)),
            site(NPS_ID, FIRST)]


def test_three_source_response_models_preserve_original_and_derived_attribution(
    registry_inputs: list[Site], tmp_path: Path,
) -> None:
    registry = coverage.load_registry(tmp_path)
    catalogue = coverage.CatalogueIndex(registry_inputs, "synthetic-global", registry)
    response = catalogue.spatial_coverage()
    assert response and response.ready
    assert response.records == 3 and response.points == 4
    groups = response.source_groups
    assert len(groups) == 3
    for group, dataset in zip(groups[:2], ["whc001", "chp001"], strict=True):
        assert group.source.model_dump() == {
            "name": "UNESCO DataHub " + dataset,
            "uri": "https://example.org/" + dataset,
            "version": "synthetic-" + dataset,
            "license": "Synthetic original licence " + dataset,
            "license_uri": "https://example.org/licence/" + dataset,
            "sha256": dataset[0] * 64,
        }
    derived = groups[2].source
    assert derived.name == "NPS Pacific reviewed location contract (derived)"
    assert "UNESCO" not in derived.name and "DataHub" not in derived.name
    assert derived.version == nps_data.COHORT_VERSION
    assert derived.sha256 == "a" * 64
    assert derived.uri.endswith("/src/archsearch/data/nps_pacific_review.json")
    assert derived.license_uri == "https://www.nps.gov/aboutus/disclaimer.htm"
    assert groups[2].site_ids == [NPS_ID]
    details = catalogue.site_locations(registry_inputs[2])
    assert details.source == derived
    assert details.representative_point == FIRST
    assert details.source_points == [FIRST, SECOND]
    assert [row.source_index for row in details.source_location_records] == [0, 1]
    assert "固定DataHub" not in details.note
    assert catalogue.site_locations(registry_inputs[0]).source == groups[0].source
    assert catalogue.site_locations(registry_inputs[1]).source == groups[1].source


def test_second_well_matches_parent_once_without_changing_representative(
    registry_inputs: list[Site], tmp_path: Path,
) -> None:
    catalogue = coverage.CatalogueIndex(
        registry_inputs, "synthetic-global", coverage.load_registry(tmp_path),
    )
    page = catalogue.page(bbox=SpatialBounds.from_csv("144.19,13.19,144.21,13.21"))
    assert page.total == 1
    assert [row.id for row in page.sites] == [NPS_ID]
    assert page.sites[0].repr_point == FIRST
    assert page.spatial_match_mode == "source-or-representative"
    assert len(catalogue.sites) == 3


@pytest.mark.parametrize("failure", ["missing", "corrupt"])
def test_third_source_failure_discards_the_whole_point_layer(
    registry_inputs: list[Site], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    def fail(_: Path) -> WorldLocations:
        raise nps_spatial_data.NpsSpatialError("Synthetic " + failure + " sidecar")

    monkeypatch.setattr(nps_spatial_data, "load_nps_locations", fail)
    registry = coverage.load_registry(tmp_path)
    assert registry.spatial is None
    assert registry.spatial_error
    assert "archsearch.nps_spatial_data --rebuild" in registry.spatial_error
    catalogue = coverage.CatalogueIndex(registry_inputs, "synthetic-global", registry)
    assert len(catalogue.sites) == 3
    assert catalogue.source_points(NPS_ID) == []
    page = catalogue.page(bbox=SpatialBounds.from_csv("144.19,13.19,144.21,13.21"))
    assert page.total == 0 and page.spatial_match_mode == "representative-only"
    state = catalogue.spatial_coverage()
    assert state and not state.ready and state.source_groups == []


def test_empty_approved_point_set_does_not_append_a_third_source_group(
    registry_inputs: list[Site], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = WorldLocations(
        version=nps_spatial_data.LOCATIONS_VERSION, points=MappingProxyType({}),
        records=MappingProxyType({}), source=MappingProxyType(nps_spatial_data._source()),
        counts=MappingProxyType({"source_points": 0}),
    )
    monkeypatch.setattr(nps_spatial_data, "load_nps_locations", lambda _: empty)
    registry = coverage.load_registry(tmp_path)
    assert registry.spatial and registry.spatial_error is None
    assert len(registry.spatial.source_groups) == 2
    assert nps_spatial_data.LOCATIONS_VERSION not in registry.spatial.version
    null_sites = [*registry_inputs[:2], site(NPS_ID, None)]
    response = coverage.CatalogueIndex(null_sites, "synthetic-global", registry).spatial_coverage()
    assert response and response.ready and len(response.source_groups) == 2
