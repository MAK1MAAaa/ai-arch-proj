"""A named-place coverage repair keeps source identity, event and location distinct."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archsearch import target_data as data
from archsearch.api import create_app
from archsearch.corpus import CORPUS_VERSION, build_document, load_corpus, load_pre_targets_corpus
from archsearch.domain import Site
from archsearch.index import SemanticIndex
from archsearch.search import SearchEngine, SearchRequest
from archsearch.subdivisions import SubdivisionIndex
from archsearch.supplement_data import base_contract

TARGET = "auth:gb-shakespeare:grave"


@pytest.fixture(scope="module")
def current() -> list[Site]:
    return load_corpus()


def test_append_preserves_all_original3897_records_and_documents(current: list[Site]) -> None:
    before = load_pre_targets_corpus()
    assert base_contract(before) == {
        "base_count": 3897,
        "base_ids_sha256": "08378c5c096994146d871acf31e4b8b78a94bff8e3c98814555220de09d02324",
        "base_sites_sha256": "4259502123b0d9a3bbd405df1e3ff85caa0f03c8ea4b227a704ae49c9ae30be8",
    }
    assert current[:-1] == before
    assert [build_document(site) for site in current[:-1]] == [
        build_document(site) for site in before
    ]
    assert len(current) == len({site.id for site in current}) == 3898
    assert CORPUS_VERSION == "global-v19" and current[-1].id == TARGET


def test_burial_event_and_church_reference_point_retain_their_distinct_scope(
    current: list[Site],
) -> None:
    site = current[-1]
    assert site.repr_point == (-1.7074, 52.1864) and site.location_precision is None
    assert site.geography and site.geography.countries == ["GB"]
    assert site.chronology.status == "reviewed" and len(site.chronology.phases) == 1
    phase = site.chronology.phases[0]
    assert phase.id == site.chronology.default_phase_id == "burial-1616"
    assert phase.kind == "other" and phase.precision == "exact_year"
    assert phase.start_year == phase.end_year == 1616
    assert any("April 25, 1616" in ref.excerpt for ref in phase.sources)
    assert "church" in site.details.lower() and "not" in site.details.lower()
    spec = data.TargetSpec.model_validate_json((data.DATA_DIR / data.SPEC_FILE).read_bytes())
    coordinate = spec.records[0].coordinate
    assert coordinate.statement_id == "Q472082$AD3A3ECC-2FA3-4930-9882-CBAA797D3CE4"
    assert coordinate.precision == 1e-6 and "not" in coordinate.note
    assert not site.periods and not site.period_evidence
    assert "not expert or human confirmation" in site.chronology.method


def test_compact_review_rebuilds_without_model_or_source_page_cache(
    current: list[Site], tmp_path: Path,
) -> None:
    (tmp_path / data.SPEC_FILE).write_bytes((data.DATA_DIR / data.SPEC_FILE).read_bytes())
    expected = {name: (data.DATA_DIR / name).read_bytes()
                for name in (data.SITES_FILE, data.MANIFEST_FILE)}
    for _ in range(2):
        manifest = data.rebuild_targets(current[:-1], tmp_path)
        assert manifest["counts"] == {"added": 1, "total": 3898}
        assert {name: (tmp_path / name).read_bytes() for name in expected} == expected
        assert data.load_targets(current[:-1], tmp_path) == current


@pytest.mark.parametrize("name", [data.SPEC_FILE, data.SITES_FILE, data.MANIFEST_FILE])
def test_changed_review_derivative_or_manifest_fails_closed(
    current: list[Site], tmp_path: Path, name: str,
) -> None:
    for filename in (data.SPEC_FILE, data.SITES_FILE, data.MANIFEST_FILE):
        (tmp_path / filename).write_bytes((data.DATA_DIR / filename).read_bytes())
    (tmp_path / name).write_text("{}", encoding="utf-8")
    with pytest.raises(data.TargetDataError):
        data.load_targets(current[:-1], tmp_path)


def test_source_point_or_chronology_cannot_silently_change_even_if_json_is_valid(
    current: list[Site], tmp_path: Path,
) -> None:
    raw = (data.DATA_DIR / data.SPEC_FILE).read_bytes()
    spec = json.loads(raw)
    spec["records"][0]["site"]["repr_point"] = [0, 0]
    spec["records"][0]["site"]["chronology"]["phases"][0]["kind"] = "construction"
    assert hashlib.sha256(data._bytes(spec)).hexdigest() != data.SPEC_SHA256
    (tmp_path / data.SPEC_FILE).write_bytes(data._bytes(spec))
    with pytest.raises(data.TargetDataError, match="independent checksum"):
        data.rebuild_targets(current[:-1], tmp_path)


@pytest.mark.parametrize("query", [
    "寻找莎士比亚的坟墓", "莎士比亚墓在哪里", "William Shakespeare's grave",
    "Shakespeare burial Holy Trinity Stratford-upon-Avon",
])
def test_named_queries_retrieve_verified_grave_without_llm_or_special_routing(
    current: list[Site], tmp_path: Path, query: str,
) -> None:
    engine = SearchEngine(current, SemanticIndex(current, tmp_path))
    hits, total = engine.search(SearchRequest(query=query, mode="bm25"))
    assert total and hits[0].site.id == TARGET
    assert hits[0].score > 0 and hits[0].matched_fields


def test_named_place_api_has_sources_phase_and_no_inferred_registered_area(
    current: list[Site], tmp_path: Path,
) -> None:
    with TestClient(create_app(home=tmp_path)) as client:
        result = client.post("/api/search", json={
            "query": "寻找莎士比亚的坟墓", "mode": "bm25",
        }).json()
        assert result["corpus_version"] == CORPUS_VERSION
        assert result["results"][0]["site"]["id"] == TARGET
        detail = client.get("/api/sites/" + TARGET).json()
        assert len(detail["source_refs"]) == 3
        assert detail["chronology"]["default_phase_id"] == "burial-1616"
        assert not client.get("/api/sites/" + TARGET + "/areas").json()["features"]
        assert client.get("/api/subdivisions?country=GB").json()["ready"]
    index = SubdivisionIndex(current, CORPUS_VERSION)
    assert index.ready, index.reason
    assert not index.site_response(TARGET).memberships
