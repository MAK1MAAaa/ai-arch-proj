"""Frozen overseas notice scopes, provider points and literal commune browsing."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archsearch import merimee_data as cohort
from archsearch.api import create_app
from archsearch.corpus import (
    CORPUS_VERSION,
    build_document,
    load_pre_merimee_corpus,
    load_pre_merimee_extension_corpus,
)
from archsearch.evaluation import evaluate_corpus, load_queries
from archsearch.supplement_data import base_contract


def test_original3326_sites_order_and_search_documents_remain_unchanged() -> None:
    before, current = load_pre_merimee_corpus(), load_pre_merimee_extension_corpus()
    assert base_contract(before) == {
        "base_count": 3326,
        "base_ids_sha256": "cec6ca8bb1c503047991ea39d25a4b8bd28fad1e1e7453308b6c18b7cc7491ea",
        "base_sites_sha256": "d48d23129b73848c58034f377d24b87a5ddeeffcfd0a823796aee70fa306e416",
    }
    assert len(current) == len({s.id for s in current}) == 3775
    assert current[:3326] == before
    documents = [[s.id, build_document(s)] for s in current[:3326]]
    assert hashlib.sha256(json.dumps(documents, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest() == (
        "5a4c5fa3299aeabbb900d2330029edc8518e0f5afb692d7cbf85963528373317"
    )
    additions = current[3326:]
    assert Counter(s.geography.countries[0] for s in additions if s.geography) == {
        "GP": 112, "BL": 7, "MF": 1, "MQ": 124, "RE": 205,
    }
    assert sum(s.repr_point is not None for s in additions) == 442
    for site in additions:
        assert not site.names and not site.description_zh
        assert not site.chronology.phases and site.chronology.status == "not_reviewed"
        assert site.location_precision is None
        assert site.details.startswith("Original source fields (French):\n")
        original = json.loads(site.details.split("\n", 1)[1])
        assert len(original["source_record"]) == 78
        assert original["source_record"]["Reference"] == site.id.rpartition(":")[2]
        assert original["source_record"]["Titre_editorial_de_la_notice"] == site.title
        assert "independent_review" not in build_document(site)


def test_frozen449_rebuilds_offline_twice_without_original_pages_or_csv(tmp_path: Path) -> None:
    for name in (cohort.ROSTER_FILE, cohort.SPEC_FILE):
        (tmp_path / name).write_bytes((cohort.DATA_DIR / name).read_bytes())
    expected = {name: (cohort.DATA_DIR / name).read_bytes()
                for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)}
    base = load_pre_merimee_corpus()
    for _ in range(2):
        manifest = cohort.rebuild_merimee(tmp_path, base=base)
        assert manifest["counts"]["added"] == 449
        assert manifest["counts"]["adopted_reference_points"] == 442
        assert manifest["counts"]["new_historical_phases"] == 0
        assert {name: (tmp_path / name).read_bytes() for name in expected} == expected


@pytest.fixture(scope="module")
def merimee_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    with TestClient(create_app(home=tmp_path_factory.mktemp("merimee-offline"))) as client:
        yield client


def test_statistical_area_mapping_preserves_old_source_region_and_components(
    merimee_client: TestClient,
) -> None:
    client = merimee_client
    expected = {"GP": 112, "BL": 7, "MF": 1, "MQ": 124, "RE": 205}
    for area, count in expected.items():
        pages = [client.get("/api/sites", params={"country": area, "limit": 50,
                                                 "offset": n}).json()
                 for n in range(0, count, 50)]
        assert all(page["total"] == count for page in pages)
        assert len({site["id"] for page in pages for site in page["sites"]}) == count
    barth = client.get("/api/sites/auth:fr-merimee:PA97100006").json()
    raw = json.loads(barth["details"].split("\n", 1)[1])["source_record"]
    assert raw["Region"] == "Guadeloupe" and raw["COG_Insee_lors_de_la_protection"] == "97701"
    assert barth["geography"]["countries"] == ["BL"]
    assert "FR" not in barth["geography"]["countries"]
    assert client.get("/api/sites/auth:fr-merimee:PA97400023").status_code == 404
    assert client.get("/api/sites/auth:fr-merimee:PA97400026").status_code == 200
    coverage = client.get("/api/coverage").json()
    assert coverage["total"] == 3898 and len(coverage["countries"]) == 211
    assert coverage["locations"] == {"mapped": 3505, "polar": 3, "unknown": 390}


def test_source_wgs84_axis_and_missing_points_do_not_become_guessed_centres(
    merimee_client: TestClient,
) -> None:
    client = merimee_client
    site = client.get("/api/sites/auth:fr-merimee:PA00105850").json()
    assert site["repr_point"] == [-61.722949450198406, 15.9883992141981]
    assert site["location_precision"] is None
    unknown = client.get("/api/sites/auth:fr-merimee:PA97100016").json()
    assert unknown["repr_point"] is None and unknown["geography"]["point_count"] == 0
    page = client.get("/api/sites", params={
        "country": "GP", "bbox": "-180,-90,180,90", "limit": 100,
    }).json()
    assert "auth:fr-merimee:PA97100016" not in {s["id"] for s in page["sites"]}
    assert page["total"] == 109
    assert not client.get("/api/sites/auth:fr-merimee:PA00105850/areas").json()["features"]


def test_commune_browse_retains_compound_values_and_existing_source_memberships(
    merimee_client: TestClient,
) -> None:
    client = merimee_client
    for area, count in {"GP": 112, "BL": 7, "MF": 1, "MQ": 124, "RE": 205}.items():
        facets = client.get("/api/subdivisions", params={"country": area}).json()
        assert facets["ready"] and facets["supported"]
        assert facets["subdivision_version"] == "source-subdivisions-v7"
        assert facets["assigned"] == count and facets["unassigned"] == 0
        assert "多地值不拆分" in facets["note"]
    detail = client.get("/api/sites/auth:fr-merimee:PA97400026/subdivisions").json()
    assert len(detail["subdivisions"]) == 1
    literal = detail["memberships"][0]["evidence"][0]["raw_value"]
    assert ";" in literal and detail["subdivisions"][0]["label"] == literal
    for area, count in {"CA": 992, "HK": 138, "BR": 133}.items():
        assert client.get("/api/subdivisions", params={"country": area}).json()["assigned"] == count
    assert not client.get("/api/subdivisions?country=SG").json()["supported"]


def test_original_name_bm25_works_without_model_and_evaluation_stays_unscored(
    merimee_client: TestClient, tmp_path: Path,
) -> None:
    client = merimee_client
    result = client.post("/api/search", json={
        "query": "Clocher suédois de Gustavia", "country": "BL", "mode": "bm25",
    }).json()
    assert result["corpus_version"] == CORPUS_VERSION
    assert result["results"][0]["site"]["id"] == "auth:fr-merimee:PA97100006"
    assert client.post("/api/search", json={
        "query": "加勒比历史建筑", "country": "GP", "mode": "semantic",
    }).status_code == 503
    query_file = Path(__file__).parents[1] / "src/archsearch/data/queries-merimee.json"
    assert [q.id for q in load_queries(query_file)] == [f"me{i:02}" for i in range(1, 21)]
    report = evaluate_corpus(tmp_path / "no-model", tmp_path / "rankings.json", queries=query_file)
    assert report["corpus_count"] == 3898 and report["metrics"] is None
    assert not report["qrels"]["confirmed"] and not report["runs_complete"]
