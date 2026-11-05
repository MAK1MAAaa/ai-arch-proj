"""Published DFHD source facts, honest location roles and offline catalogue behaviour."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from archsearch import canada_data as cohort
from archsearch.api import create_app
from archsearch.corpus import build_document, load_pre_canada_corpus, load_pre_hong_kong_corpus
from archsearch.evaluation import evaluate_corpus, load_queries
from archsearch.supplement_data import base_contract


def test_canadian_cohort_preserves_all_1999_source_records_and_search_documents() -> None:
    before, current = load_pre_canada_corpus(), load_pre_hong_kong_corpus()
    assert base_contract(before) == {
        "base_count": 1999,
        "base_ids_sha256": "1a197b6522e791d4cee045dcaaaf32212a3b62bcee3374f93bfa6205e0b5b46d",
        "base_sites_sha256": "c35e44db219b9abb61b038bb80c6832d41d368fa840ef91aa7bc19283fb7d313",
    }
    assert len(current) == len({site.id for site in current}) == 2976
    assert current[:1999] == before
    assert [build_document(site) for site in current[:1999]] == [
        build_document(site) for site in before
    ]
    spec = cohort._spec(cohort.DATA_DIR)
    assert len(spec.decisions) == 1014 and len(spec.records) == 977
    assert Counter(row.disposition for row in spec.decisions) == {
        "include": 977, "existing": 9, "component": 6, "hold": 22,
    }
    additions = current[1999:]
    assert {site.id for site in additions} == {record.site.id for record in spec.records}
    assert all(site.geography and site.geography.countries == ["CA"] for site in additions)
    assert all(site.chronology.status == "not_reviewed" and not site.chronology.phases
               and not site.periods and not site.period_evidence
               and site.location_precision is None for site in additions)
    assert all(not site.description_zh for site in additions)
    assert len({row.source_row.province_territory for row in spec.records}) == 13
    assert all("pending independent review" not in site.geography.note
               for site in additions if site.geography)
    for record in spec.records:
        assert record.site.description == (record.source_row.description or "")
        qualification = [ref for ref in record.site.source_refs
                         if ref.id.startswith("qualification:")]
        assert len(qualification) == 1 and qualification[0].excerpt == cohort.DESIGNATION_TYPE
        assert record.source_row.province_territory in build_document(record.site)
        if record.administrative_review.state == "source_admin_review":
            assert record.site.geography is not None
            assert cohort.source_administrative_note(record.administrative_review) in (
                record.site.geography.note
            )


def test_canadian_derivatives_rebuild_twice_without_raw_downloads(tmp_path: Path) -> None:
    (tmp_path / cohort.SPEC_FILE).write_bytes((cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes())
    expected = {name: (cohort.DATA_DIR / name).read_bytes()
                for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)}
    for _ in range(2):
        manifest = cohort.rebuild_canada(tmp_path)
        assert manifest["counts"]["source_designations"] == 1014
        assert manifest["counts"]["added"] == 977 and manifest["counts"]["total"] == 2976
        assert {name: (tmp_path / name).read_bytes() for name in expected} == expected
    assert manifest["counts"]["decisions"] == {
        "include": 977, "existing": 9, "component": 6, "hold": 22,
    }
    assert manifest["counts"]["source_admin_review_notices"] == 70
    assert len(manifest["catalogue_associations"]) == 15
    french = [row for row in manifest["decisions"] if row["source_row"]["Country"] == "France"]
    assert {row["source_row"]["Directory of Federal Heritage Designations Identifier"]
            for row in french} == {"1779", "1780"}
    assert all(row["disposition"] == "hold" for row in french)


def test_canadian_catalogue_and_selected_original_point_do_not_infer_years(tmp_path: Path) -> None:
    with TestClient(create_app(home=tmp_path)) as client:
        coverage = client.get("/api/coverage").json()
        assert coverage["total"] == 3897 and coverage["corpus_version"] == "global-v18"
        assert len(coverage["countries"]) == 211 and len(coverage["regions"]) == 7
        assert coverage["chronology"] == {
            "reviewed": 149, "insufficient": 451, "not_reviewed": 3297,
        }
        assert coverage["spatial_locations"]["points"] == 5851
        page = client.get("/api/sites", params={"country": "CA", "limit": 50}).json()
        assert page["total"] == 992 and len(page["sites"]) == 50
        for identifier in ("52", "66", "254", "305", "325"):
            site_id = "auth:ca-dfhd:" + identifier
            detail = client.get("/api/sites/" + site_id).json()
            assert detail["id"] == site_id and detail["geography"]["countries"] == ["CA"]
            assert detail["chronology"]["status"] == "not_reviewed"
            assert not detail["chronology"]["phases"]
            assert detail["location_precision"] is None
            search = client.post("/api/search", json={
                "query": detail["title"], "mode": "bm25", "country": "CA", "limit": 10,
            }).json()
            assert search["corpus_version"] == "global-v18"
            assert any(result["site"]["id"] == site_id for result in search["results"])
        for identifier in ("60", "257", "770", "1779", "1780", "17353"):
            assert client.get("/api/sites/auth:ca-dfhd:" + identifier).status_code == 404
        state = client.get("/api/status").json()
        assert state["corpus"]["count"] == 3897 and not state["semantic"]["ready"]
        assert state["registered_areas"]["sites"] == 197


def test_canadian_diagnostics_leave_relevance_metrics_unconfirmed(tmp_path: Path) -> None:
    queries = cohort.DATA_DIR / "queries-canada.json"
    pairs = load_queries(queries)
    assert [pair.id for pair in pairs] == [f"ca{index:02d}" for index in range(1, 21)]
    report = evaluate_corpus(tmp_path / "no-model", tmp_path / "report.json", queries=queries)
    assert report["corpus_count"] == 3897 and report["metrics"] is None
    assert report["qrels"]["confirmed"] is False and not report["runs_complete"]
    assert set(report["runs"]) == {"bm25_zh", "bm25_en", "semantic_zh", "semantic_en"}
    assert all(row["error"] is None for key, run in report["runs"].items()
               if key.startswith("bm25_") for row in run["queries"])
