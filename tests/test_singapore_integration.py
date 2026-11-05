"""Published NHB cultural wholes retain source scope, references and honest map state."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archsearch import singapore_data as cohort
from archsearch.api import create_app
from archsearch.corpus import build_document, load_pre_minas_corpus, load_pre_singapore_corpus
from archsearch.evaluation import evaluate_corpus, load_queries
from archsearch.supplement_data import base_contract


def test_qualified_singapore_wholes_preserve_every_original3116_field() -> None:
    before, current = load_pre_singapore_corpus(), load_pre_minas_corpus()
    assert base_contract(before) == {
        "base_count": 3116,
        "base_ids_sha256": "6b4ee623a48910f8b8332a81cdd6aea746c50438da60d7c3c95c1d60c3cd5b93",
        "base_sites_sha256": "0167b6e82251620d644c22adb54abc6aa3b9b3afeed43168fd15c9fae3cb38a7",
    }
    assert len(current) == len({site.id for site in current}) == 3193
    assert current[:3116] == before
    assert [build_document(site) for site in current[:3116]] == [
        build_document(site) for site in before
    ]
    spec = cohort._spec(cohort.DATA_DIR)
    assert len(spec.roster.features) == len(spec.review.records) == 77
    assert {row.disposition for row in spec.review.decisions} == {"include"}
    originals = {
        cohort.project_id(row.source_row.hyperlink): row for row in spec.roster.features
    }
    decisions = {row.whole.project_id: row for row in spec.review.decisions}
    for site in current[3116:]:
        original = originals[site.id]
        assert site.title == original.source_row.name
        assert site.description == original.source_row.description and site.description_zh == ""
        assert site.repr_point == original.geometry.coordinates and site.location_precision is None
        assert not site.chronology.phases and site.chronology.status == "not_reviewed"
        assert site.geography and site.geography.countries == ["SG"]
        assert site.geography.point_count == 1
        assert decisions[site.id].whole.supported_scope_literal in site.details
    raffles = next(row for row in spec.review.decisions if row.whole.source_object_id == 1737)
    assert raffles.target_id != "whc:1483" and raffles.disposition == "include"
    assert next(site for site in current if site.id == "whc:1483") == next(
        site for site in before if site.id == "whc:1483"
    )


def test_shipped_facts_rebuild_twice_without_source_cache(tmp_path: Path) -> None:
    for name in (cohort.ROSTER_FILE, cohort.SPEC_FILE):
        (tmp_path / name).write_bytes((cohort.DATA_DIR / name).read_bytes())
    expected = {name: (cohort.DATA_DIR / name).read_bytes()
                for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)}
    base = load_pre_singapore_corpus()
    for _ in range(2):
        manifest = cohort.rebuild_singapore(tmp_path, base=base)
        assert manifest["counts"] == {
            "base": 3116, "source_features": 77, "added": 77, "total": 3193,
            "decisions": {"include": 77}, "adopted_reference_points": 77,
            "new_historical_phases": 0,
        }
        assert {name: (tmp_path / name).read_bytes() for name in expected} == expected


@pytest.fixture(scope="module")
def singapore_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    with TestClient(create_app(home=tmp_path_factory.mktemp("sg-offline-api"))) as client:
        yield client


def test_country_catalogue_preserves_original_points_without_inventing_districts(
    singapore_client: TestClient,
) -> None:
    client = singapore_client
    page = client.get("/api/sites?country=SG&limit=100").json()
    assert page["corpus_version"] == "global-v16" and page["total"] == len(page["sites"]) == 78
    assert client.get("/api/sites", params={
        "country": "SG", "bbox": "-180,-90,180,90",
    }).json()["total"] == 78
    assert sum(site["id"].startswith("auth:sg-nhb:") for site in page["sites"]) == 77
    districts = client.get("/api/subdivisions?country=SG").json()
    assert districts["ready"] and not districts["supported"]
    assert districts["assigned"] == 0 and districts["unassigned"] == 78
    assert districts["subdivisions"] == []
    assert client.get("/api/sites?country=SG&subdivision=SG:central").status_code == 422
    assert client.get("/api/subdivisions?country=CA").json()["assigned"] == 992
    assert client.get("/api/subdivisions?country=HK").json()["assigned"] == 138
    coverage = client.get("/api/coverage").json()
    assert coverage["total"] == 3326 and len(coverage["countries"]) == 203
    assert coverage["locations"] == {"mapped": 2940, "polar": 3, "unknown": 383}
    assert coverage["chronology"] == {
        "reviewed": 149, "insufficient": 451, "not_reviewed": 2726,
    }


def test_source_entry_scope_and_spatial_provenance_remain_with_the_selected_whole(
    singapore_client: TestClient,
) -> None:
    client = singapore_client
    spec = cohort._spec(cohort.DATA_DIR)
    decisions = {row.whole.source_object_id: row for row in spec.review.decisions}
    for source_id in (1692, 1736):
        decision = decisions[source_id]
        identifier = decision.whole.project_id
        site = client.get(f"/api/sites/{identifier}").json()
        assert site["source_uri"] == decision.whole.primary_source_uri
        assert site["source_uri"] != decision.whole.business_uri
        assert identifier == cohort.project_id(decision.whole.business_uri)
        assert decision.whole.supported_scope_literal in site["details"]
        assert any(source["uri"] == site["source_uri"] for source in site["source_refs"])
        locations = client.get(f"/api/sites/{identifier}/locations").json()
        assert locations["representative_point"] == site["repr_point"]
        assert locations["source_points"] == [] and locations["source"] is None
        areas = client.get(f"/api/sites/{identifier}/areas").json()
        assert areas["ready"] and areas["features"] == []
    bridges = [row for row in spec.review.decisions if "Singapore River Bridges" in row.whole.title]
    assert len(bridges) == 1 and bridges[0].whole.scope_kind == "composite_whole"
    assert all(bridge in bridges[0].whole.supported_scope_literal
               for bridge in ("Cavenagh", "Anderson", "Elgin"))


def test_original_names_remain_searchable_without_model_or_external_network(
    singapore_client: TestClient,
) -> None:
    client = singapore_client
    response = client.post("/api/search", json={
        "query": "Former Keng Teck Whay Building", "country": "SG", "mode": "bm25",
    })
    assert response.status_code == 200
    assert response.json()["results"][0]["site"]["title"] == "Former Keng Teck Whay Building"
    same_name = client.post("/api/search", json={
        "query": "Former Admiralty House", "country": "SG", "mode": "bm25",
    }).json()
    assert same_name["results"][0]["site"]["title"] == "Former Admiralty House"
    assert all(hit["site"]["geography"]["countries"] == ["SG"]
               for hit in same_name["results"])
    missing = client.post("/api/search", json={
        "query": "新加坡的历史宗教建筑", "country": "SG", "mode": "semantic",
    })
    assert missing.status_code == 503


def test_twenty_paired_diagnostics_do_not_create_relevance_judgments(tmp_path: Path) -> None:
    queries = cohort.DATA_DIR / "queries-singapore.json"
    assert [pair.id for pair in load_queries(queries)] == [
        f"sg{number:02d}" for number in range(1, 21)
    ]
    report = evaluate_corpus(tmp_path / "no-model", tmp_path / "sg-rankings.json", queries=queries)
    assert report["corpus_count"] == 3326 and report["metrics"] is None
    assert not report["qrels"]["confirmed"] and not report["runs_complete"]
