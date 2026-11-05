"""Frozen Iepha-MG scopes remain readable, traceable and honestly unlocated."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archsearch import minas_data as cohort
from archsearch.api import create_app
from archsearch.corpus import build_document, load_pre_merimee_corpus, load_pre_minas_corpus
from archsearch.evaluation import evaluate_corpus, load_queries
from archsearch.supplement_data import base_contract


def test_original3193_contract_and_source_scope_granularity_are_preserved() -> None:
    before, current = load_pre_minas_corpus(), load_pre_merimee_corpus()
    assert base_contract(before) == {
        "base_count": 3193,
        "base_ids_sha256": "1a989372ce3ed2bb1ed3ee051ca03e60ec1f07165ab210cd4b641f8c49a5b424",
        "base_sites_sha256": "6119f5b66f33e88a885b674c05ba92cedeeba1a38a742f11a3883510d1b7b887",
    }
    assert len(current) == len({site.id for site in current}) == 3326
    assert current[:3193] == before
    assert [build_document(site) for site in current[:3193]] == [
        build_document(site) for site in before
    ]
    spec = cohort._spec(cohort.DATA_DIR)
    assert len(spec.roster.records) == 153 and len(spec.review.decisions) == 147
    assert sum(row.disposition == "include" for row in spec.review.decisions) == 133
    assert sum(row.disposition == "hold" for row in spec.review.decisions) == 12
    assert sum(row.disposition == "exclude" for row in spec.review.decisions) == 2
    approved = {row.target_id: row for row in spec.review.decisions
                if row.disposition == "include"}
    originals = {row.record_index: row.raw_fields for row in spec.roster.records}
    for site in current[3193:]:
        decision = approved[site.id]
        assert site.title == decision.supported_scope_literal and not site.names
        assert site.repr_point is site.location_precision is None
        assert not site.chronology.phases and site.chronology.status == "not_reviewed"
        assert site.geography and site.geography.countries == ["BR"]
        assert site.geography.point_count == 0
        for index in decision.source_record_indices:
            assert originals[index].denominacao in site.details
            assert originals[index].denominacao_completa in site.details
        assert "independent_review" not in build_document(site)
    same_process = [row for row in spec.review.decisions
                    if originals[row.source_record_indices[0]].processo_ano == "PTE058/1984"]
    assert len(same_process) == 2 and same_process[0].scope_key != same_process[1].scope_key


def test_shipped_review_rebuilds_twice_without_raw_pages_or_csv(tmp_path: Path) -> None:
    for name in (cohort.ROSTER_FILE, cohort.SPEC_FILE):
        (tmp_path / name).write_bytes((cohort.DATA_DIR / name).read_bytes())
    expected = {name: (cohort.DATA_DIR / name).read_bytes()
                for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)}
    for _ in range(2):
        manifest = cohort.rebuild_minas(tmp_path, base=load_pre_minas_corpus())
        assert manifest["counts"] == {
            "base": 3193, "source_records": 153, "source_scopes": 147,
            "added": 133, "total": 3326,
            "decisions": {"exclude": 2, "hold": 12, "include": 133},
            "adopted_reference_points": 0, "new_historical_phases": 0,
        }
        assert {name: (tmp_path / name).read_bytes() for name in expected} == expected


@pytest.fixture(scope="module")
def minas_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    with TestClient(create_app(home=tmp_path_factory.mktemp("minas-offline"))) as client:
        yield client


def test_brazil_directory_paginates_and_unknown_points_do_not_match_bbox(
    minas_client: TestClient,
) -> None:
    client = minas_client
    pages = [client.get(f"/api/sites?country=BR&limit=50&offset={offset}").json()
             for offset in (0, 50, 100, 150)]
    assert [len(page["sites"]) for page in pages] == [50, 50, 50, 4]
    sites = [site for page in pages for site in page["sites"]]
    assert len({site["id"] for site in sites}) == 154
    new = {site["id"] for site in sites if site["id"].startswith("auth:br-iepha-mg:")}
    assert len(new) == 133
    assert all(site["repr_point"] is None for site in sites if site["id"] in new)
    spatial = client.get("/api/sites?country=BR&bbox=-180,-90,180,90&limit=100").json()
    assert not new.intersection(site["id"] for site in spatial["sites"])
    assert spatial["total"] == sum(site["repr_point"] is not None for site in sites)


def test_original_municipality_facets_preserve_old_country_memberships(
    minas_client: TestClient,
) -> None:
    client = minas_client
    districts = client.get("/api/subdivisions?country=BR").json()
    assert districts["ready"] and districts["supported"]
    assert districts["subdivision_version"] == "source-subdivisions-v7"
    assert (districts["total"], districts["assigned"], districts["unassigned"]) == (154, 133, 21)
    assert len(districts["subdivisions"]) == 67
    compound = next(row for row in districts["subdivisions"]
                    if row["label"] == "Belo Horizonte, Nova Lima e Sabará")
    result = client.get("/api/sites", params={
        "country": "BR", "subdivision": compound["id"],
    }).json()
    assert result["total"] == 1 and result["sites"][0]["title"] == "Serra do Curral"
    assert result["sites"][0]["repr_point"] is None
    assert "不表示整体" in districts["note"]
    assert client.get("/api/sites?country=CA&subdivision=" + compound["id"]).status_code == 422
    assert client.get("/api/subdivisions?country=CA").json()["assigned"] == 992
    assert client.get("/api/subdivisions?country=HK").json()["assigned"] == 138
    assert not client.get("/api/subdivisions?country=SG").json()["supported"]


def test_original_portuguese_fields_remain_searchable_without_model(
    minas_client: TestClient,
) -> None:
    response = minas_client.post("/api/search", json={
        "query": "Prédio da antiga Cadeia Pública de Barbacena", "country": "BR", "mode": "bm25",
    })
    assert response.status_code == 200
    hit = response.json()["results"][0]["site"]
    assert hit["title"] == "Prédio da antiga Cadeia Pública de Barbacena"
    assert hit["repr_point"] is None and hit["source_uri"] == cohort.DATASET_URI
    assert minas_client.get(f"/api/sites/{hit['id']}/locations").json()["source_points"] == []
    assert minas_client.get(f"/api/sites/{hit['id']}/areas").json()["features"] == []
    assert minas_client.post("/api/search", json={
        "query": "巴西的历史建筑", "country": "BR", "mode": "semantic",
    }).status_code == 503


def test_paired_diagnostics_leave_unconfirmed_relevance_metrics_null(tmp_path: Path) -> None:
    queries = cohort.DATA_DIR / "queries-minas.json"
    assert [pair.id for pair in load_queries(queries)] == [f"mg{number:02d}"
                                                         for number in range(1, 21)]
    result = evaluate_corpus(tmp_path / "missing-model", tmp_path / "rankings.json",
                             queries=queries)
    assert result["corpus_count"] == 3898 and result["metrics"] is None
    assert not result["qrels"]["confirmed"] and not result["runs_complete"]
