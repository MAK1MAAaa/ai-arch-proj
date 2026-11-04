"""Published African facts remain usable without source downloads or a model."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from archsearch import africa_data as cohort
from archsearch.api import create_app
from archsearch.corpus import build_document, load_corpus, load_pre_nps_corpus
from archsearch.domain import Site
from archsearch.evaluation import evaluate_corpus, load_queries
from archsearch.supplement_data import base_contract


def test_published_append_preserves_pinned1795_and_reviewed_five_facts() -> None:
    sites = load_pre_nps_corpus()[:1800]
    assert len(sites) == 1800
    assert base_contract(sites[:1795]) == {
        "base_count": 1795,
        "base_ids_sha256": "2f3badcb912fc0585c554d65f19f68236e2b4b0d9728c81b3e86a509877f3e47",
        "base_sites_sha256": "7ce905be26b382ca0484c4e3c7bed04752beb9c0c1252f27e9cfcc7aac268ffa",
    }
    additions = {site.id: site for site in sites[1795:]}
    assert set(additions) == cohort.EXPECTED_IDS
    assert Counter(site.geography.countries[0] for site in additions.values()
                   if site.geography) == {"AO": 1, "CD": 1, "CM": 1, "NE": 2}
    assert additions["auth:whc-tentative:6251"].repr_point == (12.877028, -15.938057)
    assert additions["auth:whc-tentative:6320"].repr_point == (10.1138, 6.0888)
    for identifier in ("961", "5044", "5045"):
        site = additions["auth:whc-tentative:" + identifier]
        assert site.repr_point is None and site.geography and site.geography.point_count == 0
    for site in additions.values():
        assert site.location_precision is None and not site.periods and not site.period_evidence
        assert site.chronology.status == "not_reviewed" and not site.chronology.phases
        assert site.chronology.default_phase_id is None
        assert site.description_zh == ""
        assert site.source_uri.startswith("https://whc.unesco.org/en/tentativelists/")
    spec = json.loads((cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes())
    assert len({artifact["filename"] for row in spec["records"]
                for artifact in row["source_files"]}) == 16
    for row in spec["records"]:
        assert row["independent_review"]["status"] == "approved"
        assert build_document(Site.model_validate(row["site"])) == build_document(
            additions[row["site"]["id"]],
        )


def test_published_derivatives_rebuild_byte_identically_offline(tmp_path: Path) -> None:
    (tmp_path / cohort.SPEC_FILE).write_bytes((cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes())
    expected = {name: (cohort.DATA_DIR / name).read_bytes()
                for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)}
    for _ in range(2):
        manifest = cohort.rebuild_africa(tmp_path)
        assert expected == {name: (tmp_path / name).read_bytes() for name in expected}
        assert manifest["counts"] == {
            "base": 1795, "added": 5, "total": 1800, "countries": 4,
            "known_locations": 2, "no_adopted_coordinate": 3,
        }
    assert hashlib.sha256(expected[cohort.SITES_FILE]).hexdigest() == cohort.SITES_SHA256


def test_real_api_country_browse_null_points_bounds_and_keyword_discovery(tmp_path: Path) -> None:
    with TestClient(create_app(home=tmp_path)) as client:
        coverage = client.get("/api/coverage").json()
        assert coverage["total"] == 1999 and coverage["corpus_version"] == "global-v12"
        assert len(coverage["countries"]) == 202 and len(coverage["regions"]) == 7
        assert coverage["locations"] == {"mapped": 1898, "polar": 3, "unknown": 98}
        assert coverage["chronology"] == {
            "reviewed": 149, "insufficient": 451, "not_reviewed": 1399,
        }
        spatial = coverage["spatial_locations"]
        assert (spatial["records"], spatial["points"], spatial["display_points"]) == (
            1239, 5851, 6301,
        )
        assert len(spatial["source_groups"]) == 3
        status = client.get("/api/status").json()
        assert not status["semantic"]["ready"]
        for site in load_corpus()[1795:1800]:
            assert site.geography
            page = client.get("/api/sites", params={
                "country": site.geography.countries[0], "region": "africa", "limit": 100,
            }).json()
            assert sum(row["id"] == site.id for row in page["sites"]) == 1
            detail = client.get("/api/sites/" + quote(site.id, safe="")).json()
            assert detail == site.model_dump(mode="json")
            within = client.get("/api/sites", params={
                "country": site.geography.countries[0], "bbox": "-180,-90,180,90",
                "limit": 100,
            }).json()
            assert any(row["id"] == site.id for row in within["sites"]) == (
                site.repr_point is not None
            )
            result = client.post("/api/search", json={
                "query": site.title, "mode": "bm25", "type": "historic-site",
                "country": site.geography.countries[0], "limit": 10,
            })
            assert result.status_code == 200
            assert result.json()["results"][0]["site"]["id"] == site.id


def test_africa_diagnostics_do_not_publish_unconfirmed_metrics(tmp_path: Path) -> None:
    queries = cohort.DATA_DIR / "queries-africa.json"
    pairs = load_queries(queries)
    assert len(pairs) == len({pair.id for pair in pairs}) == 20
    assert [pair.id for pair in pairs] == [f"a{index:02d}" for index in range(1, 21)]
    report = evaluate_corpus(tmp_path / "missing-model", tmp_path / "report.json", queries=queries)
    assert report["corpus_count"] == 1999 and report["metrics"] is None
    assert report["qrels"]["confirmed"] is False and report["runs_complete"] is False
    assert set(report["runs"]) == {"bm25_zh", "bm25_en", "semantic_zh", "semantic_en"}
    assert all(row["error"] is None for key, run in report["runs"].items()
               if key.startswith("bm25_") for row in run["queries"])
