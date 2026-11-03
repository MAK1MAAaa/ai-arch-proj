"""Coverage counts and browsing use source memberships without inferring from coordinates."""

from pathlib import Path

import pytest

from archsearch.coverage import CatalogueIndex, CoverageRegistry, load_registry
from archsearch.domain import ChronologyReview, Geography, Site, SourceReference


@pytest.fixture
def mapped_sites(sample_sites: list[Site]) -> list[Site]:
    source = SourceReference(
        id="fixture-geography", title="Official catalogue membership",
        uri="https://example.org/catalogue", publisher="Test source", license="CC0",
    )
    return [
        sample_sites[0].model_copy(update={"geography": Geography(
            authority_id="11", countries=["CN", "JP"], regions=["asia-pacific"], source=source,
        )}),
        sample_sites[1].model_copy(update={
            "geography": Geography(
                authority_id="12", countries=[], regions=["arab-states"], source=source,
                note="Country not declared; do not infer it from the representative point.",
            ),
            "chronology": ChronologyReview(
                status="insufficient", method="source excerpt check", reviewed_at="2026-11-04",
            ),
        }),
        sample_sites[2],
    ]


def index(sites: list[Site]) -> CatalogueIndex:
    return CatalogueIndex(sites, "fixture-v3", CoverageRegistry(
        countries={"CN": "China", "JP": "Japan"},
        regions={"asia-pacific": "亚太地区", "arab-states": "阿拉伯国家"},
    ))


def test_coverage_preserves_transnational_membership_and_unknowns(mapped_sites: list[Site]) -> None:
    response = index(mapped_sites).coverage()
    assert response.corpus_version == "fixture-v3" and response.total == 3
    assert [(row.id, row.label, row.count) for row in response.countries] == [
        ("CN", "China", 1), ("JP", "Japan", 1),
    ]
    assert {row.id: row.count for row in response.regions} == {
        "asia-pacific": 1, "arab-states": 1,
    }
    assert response.geography_unknown == 1
    assert response.country_unknown == 2
    assert response.chronology.insufficient == 1 and response.chronology.not_reviewed == 2
    assert sum(row.count for row in response.sources) == response.total
    assert response.authority is None


def test_authority_coverage_counts_unique_ids_and_exposes_its_denominator(
    mapped_sites: list[Site],
) -> None:
    registry = CoverageRegistry(
        countries={}, regions={}, authority_ids=frozenset({"11", "12", "13"}),
        source={
            "dataset_id": "fixture", "uri": "https://example.org/data", "modified": "v1",
            "records_sha256": "pinned", "license": "CC0", "license_uri": "https://example.org/cc0",
        }, excluded_natural=2,
    )
    response = CatalogueIndex(mapped_sites, "fixture-v3", registry).coverage()
    assert response.authority is not None
    assert response.authority.covered == 2 and response.authority.eligible_total == 3
    assert response.authority.missing == 1 and response.authority.excluded_natural == 2
    assert "固定版本" in response.authority.note


def test_compact_points_are_stably_ordered_and_do_not_redistribute_source_text(
    mapped_sites: list[Site],
) -> None:
    catalogue = index(list(reversed(mapped_sites))).catalogue()
    assert [point.id for point in catalogue.points] == ["3", "1", "2"]
    assert catalogue.total == 3
    point = catalogue.points[0]
    assert point.countries == ["CN", "JP"] and point.repr_point == (12.0, 35.0)
    assert "description" not in point.model_dump() and "chronology" not in point.model_dump()
    assert point.chronology_status == "not_reviewed"


def test_filters_intersect_and_preserve_empty_matches(mapped_sites: list[Site]) -> None:
    catalogue = index(mapped_sites)
    assert [point.id for point in catalogue.catalogue(country="CN").points] == ["3"]
    assert catalogue.catalogue(country="JP", region="arab-states").total == 0
    assert catalogue.page(region="arab-states").sites[0].id == "1"
    assert catalogue.page(country="CN", kind="bath").total == 0
    assert catalogue.page(kind="port").total == 2


def test_pages_have_no_gaps_or_duplicates_and_out_of_range_offsets_are_empty(
    mapped_sites: list[Site],
) -> None:
    catalogue = index(mapped_sites)
    pages = [catalogue.page(offset=offset, limit=1) for offset in range(3)]
    assert [page.sites[0].id for page in pages] == ["3", "1", "2"]
    assert all(page.total == 3 and page.limit == 1 for page in pages)
    assert catalogue.page(offset=100, limit=10).sites == []


@pytest.mark.parametrize("filters", [
    {"country": "XX"}, {"country": "cn"}, {"country": ""},
    {"region": "unknown"}, {"region": ""}, {"kind": "unknown"},
])
def test_unknown_filter_ids_are_rejected(mapped_sites: list[Site], filters: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        index(mapped_sites).filtered(**filters)


@pytest.mark.parametrize("offset,limit", [(-1, 10), (0, 0), (0, 101), (True, 10), (0, 1.5)])
def test_page_bounds_are_validated(mapped_sites: list[Site], offset: int, limit: int) -> None:
    with pytest.raises(ValueError):
        index(mapped_sites).page(offset=offset, limit=limit)


def test_empty_corpus_reports_zero_without_inventing_geography() -> None:
    catalogue = index([])
    assert catalogue.coverage().total == 0 and catalogue.coverage().countries == []
    assert catalogue.catalogue().points == [] and catalogue.page().sites == []


def test_registry_loading_is_offline_and_labels_are_separate_from_membership(
    tmp_path: Path,
) -> None:
    (tmp_path / "catalogue_manifest.json").write_text(
        '{"countries":[{"id":"CN","label":"China"}],'
        '"regions":[{"id":"asia-pacific","label":"亚太地区"}]}', encoding="utf-8",
    )
    registry = load_registry(tmp_path)
    assert registry.countries == {"CN": "China"}
    assert registry.regions == {"asia-pacific": "亚太地区"}
    assert CatalogueIndex([], "empty", registry).coverage().countries == []
