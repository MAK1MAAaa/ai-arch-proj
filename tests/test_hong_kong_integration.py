"""Published Hong Kong whole objects, honest shapes and offline original-name discovery."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archsearch import hong_kong_data as cohort
from archsearch.api import create_app
from archsearch.corpus import build_document, load_pre_hong_kong_corpus, load_pre_singapore_corpus
from archsearch.evaluation import evaluate_corpus, load_queries
from archsearch.hong_kong_areas import load_hong_kong_area_group
from archsearch.supplement_data import base_contract


def test_complete_hong_kong_supplement_preserves_every_original2976_field() -> None:
    before, current = load_pre_hong_kong_corpus(), load_pre_singapore_corpus()
    assert base_contract(before) == {
        "base_count": 2976,
        "base_ids_sha256": "7dfba2896df4370dc078372b735aaddc3141fcba36ef2c2135d40fa4cc0ef830",
        "base_sites_sha256": "794d50f1df00ad835a9f108eefa4543c4944296495cffceb1fe4868ee77d77e0",
    }
    assert current[:2976] == before
    assert [build_document(site) for site in current[:2976]] == [
        build_document(site) for site in before
    ]
    assert len(current) == len({site.id for site in current}) == 3116
    spec = cohort._spec(cohort.DATA_DIR)
    assert len(spec.decisions) == len(spec.records) == 140
    assert len(spec.source_feature_roster) == 174 and not spec.held_features
    assert len(spec.countries[0].source_m49_cells) == 15
    assert "Developing" not in spec.countries[0].source_m49_cells
    records = {record.whole.project_id: record for record in spec.records}
    for site in current[2976:]:
        whole = records[site.id].whole
        assert site.title == whole.title_en and site.names == [whole.title_tc]
        assert site.description == site.description_zh == ""
        assert site.repr_point is None and site.location_precision is None
        assert not site.periods and not site.period_evidence and not site.chronology.phases
        assert site.chronology.status == "not_reviewed"
        assert site.geography and site.geography.countries == ["HK"]
        assert site.geography.point_count == 0
    assert len(records["auth:hk-amo:monuments-88"].whole.source_features) == 22
    assert {relation.relation for relation in
            records["auth:hk-amo:monuments-13"].whole.scope_relations} == {
        "same_whole", "component_of_whole",
    }


def test_shipped_facts_rebuild_twice_without_any_source_download(tmp_path: Path) -> None:
    (tmp_path / cohort.SPEC_FILE).write_bytes((cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes())
    expected = {name: (cohort.DATA_DIR / name).read_bytes()
                for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)}
    for _ in range(2):
        manifest = cohort.rebuild_hong_kong(tmp_path)
        assert manifest["counts"]["added"] == 140 and manifest["counts"]["total"] == 3116
        assert manifest["counts"]["source_polygon_sites"] == 138
        assert manifest["counts"]["source_polygon_features"] == 174
        assert {name: (tmp_path / name).read_bytes() for name in expected} == expected


@pytest.fixture(scope="module")
def hong_kong_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    with TestClient(create_app(home=tmp_path_factory.mktemp("hk-offline-api"))) as client:
        yield client


def test_country_and_district_catalogues_preserve_unknowns_without_geocoding(
    hong_kong_client: TestClient,
) -> None:
    client = hong_kong_client
    page = client.get("/api/sites", params={"country": "HK", "limit": 100}).json()
    assert page["total"] == 140 and len(page["sites"]) == 100
    assert all(site["repr_point"] is None for site in page["sites"])
    assert client.get("/api/sites", params={
        "country": "HK", "bbox": "-180,-90,180,90",
    }).json()["total"] == 0
    facets = client.get("/api/subdivisions?country=HK").json()
    assert facets["ready"] and facets["supported"]
    assert (facets["total"], facets["assigned"], facets["unassigned"]) == (140, 138, 2)
    assert len(facets["subdivisions"]) == 17
    assert sum(row["count"] for row in facets["subdivisions"]) == 139
    assert "来源要素地区" in facets["note"] and "不表示整体或全部几何" in facets["note"]
    for district in ("HK:southern", "HK:wan-chai"):
        data = client.get("/api/sites", params={
            "country": "HK", "subdivision": district, "limit": 100,
        }).json()
        assert "auth:hk-amo:monuments-88" in {site["id"] for site in data["sites"]}
        assert data["subdivision"] == district and data["subdivision_version"]
    ca = client.get("/api/subdivisions?country=CA").json()
    assert ca["assigned"] == 992 and sum(row["count"] for row in ca["subdivisions"]) == 993
    assert client.get("/api/sites?country=CA&subdivision=HK:southern").status_code == 422


def test_source_polygons_are_separate_from_points_and_registration_extents(
    hong_kong_client: TestClient,
) -> None:
    client = hong_kong_client
    status = client.get("/api/status").json()
    assert status["corpus"]["count"] == 3193 and not status["semantic"]["ready"]
    assert status["registered_areas"]["ready"]
    assert status["registered_areas"]["version"] == "registered-areas-v1+hong-kong-polygons-v1"
    assert (status["registered_areas"]["sites"], status["registered_areas"]["features"],
            status["registered_areas"]["rings"],
            status["registered_areas"]["coordinate_records"]) == (197, 234, 546, 72540)
    group = load_hong_kong_area_group()
    assert group and group.ready
    assert len(group.site_ids) == 140 and len(group.features) == 138
    assert sum(len(rows) for rows in group.features.values()) == 174
    assert sum(len(row.rings) for rows in group.features.values() for row in rows) == 180
    assert sum(len(ring) for rows in group.features.values() for row in rows
               for ring in row.rings) == 4050
    for number, size in ((13, 2), (88, 22), (139, 0), (140, 0)):
        identifier = f"auth:hk-amo:monuments-{number}"
        shapes = client.get(f"/api/sites/{identifier}/areas").json()
        assert shapes["ready"] and shapes["label"] == "来源古迹多边形"
        assert "不承诺法定保护边界" in shapes["note"]
        assert len(shapes["features"]) == size
        assert [row["source_index"] for row in shapes["features"]] == list(range(size))
        locations = client.get(f"/api/sites/{identifier}/locations").json()
        assert locations["representative_point"] is None and locations["source_points"] == []
    au = client.get("/api/sites/auth:au-nhl:106061/areas").json()
    assert au["ready"] and au["label"] == "现代遗产登记范围" and "GDA94" in au["note"]
    assert len(au["features"]) == 2


def test_original_traditional_chinese_names_are_searchable_without_a_model(
    hong_kong_client: TestClient,
) -> None:
    result = hong_kong_client.post("/api/search", json={
        "query": "李鄭屋漢墓", "country": "HK", "mode": "bm25", "limit": 10,
    })
    assert result.status_code == 200
    assert result.json()["results"][0]["site"]["id"] == "auth:hk-amo:monuments-35"
    missing_model = hong_kong_client.post("/api/search", json={
        "query": "寻找香港石刻", "country": "HK", "mode": "semantic", "limit": 10,
    })
    assert missing_model.status_code == 503


def test_twenty_paired_diagnostics_leave_relevance_metrics_unconfirmed(tmp_path: Path) -> None:
    queries = cohort.DATA_DIR / "queries-hong-kong.json"
    assert [pair.id for pair in load_queries(queries)] == [
        f"hk{number:02d}" for number in range(1, 21)
    ]
    report = evaluate_corpus(tmp_path / "no-model", tmp_path / "hk-rankings.json", queries=queries)
    assert report["corpus_count"] == 3193 and report["metrics"] is None
    assert not report["qrels"]["confirmed"] and not report["runs_complete"]
