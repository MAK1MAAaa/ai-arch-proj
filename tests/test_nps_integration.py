"""Exercise the published NPS cohort against the previous frozen corpus and real API."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from archsearch import nps_data as cohort
from archsearch import nps_spatial_data as spatial
from archsearch.api import create_app
from archsearch.corpus import build_document, load_corpus, load_pre_nps_corpus
from archsearch.evaluation import evaluate_corpus, load_queries
from archsearch.supplement_data import base_contract


def test_existing_evidence_and_search_text_survive_only_additive_catalogue_links() -> None:
    original, current = load_pre_nps_corpus(), load_corpus()
    assert len(original) == 1807 and len(current) == 1940
    assert base_contract(original) == {
        "base_count": 1807,
        "base_ids_sha256": "504a72bfbaeadd5ee42fe8c15e678e39328406bd2b9f9323f937463602703ec3",
        "base_sites_sha256": "e662428f2a7a3e18cd7b60ec2629eddd36cecb2b05988daeddb3bca6d1d46d84",
    }
    associated = {
        "wd:Q4930787": "AS", "wd:Q15226028": "MP", "wd:Q846967": "FM",
        "wd:Q22950225": "GU", "wd:Q19871758": "PW",
    }
    for before, after in zip(original, current[:1807], strict=True):
        assert before.id == after.id and build_document(before) == build_document(after)
        if before.id not in associated:
            assert before == after
            continue
        assert before.model_dump(exclude={"geography", "source_refs"}) == after.model_dump(
            exclude={"geography", "source_refs"},
        )
        assert before.geography and after.geography
        assert before.geography.model_dump(exclude={"countries", "regions", "note"}) == (
            after.geography.model_dump(exclude={"countries", "regions", "note"})
        )
        for name in ("countries", "regions"):
            old_values = getattr(before.geography, name)
            assert getattr(after.geography, name)[:len(old_values)] == old_values
        assert associated[before.id] in after.geography.countries
        assert "nps-pacific" in after.geography.regions
        assert after.source_refs[:len(before.source_refs)] == before.source_refs
        assert all(not ref.excerpt for ref in after.source_refs[len(before.source_refs):])
    additions = current[1807:]
    assert len({site.id for site in current}) == 1940
    assert sum(site.repr_point is not None for site in additions) == 111
    assert all(site.chronology.status == "not_reviewed" and not site.chronology.phases
               for site in additions)
    assert all(site.location_precision is None for site in additions)


def test_four_published_files_rebuild_deterministically_offline(tmp_path: Path) -> None:
    directory = cohort.DATA_DIR
    (tmp_path / cohort.SPEC_FILE).write_bytes((directory / cohort.SPEC_FILE).read_bytes())
    expected = {name: (directory / name).read_bytes() for name in (
        cohort.SPEC_FILE, cohort.SITES_FILE, cohort.MANIFEST_FILE, spatial.LOCATIONS_FILE,
    )}
    for _ in range(2):
        counts = cohort.rebuild_nps(tmp_path)["counts"]
        assert counts["decisions"] == {"include": 133, "existing": 5, "hold": 18}
        assert spatial.rebuild_nps_locations(tmp_path) == {"records": 111, "points": 112}
        assert {name: (tmp_path / name).read_bytes() for name in expected} == expected


def test_public_private_duplicate_names_and_second_point_in_real_api(tmp_path: Path) -> None:
    with TestClient(create_app(home=tmp_path)) as client:
        report = client.get("/api/coverage").json()
        assert report["total"] == 1940 and report["corpus_version"] == "global-v11"
        assert len(report["countries"]) == 201 and len(report["regions"]) == 7
        countries = {row["id"]: row["count"] for row in report["countries"]}
        assert {key: countries[key] for key in ["AS", "GU", "MP", "UM", "FM", "MH", "PW"]} == {
            "AS": 14, "GU": 74, "MP": 22, "UM": 1, "FM": 23, "MH": 5, "PW": 4,
        }
        page = client.get("/api/sites", params={"region": "nps-pacific", "limit": 100}).json()
        assert page["total"] == 138
        for ref in ("87001980", "85002726"):
            detail = client.get("/api/sites/auth:nps-nris:" + ref).json()
            assert detail["repr_point"] is None
            assert detail["chronology"]["status"] == "not_reviewed"
        hospitals = [client.get("/api/sites/auth:nps-nris:" + ref).json()
                     for ref in ("74002189", "81000664")]
        assert hospitals[0]["title"] == hospitals[1]["title"]
        assert hospitals[0]["id"] != hospitals[1]["id"]
        wells = client.get("/api/sites/auth:nps-nris:08000165/locations").json()
        assert len(wells["source_points"]) == 2
        assert wells["representative_point"] == wells["source_points"][0]
        assert wells["source"]["sha256"] == cohort.SPEC_SHA256
        second = wells["source_points"][1]
        bbox = f"{second[0] - .0001},{second[1] - .0001},{second[0] + .0001},{second[1] + .0001}"
        within = client.get("/api/sites", params={"bbox": bbox}).json()
        assert Counter(row["id"] for row in within["sites"])["auth:nps-nris:08000165"] == 1
        result = client.post("/api/search", json={
            "query": "Canada Water Wells", "mode": "bm25", "country": "GU", "limit": 10,
        })
        assert result.status_code == 200
        assert result.json()["results"][0]["site"]["id"] == "auth:nps-nris:08000165"
        assert not client.get("/api/status").json()["semantic"]["ready"]
        blunts = client.get("/api/sites/wd:Q4930787").json()
        assert {"AS", "US"} <= set(blunts["geography"]["countries"])


def test_nps_diagnostics_never_invent_relevance_judgments(tmp_path: Path) -> None:
    queries = cohort.DATA_DIR / "queries-nps-pacific.json"
    assert len(load_queries(queries)) == 20
    result = evaluate_corpus(tmp_path / "missing-model", tmp_path / "report.json", queries=queries)
    assert result["corpus_count"] == 1940 and result["metrics"] is None
    assert not result["qrels"]["confirmed"] and not result["runs_complete"]
    assert all(row["error"] is None for key, group in result["runs"].items()
               if key.startswith("bm25_") for row in group["queries"])
    spec = json.loads((cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes())
    assert len({item["filename"] for row in spec["records"] + spec["decisions"]
                for item in row["source_files"]}) == 294
