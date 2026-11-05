"""Real GF/YT/PM notice scopes extend the corpus without changing earlier records."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archsearch import merimee_extension_data as cohort
from archsearch.api import create_app
from archsearch.corpus import (
    build_document,
    load_pre_merimee_extension_corpus,
    load_pre_targets_corpus,
)
from archsearch.evaluation import evaluate_corpus, load_queries
from archsearch.supplement_data import base_contract


def test_original3775_fields_order_and_shared_documents_are_unchanged() -> None:
    before, current = load_pre_merimee_extension_corpus(), load_pre_targets_corpus()
    assert base_contract(before) == {
        "base_count": 3775,
        "base_ids_sha256": "87fb14327abb2a6d9e720687f53099485211b8f5426aadc941fe5c4c404546af",
        "base_sites_sha256": "4622fb2d263291b1e527fcf29c7321c8e84cc2e3e13961bd673dadfa13b261c3",
    }
    assert current[:3775] == before and len(current) == len({s.id for s in current}) == 3897
    documents = [[s.id, build_document(s)] for s in current[:3775]]
    assert hashlib.sha256(json.dumps(documents, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest() == (
        "e4c61e5c8d0c935fa7b3e811b5232a01f9d92c56e289474c3be7afaeac2e3c31"
    )
    additions = current[3775:]
    assert Counter(s.geography.countries[0] for s in additions if s.geography) == {
        "GF": 90, "YT": 16, "PM": 16,
    }
    for site in additions:
        assert site.repr_point is not None and site.location_precision is None
        assert not site.names and not site.description_zh
        assert not site.chronology.phases and site.chronology.status == "not_reviewed"
        original = json.loads(site.details.split("\n", 1)[1])["source_record"]
        assert len(original) == 78 and original["Reference"] == site.id.rpartition(":")[2]
        assert "independent_review" not in build_document(site)
        assert site.geography and site.geography.point_count == 1
        if site.geography.countries == ["PM"]:
            assert site.geography.regions == ["europe-north-america"]


def test_shipped_facts_rebuild_twice_without_original_csv_pages_or_model(tmp_path: Path) -> None:
    for name in (cohort.ROSTER_FILE, cohort.SPEC_FILE):
        (tmp_path / name).write_bytes((cohort.DATA_DIR / name).read_bytes())
    expected = {name: (cohort.DATA_DIR / name).read_bytes()
                for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)}
    base = load_pre_merimee_extension_corpus()
    for _ in range(2):
        manifest = cohort.rebuild_merimee_extension(tmp_path, base=base)
        assert manifest["counts"]["source_records"] == 123
        assert manifest["counts"]["decisions"] == {"component": 1, "include": 122}
        assert manifest["counts"]["adopted_reference_points"] == 122
        assert manifest["counts"]["new_historical_phases"] == 0
        assert {name: (tmp_path / name).read_bytes() for name in expected} == expected


@pytest.fixture(scope="module")
def extension_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    with TestClient(create_app(home=tmp_path_factory.mktemp("extension-offline"))) as client:
        yield client


def test_three_statistical_area_directories_paginate_without_country_inference(
    extension_client: TestClient,
) -> None:
    client = extension_client
    for area, count in {"GF": 90, "YT": 16, "PM": 16}.items():
        pages = [client.get("/api/sites", params={
            "country": area, "offset": offset, "limit": 50,
        }).json() for offset in range(0, count, 50)]
        assert all(p["total"] == count for p in pages)
        assert len({s["id"] for p in pages for s in p["sites"]}) == count
        assert all(s["repr_point"] is not None and s["geography"]["countries"] == [area]
                   for p in pages for s in p["sites"])
    coverage = client.get("/api/coverage").json()
    assert coverage["corpus_version"] == "global-v19" and coverage["total"] == 3898
    assert len(coverage["countries"]) == 211
    assert coverage["locations"] == {"mapped": 3505, "polar": 3, "unknown": 390}
    assert coverage["spatial_locations"]["display_points"] == 7908
    assert client.get("/api/sites/auth:fr-merimee:PA97300012").status_code == 404
    whole = client.get("/api/sites/auth:fr-merimee:PA97300021").json()
    assert whole["title"] == "Entités archéologiques de l’Inselberg de la Mamilipann"
    assert not whole["names"] and not whole["chronology"]["phases"]


def test_literal_commune_variants_survive_same_cog_and_old_memberships_remain(
    extension_client: TestClient,
) -> None:
    client = extension_client
    facets = client.get("/api/subdivisions?country=GF").json()
    assert facets["ready"] and facets["subdivision_version"] == "source-subdivisions-v7"
    assert facets["assigned"] == 90 and len(facets["subdivisions"]) == 15
    variants = [row for row in facets["subdivisions"] if row["label"] in {
        "Montsinéry-Tonnegrande", "Montsinéry-Tonnégrande",
    }]
    assert len(variants) == 2 and variants[0]["id"] != variants[1]["id"]
    for row in variants:
        page = client.get("/api/sites", params={
            "country": "GF", "subdivision": row["id"], "limit": 100,
        }).json()
        assert page["total"] == row["count"] > 0
        for item in page["sites"]:
            site = client.get("/api/sites/" + item["id"]).json()
            raw = json.loads(site["details"].split("\n", 1)[1])["source_record"]
            assert raw["Commune_forme_editoriale"] == row["label"]
            assert raw["COG_Insee_lors_de_la_protection"] == "97313"
    for area, assigned in {"CA": 992, "HK": 138, "BR": 133, "GP": 112,
                           "BL": 7, "MF": 1, "MQ": 124, "RE": 205}.items():
        current = client.get("/api/subdivisions", params={"country": area}).json()
        assert current["assigned"] == assigned
    assert not client.get("/api/subdivisions?country=SG").json()["supported"]


def test_separate_mosque_minaret_scopes_do_not_create_phases_or_boundaries(
    extension_client: TestClient,
) -> None:
    client = extension_client
    mosque = client.get("/api/sites/auth:fr-merimee:PA97600002").json()
    minaret = client.get("/api/sites/auth:fr-merimee:PA97600007").json()
    mosque_scope = json.loads(mosque["details"].split("\n", 1)[1])["scope"]["literal"]
    assert "minaret" in mosque_scope.lower()
    assert minaret["id"] != mosque["id"]
    for site in [mosque, minaret]:
        assert site["location_precision"] is None and not site["chronology"]["phases"]
        assert client.get("/api/sites/" + site["id"] + "/areas").json()["features"] == []
    hits = client.post("/api/search", json={
        "query": "Susky", "country": "GF", "mode": "bm25",
    }).json()["results"]
    assert hits[0]["site"]["id"] == "auth:fr-merimee:PA97300021"
    assert all(h["site"]["id"] != "auth:fr-merimee:PA97300012" for h in hits)


def test_new_diagnostic_queries_preserve_the_unconfirmed_relevance_gate(tmp_path: Path) -> None:
    queries = cohort.DATA_DIR / "queries-merimee-extension.json"
    assert [p.id for p in load_queries(queries)] == [f"mx{i:02}" for i in range(1, 21)]
    report = evaluate_corpus(tmp_path / "no-model", tmp_path / "rankings.json", queries=queries)
    assert report["corpus_count"] == 3898 and report["metrics"] is None
    assert not report["qrels"]["confirmed"] and not report["runs_complete"]
