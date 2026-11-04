"""Published Pacific/interior identities remain browsable with honest location gaps."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from archsearch import pacific_data as cohort
from archsearch.api import create_app
from archsearch.corpus import build_document, load_corpus, load_pre_nps_corpus
from archsearch.evaluation import evaluate_corpus, load_queries
from archsearch.supplement_data import base_contract


def test_published_facts_preserve_the_pinned1800_and_shared_source_quote_limits() -> None:
    sites = load_pre_nps_corpus()
    assert len(sites) == 1807
    assert base_contract(sites[:1800]) == {
        "base_count": 1800,
        "base_ids_sha256": "c900145f6641be8722fbf2ef21b8beb04b1f44c4ae6305033738357aa47b07af",
        "base_sites_sha256": "eeffd19cb62aaa4404517e9fd07cb2b3078cf066502b378ae2e18f5c7abcffa6",
    }
    additions = {site.id: site for site in sites[1800:]}
    assert set(additions) == cohort.EXPECTED_IDS
    assert Counter(site.geography.countries[0] for site in additions.values()
                   if site.geography) == {"FM": 1, "MH": 1, "PW": 2, "FJ": 1, "CD": 2}
    airai = additions["wd:Q19871758"]
    assert airai.repr_point == (134.56027777777777, 7.361111111111111)
    assert airai.description == airai.description_zh == ""
    assert "united states" not in build_document(airai).casefold()
    excerpts: dict[str, set[str]] = {}
    for site in additions.values():
        assert site.description == site.description_zh == ""
        assert (site.repr_point is not None) == (site.id == airai.id)
        assert site.location_precision is None and not site.periods and not site.period_evidence
        assert site.chronology.status == "not_reviewed" and not site.chronology.phases
        assert site.chronology.default_phase_id is None
        for source in site.source_refs:
            if source.license not in {"CC0", "CC0-1.0"}:
                excerpts.setdefault(source.uri, set()).add(source.excerpt)
    assert all(sum(len(text.split()) for text in texts) <= 25 for texts in excerpts.values())
    spec = json.loads((cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes())
    assert len({artifact["filename"] for row in spec["records"]
                for artifact in row["source_files"]}) == 14
    assert all(row["independent_review"]["status"] == "approved" for row in spec["records"])


def test_published_derivatives_rebuild_twice_without_source_downloads(tmp_path: Path) -> None:
    (tmp_path / cohort.SPEC_FILE).write_bytes((cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes())
    expected = {name: (cohort.DATA_DIR / name).read_bytes()
                for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)}
    for _ in range(2):
        manifest = cohort.rebuild_pacific(tmp_path)
        assert expected == {name: (tmp_path / name).read_bytes() for name in expected}
        assert manifest["counts"] == {
            "base": 1800, "added": 7, "total": 1807, "countries": 5,
            "known_locations": 1, "no_adopted_coordinate": 6,
        }
    assert hashlib.sha256(expected[cohort.SITES_FILE]).hexdigest() == cohort.SITES_SHA256


def test_real_api_dot_identifier_country_browse_null_bounds_and_keyword_mode(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(home=tmp_path)) as client:
        coverage = client.get("/api/coverage").json()
        assert coverage["total"] == 3116 and coverage["corpus_version"] == "global-v14"
        assert len(coverage["countries"]) == 203 and len(coverage["regions"]) == 7
        assert coverage["locations"] == {"mapped": 2863, "polar": 3, "unknown": 250}
        assert coverage["chronology"] == {
            "reviewed": 149, "insufficient": 451, "not_reviewed": 2516,
        }
        spatial = coverage["spatial_locations"]
        assert (spatial["records"], spatial["points"], spatial["display_points"]) == (
            1239, 5851, 7266,
        )
        assert len(spatial["source_groups"]) == 3
        assert not client.get("/api/status").json()["semantic"]["ready"]
        for site in load_corpus()[1800:1807]:
            assert site.geography
            params: dict[str, str | int] = {
                "country": site.geography.countries[0], "region": site.geography.regions[0],
                "limit": 100,
            }
            page = client.get("/api/sites", params=params).json()
            assert sum(row["id"] == site.id for row in page["sites"]) == 1
            detail = client.get("/api/sites/" + quote(site.id, safe="")).json()
            assert detail == site.model_dump(mode="json")
            params["bbox"] = "-180,-90,180,90"
            within = client.get("/api/sites", params=params).json()
            assert any(row["id"] == site.id for row in within["sites"]) == (
                site.repr_point is not None
            )
            result = client.post("/api/search", json={
                "query": site.title, "mode": "bm25", "type": "historic-site",
                "country": site.geography.countries[0], "limit": 10,
            })
            assert result.status_code == 200
            assert result.json()["results"][0]["site"]["id"] == site.id


def test_pacific_diagnostics_keep_metrics_unconfirmed_without_a_model(tmp_path: Path) -> None:
    queries = cohort.DATA_DIR / "queries-pacific.json"
    pairs = load_queries(queries)
    assert len(pairs) == len({pair.id for pair in pairs}) == 20
    assert [pair.id for pair in pairs] == [f"p{index:02d}" for index in range(1, 21)]
    report = evaluate_corpus(tmp_path / "missing-model", tmp_path / "report.json", queries=queries)
    assert report["corpus_count"] == 3116 and report["metrics"] is None
    assert report["qrels"]["confirmed"] is False and report["runs_complete"] is False
    assert set(report["runs"]) == {"bm25_zh", "bm25_en", "semantic_zh", "semantic_en"}
    assert all(row["error"] is None for key, run in report["runs"].items()
               if key.startswith("bm25_") for row in run["queries"])
