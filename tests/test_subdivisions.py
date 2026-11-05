"""Source membership filtering stays separate from text, coordinates and chronology."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlencode

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from archsearch import canada_data
from archsearch import subdivisions as sub
from archsearch.api import create_app
from archsearch.bounds import SpatialBounds
from archsearch.config import MODEL_REVISION
from archsearch.corpus import CORPUS_VERSION, build_document
from archsearch.coverage import CatalogueIndex, CoverageRegistry
from archsearch.domain import Geography, Site, SourceReference
from archsearch.index import SemanticIndex
from archsearch.search import SearchEngine, SearchRequest
from archsearch.spatial_data import SourceLocation, WorldLocations
from archsearch.supplement_data import SourceArtifact


def source(identifier: str = "fixture") -> SourceReference:
    return SourceReference(id=identifier, title="Original province field",
                           uri="https://example.org/record", publisher="Fixture authority",
                           license="CC0", excerpt="Ontario", revision="fixed1")


def dfhd_row(identifier: int, province: str) -> canada_data.DfhdSourceRow:
    raw = {field.alias: None for field in canada_data.DfhdSourceRow.model_fields.values()}
    raw.update({
        "_id": identifier, "Directory of Federal Heritage Designations Identifier": str(identifier),
        "Designation name": "Historic object " + str(identifier),
        "Designation type": canada_data.DESIGNATION_TYPE,
        "Designation statute": "Original fixture statute", "Designation date": "2000-01-01",
        "Province or territory": province, "Country": "Canada",
    })
    return canada_data.DfhdSourceRow.model_validate(raw)


def decision(identifier: int, province: str, disposition: str, target: str | None) -> Any:
    qualification = source("qualification:fixture:" + str(identifier)).model_copy(update={
        "uri": "https://open.canada.ca/data/api/3/action/datastore_search?" + urlencode({
            "resource_id": canada_data.SOURCE_RESOURCE_ID,
            "filters": json.dumps({"Directory of Federal Heritage Designations Identifier":
                                   str(identifier)}), "limit": 1,
        }),
    })
    return canada_data.CanadaDecision(
        source_row=dfhd_row(identifier, province), disposition=disposition, target_id=target,
        reason="Independent same-object fixture review; not expert confirmation.",
        evidence=[qualification], point_receipt=None,
        source_files=[SourceArtifact(filename="dfhd-pages/nhs-0000.json", sha256="a" * 64,
                                     uri="https://open.canada.ca/data/page")],
    )


@dataclass
class Bundle:
    directory: Path
    sites: list[Site]
    decisions: list[canada_data.CanadaDecision]
    review: dict[str, Any]
    monkeypatch: pytest.MonkeyPatch

    def pin_review(self, *, facts: bool = False) -> None:
        review = sub.SubdivisionReview.model_validate(self.review)
        raw = sub._bytes(review.model_dump(mode="json"))
        (self.directory / sub.REVIEW_FILE).write_bytes(raw)
        self.monkeypatch.setattr(sub, "REVIEW_SHA256", sub._hash(raw))
        if facts:
            self.monkeypatch.setattr(sub, "SOURCE_FACTS_SHA256",
                                    sub._hash(sub._bytes(sub.source_facts(review))))

    def payload(self) -> sub.SubdivisionPayload:
        return sub.compile_payload(sub.SubdivisionReview.model_validate(self.review), self.sites,
                                   self.decisions)

    def compile(self) -> dict[str, Any]:
        self.pin_review()
        self.monkeypatch.setattr(sub, "PAYLOAD_SHA256",
                                sub._hash(sub._bytes(self.payload().model_dump(mode="json"))))
        return sub.rebuild_subdivisions(self.sites, CORPUS_VERSION, self.directory)

    def index(self) -> sub.SubdivisionIndex:
        return sub.SubdivisionIndex(self.sites, CORPUS_VERSION, self.directory)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_sites: list[Site]) -> Bundle:
    sites = [site.model_copy(update={"geography": Geography(
        countries=["CA"], regions=["europe-north-america"], source=source(),
    )}) for site in sample_sites]
    missing = Site(
        id="auth:fixture:4", title="Quebec unlocated harbor", description="Historic harbor.",
        names=[], types=["historic-site"], periods=[], repr_point=None,
        source_uri="https://example.org/4", contributors=["Fixture"], period_evidence=[],
        source_kind="supplement", source_refs=[source()],
        geography=Geography(authority_id="supplement:auth:fixture:4", countries=["CA"],
                            regions=["europe-north-america"], source=source(), point_count=0),
    )
    sites += [missing, sites[0].model_copy(update={"id": "5", "title": "Unassigned harbor"}),
              sites[0].model_copy(update={"id": "6", "title": "French harbor",
                "geography": Geography(countries=["FR"], regions=["europe-north-america"],
                                       source=source())})]
    decisions = [decision(1, "Ontario", "include", "3"),
                 decision(2, "Ontario", "existing", "1"),
                 decision(3, "Nova Scotia", "include", "2"),
                 decision(4, "Quebec", "include", missing.id),
                 decision(5, "Nova Scotia", "component", "1"),
                 decision(6, "Quebec", "hold", None)]
    review = {
        "schema_version": 1, "version": sub.VERSION, "corpus_version": CORPUS_VERSION,
        **sub.corpus_contract(sites), "canada_spec_sha256": canada_data.SPEC_SHA256,
        "source_review_sha256": "b" * 64,
        "review_method": "Independent source fixture review, not expert/human confirmation.",
        "reviewed_at": "2026-11-05",
        "subdivisions": [{"id": "CA:ontario", "country": "CA", "label": "Ontario"},
                         {"id": "CA:nova-scotia", "country": "CA", "label": "Nova Scotia"},
                         {"id": "CA:quebec", "country": "CA", "label": "Quebec"}],
        "extra_memberships": [],
    }
    monkeypatch.setattr(sub, "SOURCE_REVIEW_SHA256", "b" * 64)
    monkeypatch.setattr(canada_data, "_spec", lambda _: SimpleNamespace(decisions=decisions))
    result = Bundle(tmp_path, sites, decisions, review, monkeypatch)
    result.pin_review(facts=True)
    result.compile()
    return result


def test_derivation_only_uses_whole_object_source_fields_and_preserves_all_sites(
    bundle: Bundle,
) -> None:
    before = [site.model_dump(mode="json") for site in bundle.sites]
    documents = [build_document(site) for site in bundle.sites]
    index = bundle.index()
    assert index.ready and index.ids("CA", "CA:ontario") == {"1", "3"}
    assert index.ids("CA", "CA:nova-scotia") == {"2"}
    assert index.site_response("1").subdivisions[0].label == "Ontario"
    assert not index.site_response("5").memberships
    assert [site.model_dump(mode="json") for site in bundle.sites] == before
    assert [build_document(site) for site in bundle.sites] == documents
    assert index.site_response("3").memberships[0].evidence[0].field == "Province or territory"
    assert index.site_response("3").memberships[0].evidence[0].raw_value == "Ontario"


def test_facets_count_distinct_objects_keep_unassigned_and_null_points(bundle: Bundle) -> None:
    index = bundle.index()
    ca = index.facets("CA", 5)
    assert ca.ready and ca.supported and ca.total == 5 and ca.assigned == 4 and ca.unassigned == 1
    assert {row.id: row.count for row in ca.subdivisions} == {
        "CA:ontario": 2, "CA:nova-scotia": 1, "CA:quebec": 1,
    }
    assert index.ids("CA", "CA:quebec") == {"auth:fixture:4"}
    assert "不表示实际地理未知" in ca.note
    fr = index.facets("FR", 1)
    assert fr.ready and not fr.supported and fr.assigned == 0 and fr.unassigned == 1


def minas_locality_fixture(bundle: Bundle) -> tuple[str, str]:
    site_id = "auth:br-iepha-mg:scope-" + "a" * 64
    label = "Belo Horizonte, Nova Lima e Sabará"
    original = {"processo_ano": "PTE163/2018", "municipio": label}
    site = bundle.sites[3].model_copy(update={
        "id": site_id, "title": "Source-registered composite object", "geography": Geography(
            authority_id="supplement:" + site_id, countries=["BR"],
            regions=["latin-america-caribbean"], source=source(), point_count=0,
        ),
    })
    bundle.sites.append(site)
    bundle.review.update(sub.corpus_contract(bundle.sites))
    bundle.review["minas_spec_sha256"] = "c" * 64
    bundle.review["subdivisions"].append({
        "id": "BR:mg-municipio-fixture", "country": "BR", "label": label,
    })
    bundle.review["extra_memberships"].append({
        "site_id": site_id, "subdivision_id": "BR:mg-municipio-fixture",
        "source": source("record:iepha-mg:153").model_copy(update={"excerpt": label})
            .model_dump(mode="json"),
        "artifact": {"filename": "mg/source.csv", "sha256": "d" * 64,
                     "uri": "https://example.org/record"},
        "field": "municipio", "raw_value": label, "source_label": label,
        "source_row": original, "source_row_sha256": sub._row_hash(original),
        "role": "source_record_locality",
        "review_method": "Independent literal original-record locality fixture.",
    })
    bundle.monkeypatch.setattr(sub, "_minas_pin_matches", lambda pin: pin == "c" * 64)
    return site_id, label


def test_original_municipality_value_keeps_composite_literal_and_unknown_location(
    bundle: Bundle,
) -> None:
    site_id, label = minas_locality_fixture(bundle)
    bundle.pin_review(facts=True)
    bundle.compile()
    index = bundle.index()
    assert index.ready and index.ids("BR", "BR:mg-municipio-fixture") == {site_id}
    response = index.facets("BR", 1)
    assert response.assigned == 1 and response.unassigned == 0
    assert [row.label for row in response.subdivisions] == [label]
    assert "多地值保持原串" in response.note and "不表示整体" in response.note
    assert bundle.sites[-1].repr_point is None
    assert index.site_response(site_id).memberships[0].evidence[0].raw_value == label
    assert index.ids("CA", "CA:ontario") == {"1", "3"}


@pytest.mark.parametrize("change", ["missing_pin", "wrong_field", "wrong_site_namespace", "zero"])
def test_municipality_association_requires_its_approved_cohort_and_original_field(
    bundle: Bundle, change: str,
) -> None:
    minas_locality_fixture(bundle)
    extra = bundle.review["extra_memberships"][0]
    if change == "missing_pin":
        bundle.review["minas_spec_sha256"] = None
    elif change == "wrong_field":
        extra["field"] = "distrito"
        extra["source_row"] = {"distrito": extra["raw_value"]}
    elif change == "wrong_site_namespace":
        extra["site_id"] = "auth:fixture:4"
    else:
        extra["raw_value"] = extra["source_label"] = "0"
        extra["source_row"] = {"municipio": "0"}
        bundle.review["subdivisions"][-1]["label"] = "0"
    extra["source_row_sha256"] = sub._row_hash(extra["source_row"])
    with pytest.raises(sub.SubdivisionUnavailable):
        bundle.payload()


def test_rebuild_is_deterministic_and_normal_load_never_reparses_the_large_review(
    bundle: Bundle, monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = [sub.PAYLOAD_FILE, sub.MANIFEST_FILE]
    before = {name: (bundle.directory / name).read_bytes() for name in names}
    for _ in range(2):
        bundle.compile()
        assert {name: (bundle.directory / name).read_bytes() for name in names} == before
    monkeypatch.setattr(canada_data, "_spec", lambda _: pytest.fail("runtime parsed CanadaSpec"))
    (bundle.directory / sub.REVIEW_FILE).unlink()
    assert bundle.index().ready
    for _ in range(5):
        assert bundle.index().ids("CA", "CA:ontario") == {"1", "3"}


@pytest.mark.parametrize("name", [sub.PAYLOAD_FILE, sub.MANIFEST_FILE])
def test_corrupt_or_missing_sidecar_only_disables_active_province(
    bundle: Bundle, name: str,
) -> None:
    (bundle.directory / name).write_bytes(b"corrupt")
    index = bundle.index()
    assert not index.ready and index.reason and "--rebuild" in index.reason
    index.validate("CA", None)
    with pytest.raises(sub.SubdivisionUnavailable):
        index.ids("CA", "CA:ontario")
    assert not index.site_response("3").ready


@pytest.mark.parametrize("name,limit", [(sub.PAYLOAD_FILE, "MAX_PAYLOAD_BYTES"),
                                      (sub.MANIFEST_FILE, "MAX_MANIFEST_BYTES")])
def test_oversized_local_lookup_is_bounded_and_keeps_basic_capability(
    bundle: Bundle, monkeypatch: pytest.MonkeyPatch, name: str, limit: str,
) -> None:
    monkeypatch.setattr(sub, limit, 4)
    index = bundle.index()
    assert not index.ready and "容量限制" in (index.reason or "")
    index.validate("CA", None)
    assert not index.facets("CA", 5).ready


@pytest.mark.parametrize("pin", ["REVIEW_SHA256", "PAYLOAD_SHA256", "SOURCE_REVIEW_SHA256",
                                "SOURCE_FACTS_SHA256"])
def test_unconfigured_independent_pin_cannot_enable_the_feature(
    bundle: Bundle, monkeypatch: pytest.MonkeyPatch, pin: str,
) -> None:
    monkeypatch.setattr(sub, pin, "")
    assert not bundle.index().ready
    with pytest.raises(sub.SubdivisionUnavailable):
        sub.rebuild_subdivisions(bundle.sites, CORPUS_VERSION, bundle.directory)


@pytest.mark.parametrize("field", ["label", "extra", "method", "country_roster"])
def test_resigning_review_and_payload_cannot_change_independently_checked_facts(
    bundle: Bundle, field: str,
) -> None:
    if field == "label":
        bundle.review["subdivisions"][0]["id"] = "CA:rewritten-label"
    elif field == "extra":
        bundle.review["extra_memberships"] = [extra_membership("5")]
    elif field == "method":
        bundle.review["review_method"] = "A replacement unapproved method"
    else:
        bundle.review["corpus_countries_sha256"] = "f" * 64
    bundle.pin_review()
    with pytest.raises(sub.SubdivisionUnavailable, match="审批"):
        sub.rebuild_subdivisions(bundle.sites, CORPUS_VERSION, bundle.directory)


def extra_membership(site_id: str) -> dict[str, Any]:
    row = {"PlaceId": "16360", "LocationDisplay": "Near Alert, Quebec"}
    ref = source("authority:fixture:16360").model_copy(update={
        "excerpt": row["LocationDisplay"],
    })
    return {
        "site_id": site_id, "subdivision_id": "CA:quebec", "source": ref.model_dump(),
        "artifact": {"filename": "source-place.html", "sha256": "c" * 64,
                     "uri": ref.uri},
        "field": "LocationDisplay", "raw_value": row["LocationDisplay"], "source_row": row,
        "source_row_sha256": sub._row_hash(row), "role": "explicit_place_location",
        "review_method": "Independent exact identity and original location field check.",
    }


def test_extra_page_field_is_bound_without_changing_the_existing_site(bundle: Bundle) -> None:
    old = bundle.sites[4].model_dump(mode="json")
    bundle.review["extra_memberships"] = [extra_membership("5")]
    bundle.pin_review(facts=True)
    bundle.compile()
    index = bundle.index()
    assert index.ids("CA", "CA:quebec") == {"auth:fixture:4", "5"}
    assert index.site_response("5").memberships[0].evidence[0].raw_value == "Near Alert, Quebec"
    assert bundle.sites[4].model_dump(mode="json") == old


def test_one_whole_object_can_have_two_explicit_source_provinces_without_counting_twice(
    bundle: Bundle,
) -> None:
    first = extra_membership("5")
    first["source_row"]["LocationDisplay"] = "Across Ontario and Quebec"
    first["raw_value"] = first["source_row"]["LocationDisplay"]
    first["source_row_sha256"] = sub._row_hash(first["source_row"])
    first["source"]["excerpt"] = first["raw_value"]
    second = copy.deepcopy(first)
    second["subdivision_id"] = "CA:ontario"
    bundle.review["extra_memberships"] = [first, second]
    bundle.pin_review(facts=True)
    bundle.compile()
    index = bundle.index()
    assert len(index.site_response("5").memberships) == 2
    assert index.facets("CA", 5).assigned == 5
    assert sum(row.count for row in index.facets("CA", 5).subdivisions) == 6
    assert index.ids("CA", "CA:ontario") == {"1", "3", "5"}
    assert index.ids("CA", "CA:quebec") == {"auth:fixture:4", "5"}


def test_reviewed_source_alias_keeps_original_literal_and_requires_its_external_fact_pin(
    bundle: Bundle,
) -> None:
    extra = extra_membership("5")
    extra["source_row"]["LocationDisplay"] = "Québec"
    extra.update(raw_value="Québec", source_label="Québec", role="source_declared_subdivision")
    extra["source_row_sha256"] = sub._row_hash(extra["source_row"])
    extra["source"]["excerpt"] = "Québec"
    bundle.review["extra_memberships"] = [extra]
    bundle.pin_review()
    with pytest.raises(sub.SubdivisionUnavailable, match="审批"):
        sub.rebuild_subdivisions(bundle.sites, CORPUS_VERSION, bundle.directory)
    bundle.pin_review(facts=True)
    bundle.compile()
    response = bundle.index().site_response("5")
    assert response.subdivisions[0].label == "Quebec"
    assert response.memberships[0].evidence[0].raw_value == "Québec"
    assert response.memberships[0].evidence[0].source_label == "Québec"


def test_source_feature_districts_keep_whole_identity_and_unassigned_objects(
    bundle: Bundle, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from archsearch import hong_kong_data

    monkeypatch.setattr(hong_kong_data, "SPEC_SHA256", "c" * 64)
    for identifier in ("auth:fixture:hk-whole", "auth:fixture:hk-no-feature"):
        bundle.sites.append(Site(
            id=identifier, title="Whole compound " + identifier, description="",
            names=[], types=["historic-site"], periods=[], repr_point=None,
            source_uri="https://example.org/whole", contributors=["Fixture"], period_evidence=[],
            source_kind="supplement", source_refs=[source()],
            geography=Geography(authority_id="supplement:" + identifier, countries=["HK"],
                                regions=["asia-pacific"], source=source(), point_count=0),
        ))
    bundle.review.update(sub.corpus_contract(bundle.sites))
    bundle.review["hong_kong_spec_sha256"] = hong_kong_data.SPEC_SHA256
    extras = []
    for oid, district in ((17, "Southern"), (18, "Wan Chai")):
        code = "HK:" + district.lower().replace(" ", "-")
        bundle.review["subdivisions"].append({"id": code, "country": "HK", "label": district})
        original = {"OBJECTID": oid, "DISTRICT": district, "DISTRIC_TC": "原始區名"}
        evidence = source("feature-district:" + str(oid)).model_copy(update={
            "uri": "https://example.org/source-feature", "excerpt": district,
        })
        extras.append({
            "site_id": "auth:fixture:hk-whole", "subdivision_id": code,
            "source": evidence.model_dump(mode="json"),
            "artifact": {"filename": "source-feature.json", "sha256": "d" * 64,
                         "uri": evidence.uri},
            "field": "DISTRICT", "raw_value": district, "source_row": original,
            "source_row_sha256": sub._row_hash(original), "role": "source_feature_district",
            "review_method": "Explicit reviewed feature-to-whole fixture, not geocoding.",
        })
    bundle.review["extra_memberships"] = extras
    before = [site.model_dump(mode="json") for site in bundle.sites]
    bundle.pin_review(facts=True)
    bundle.compile()
    index = bundle.index()
    assert index.ready
    assert index.ids("HK", "HK:southern") == index.ids("HK", "HK:wan-chai") == {
        "auth:fixture:hk-whole",
    }
    facets = index.facets("HK", 2)
    assert facets.assigned == 1 and facets.unassigned == 1
    assert sum(row.count for row in facets.subdivisions) == 2
    assert "来源要素地区" in facets.note and "不表示整体或全部几何" in facets.note
    assert index.ids("CA", "CA:ontario") == {"1", "3"}
    assert [site.model_dump(mode="json") for site in bundle.sites] == before
    assert index.site_response("auth:fixture:hk-no-feature").memberships == []
    assert "来源要素地区" in index.site_response("auth:fixture:hk-no-feature").note
    monkeypatch.setattr(hong_kong_data, "SPEC_SHA256", "e" * 64)
    assert not bundle.index().ready


@pytest.mark.parametrize("country,field,pin", [
    ("CA", "DISTRICT", "c" * 64), ("HK", "ADDRESS", "c" * 64),
    ("HK", "DISTRICT", None),
])
def test_source_feature_role_rejects_inferred_country_field_or_unbound_contract(
    bundle: Bundle, country: str, field: str, pin: str | None,
) -> None:
    extra = extra_membership("5")
    extra.update(subdivision_id=country + ":example", field=field, raw_value="Example",
                 source_row={field: "Example"}, role="source_feature_district")
    extra["source_row_sha256"] = sub._row_hash(extra["source_row"])
    bundle.review["extra_memberships"] = [extra]
    bundle.review["hong_kong_spec_sha256"] = pin
    bundle.review["subdivisions"].append({"id": country + ":example", "country": country,
                                         "label": "Example"})
    if country == "HK":
        bundle.sites[-2] = bundle.sites[-2].model_copy(update={"geography": Geography(
            countries=["HK"], regions=["asia-pacific"], source=source(),
        )})
    bundle.review.update(sub.corpus_contract(bundle.sites))
    with pytest.raises(sub.SubdivisionUnavailable, match="香港"):
        bundle.payload()


@pytest.mark.parametrize("mutation", ["raw", "row_hash", "path", "uri", "label", "site"])
def test_extra_field_or_country_cannot_be_forged(bundle: Bundle, mutation: str) -> None:
    extra = extra_membership("5")
    if mutation == "raw":
        extra["raw_value"] = "Quebec"
    elif mutation == "row_hash":
        extra["source_row_sha256"] = "f" * 64
    elif mutation == "path":
        extra["artifact"]["filename"] = "../outside.html"
    elif mutation == "uri":
        extra["artifact"]["uri"] = "https://example.org/another-object"
    elif mutation == "label":
        extra["subdivision_id"] = "CA:ontario"
    else:
        extra["site_id"] = "6"
    bundle.review["extra_memberships"] = [extra]
    with pytest.raises((ValidationError, sub.SubdivisionUnavailable)):
        bundle.pin_review(facts=True)
        bundle.compile()


@pytest.mark.parametrize("mutation", ["ids", "country", "version", "duplicate", "unknown"])
def test_compact_lookup_cannot_apply_to_a_different_corpus(bundle: Bundle, mutation: str) -> None:
    sites = copy.copy(bundle.sites)
    version = CORPUS_VERSION
    payload = bundle.payload()
    if mutation == "ids":
        sites[0] = sites[0].model_copy(update={"id": "new-id"})
    elif mutation == "country":
        sites[0] = sites[0].model_copy(update={"geography": Geography(
            countries=["FR"], regions=["europe-north-america"], source=source(),
        )})
    elif mutation == "version":
        version = "global-other"
    elif mutation == "duplicate":
        payload = payload.model_copy(update={"memberships": payload.memberships * 2})
    else:
        first = payload.memberships[0].model_copy(update={"site_id": "missing"})
        payload = payload.model_copy(update={"memberships": [first, *payload.memberships[1:]]})
    assert not sub.SubdivisionIndex(sites, version, payload=payload).ready


class FakeSemantic:
    def __init__(self, sites: list[Site]) -> None:
        self.sites = sites
        self.ready = True
        self.reason = None
        self.revision = MODEL_REVISION

    def scores(self, query: str) -> Any:
        return np.array([1, 2, 90, 80, 100, 200], dtype=np.float32)


def test_subdivision_is_applied_before_semantic_top_k_and_bm25_ranking(bundle: Bundle) -> None:
    engine = SearchEngine(bundle.sites, cast(SemanticIndex, FakeSemantic(bundle.sites)),
                          bundle.index())
    semantic, total = engine.search(SearchRequest(query="harbor", mode="semantic", limit=1,
                                                  country="CA", subdivision="CA:ontario"))
    assert total == 2 and semantic[0].site.id == "1"
    lexical, total = engine.search(SearchRequest(query="harbor", mode="bm25", limit=1,
                                                 country="CA", subdivision="CA:ontario"))
    assert total == 1 and lexical[0].site.id == "3"
    all_hits, total = engine.search(SearchRequest(query="harbor", mode="semantic", limit=6,
                                                 country="CA"))
    assert total == 5 and all_hits[0].site.id == "5"


def test_province_selection_retains_every_original_source_point_and_bbox_rule(
    bundle: Bundle,
) -> None:
    original = ((-179.0, 0.0), (179.0, 0.0), (-179.0, 0.0))
    locations = WorldLocations(
        version="source-fixture-v1", points={"3": original},
        records={"3": tuple(SourceLocation(i, point, "Original " + str(i), str(i))
                            for i, point in enumerate(original))},
        source={"dataset_id": "fixture", "name": "Original source points", "version": "v1",
                "uri": "https://example.org/points", "license": "CC0", "license_uri":
                "https://example.org/rights", "sha256": "a" * 64}, counts={},
    )
    catalogue = CatalogueIndex(bundle.sites, CORPUS_VERSION,
        CoverageRegistry(countries={"CA": "Canada", "FR": "France"}, regions={},
                         spatial=locations), bundle.index())
    points = catalogue.catalogue("CA", subdivision="CA:ontario")
    assert points.total == 2 and points.subdivision_version == sub.VERSION
    assert next(row.source_points for row in points.points if row.id == "3") == list(original)
    bounded = catalogue.page(country="CA", subdivision="CA:ontario",
        bbox=SpatialBounds.from_csv("178,-1,-178,1"))
    assert bounded.total == 1 and bounded.sites[0].id == "3"
    assert catalogue.page(country="CA", subdivision="CA:quebec").total == 1
    assert catalogue.page(country="CA", subdivision="CA:quebec",
                          bbox=SpatialBounds.from_csv("-180,-90,180,90")).total == 0


def test_api_facets_search_page_and_catalogue_echo_the_same_supported_scope(bundle: Bundle) -> None:
    with TestClient(create_app(sites=bundle.sites,
            semantic=cast(SemanticIndex, FakeSemantic(bundle.sites)), home=bundle.directory,
            subdivisions=bundle.index())) as client:
        facets = client.get("/api/subdivisions", params={"country": "CA"}).json()
        assert facets["total"] == 5 and facets["assigned"] == 4 and facets["unassigned"] == 1
        assert facets["subdivision_version"] == sub.VERSION
        params = {"country": "CA", "subdivision": "CA:ontario"}
        for path in ["/api/sites", "/api/catalogue"]:
            body = client.get(path, params=params).json()
            assert body["total"] == 2 and body["subdivision"] == "CA:ontario"
            assert body["subdivision_version"] == sub.VERSION
        searched = client.post("/api/search", json={"query": "harbor", "mode": "semantic",
                                                   "limit": 1, **params}).json()
        assert searched["results"][0]["site"]["id"] == "1"
        assert searched["subdivision"] == "CA:ontario"
        assert searched["subdivision_version"] == sub.VERSION
        assert client.get("/api/sites/5/subdivisions").json()["memberships"] == []
        assert client.get("/api/sites/missing/subdivisions").status_code == 404
        assert client.get("/api/sites/3").json() == bundle.sites[0].model_dump(mode="json")
        assert client.get("/api/subdivisions", params={"country": "FR"}).json()[
            "supported"
        ] is False
        assert client.get("/api/status").json()["subdivisions"] == {
            "ready": True, "reason": None, "version": sub.VERSION,
        }


@pytest.mark.parametrize("params", [
    {"subdivision": "CA:ontario"}, {"country": "FR", "subdivision": "CA:ontario"},
    {"country": "CA", "subdivision": "CA:not-in-source"},
    {"country": "CA", "subdivision": "CA:Ontario"},
])
def test_unknown_or_cross_country_scope_returns422(bundle: Bundle, params: dict[str, str]) -> None:
    with TestClient(create_app(sites=bundle.sites, home=bundle.directory,
                              subdivisions=bundle.index())) as client:
        for path in ["/api/sites", "/api/catalogue"]:
            assert client.get(path, params=params).status_code == 422
        assert client.post("/api/search", json={"query": "harbor", **params}).status_code == 422


def test_duplicate_get_filters_are_rejected(bundle: Bundle) -> None:
    with TestClient(create_app(sites=bundle.sites, home=bundle.directory,
                              subdivisions=bundle.index())) as client:
        assert client.get("/api/subdivisions?country=CA&country=FR").status_code == 422
        for path in ["/api/sites", "/api/catalogue"]:
            assert client.get(path + "?country=CA&subdivision=CA:ontario&subdivision=CA:quebec"
                              ).status_code == 422


def test_search_schema_refuses_unversioned_invented_filter_fields(bundle: Bundle) -> None:
    with TestClient(create_app(sites=bundle.sites, home=bundle.directory,
                              subdivisions=bundle.index())) as client:
        assert client.post("/api/search", json={"query": "harbor", "country": "CA",
            "subdivision": "CA:ontario", "subdivision_version": "invented"
        }).status_code == 422


def test_registry_failure_preserves_basic_search_and_browsing_and_reports503_only_for_active(
    bundle: Bundle,
) -> None:
    (bundle.directory / sub.PAYLOAD_FILE).unlink()
    index = bundle.index()
    with TestClient(create_app(sites=bundle.sites, home=bundle.directory,
                              subdivisions=index)) as client:
        assert client.get("/api/status").json()["subdivisions"]["ready"] is False
        assert client.get("/api/sites", params={"country": "CA"}).json()["total"] == 5
        assert client.get("/api/catalogue", params={"country": "CA"}).json()["total"] == 5
        assert client.post("/api/search", json={"query": "harbor", "mode": "bm25",
                                                "country": "CA"}).status_code == 200
        params = {"country": "CA", "subdivision": "CA:ontario"}
        for path in ["/api/sites", "/api/catalogue"]:
            assert client.get(path, params=params).status_code == 503
        assert client.post("/api/search", json={"query": "harbor", "mode": "bm25",
                                                **params}).status_code == 503
        assert client.get("/api/sites/3/subdivisions").json()["ready"] is False
        assert "--rebuild" in client.get("/api/subdivisions?country=CA").json()["reason"]


def test_deep_manifest_degrades_province_without_preventing_default_app_startup(
    bundle: Bundle, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (bundle.directory / sub.MANIFEST_FILE).write_bytes(b"[" * 2000 + b"0" + b"]" * 2000)
    read_bounded = sub._read_bounded
    monkeypatch.setattr(sub, "_read_bounded", lambda path, limit: read_bounded(
        bundle.directory / path.name, limit,
    ))
    with TestClient(create_app(sites=bundle.sites, home=bundle.directory)) as client:
        status = client.get("/api/status").json()["subdivisions"]
        assert status["ready"] is False and "--rebuild" in status["reason"]
        assert client.get("/api/sites", params={"country": "CA"}).json()["total"] == 5
        assert client.get("/api/catalogue", params={"country": "CA"}).json()["total"] == 5
        searched = client.post("/api/search", json={"query": "harbor", "mode": "bm25",
                                                   "country": "CA"})
        assert searched.status_code == 200 and searched.json()["results"]
        active = {"country": "CA", "subdivision": "CA:ontario"}
        for path in ["/api/sites", "/api/catalogue"]:
            assert client.get(path, params=active).status_code == 503
        assert client.post("/api/search", json={"query": "harbor", "mode": "bm25",
                                                **active}).status_code == 503
