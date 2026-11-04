"""Verify the published NHL cohort and its independent modern-outline API."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from archsearch import australia_data as cohort
from archsearch.api import create_app
from archsearch.corpus import build_document, load_pre_australia_corpus, load_pre_canada_corpus
from archsearch.registered_areas import RegisteredAreasIndex
from archsearch.supplement_data import base_contract


def test_nhl_preserves_every_prior_record_and_has_no_synthetic_representatives() -> None:
    before, current = load_pre_australia_corpus(), load_pre_canada_corpus()
    assert len(before) == 1940 and len(current) == 1999
    assert base_contract(before) == {
        "base_count": 1940,
        "base_ids_sha256": "0462220bc28fba9359ee20d33ec335d8c7b830e253e9c23a22917cdf57f7e5e6",
        "base_sites_sha256": "c38269207ddd35bc939f8d20e7e4e9f08e4b4e665a3369fc6cea0979efaef12b",
    }
    assert current[:1940] == before
    assert [build_document(site) for site in current[:1940]] == [
        build_document(site) for site in before
    ]
    assert len({site.id for site in current}) == 1999
    additions = current[1940:]
    assert all(site.repr_point is None and site.location_precision is None for site in additions)
    assert all(site.chronology.status == "not_reviewed" and not site.chronology.phases
               for site in additions)
    assert "auth:au-nhl:105665" not in {site.id for site in current}
    spec = json.loads((cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes())
    assert len(spec["decisions"]) == 60 and len(spec["records"]) == 59
    assert all(not row["provenance"]["scope_and_geometry_still_require_independent_review"]
               for row in spec["records"])


def test_published_text_derivatives_rebuild_twice_without_network(tmp_path: Path) -> None:
    (tmp_path / cohort.SPEC_FILE).write_bytes((cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes())
    names = [cohort.SITES_FILE, cohort.MANIFEST_FILE]
    expected = {name: (cohort.DATA_DIR / name).read_bytes() for name in names}
    for _ in range(2):
        counts = cohort.rebuild_australia(tmp_path)["counts"]
        assert counts["added"] == 59 and counts["total"] == 1999
        assert counts["decisions"] == {"hold": 1, "include": 59}
        assert counts["registered_range_features"] == 60
        assert {name: (tmp_path / name).read_bytes() for name in names} == expected


def test_norfolk_is_additional_source_membership_and_area_is_not_a_point(tmp_path: Path) -> None:
    with TestClient(create_app(home=tmp_path)) as client:
        coverage = client.get("/api/coverage").json()
        assert coverage["total"] == 3193 and coverage["corpus_version"] == "global-v15"
        assert len(coverage["countries"]) == 203 and len(coverage["regions"]) == 7
        countries = {row["id"]: row["count"] for row in coverage["countries"]}
        assert countries["AU"] == 73 and countries["NF"] == 1
        nf = client.get("/api/sites", params={"country": "NF"}).json()
        assert nf["total"] == 1 and nf["sites"][0]["id"] == "auth:au-nhl:106167"
        sirius = client.get("/api/sites/auth:au-nhl:106167").json()
        assert sirius["geography"]["countries"] == ["AU", "NF"] and sirius["repr_point"] is None
        assert "Kingston, EXT, Australia" in sirius["geography"]["note"]
        assert not client.get("/api/sites", params={
            "country": "NF", "bbox": "-180,-90,180,90",
        }).json()["total"]
        areas = client.get("/api/sites/auth:au-nhl:106167/areas").json()
        assert areas["ready"] and areas["features"] and areas["label"] == "现代遗产登记范围"
        assert "不是古代遗址轮廓" in areas["note"]
        point_view = client.get("/api/sites/auth:au-nhl:106167/locations").json()
        assert point_view["representative_point"] is None and point_view["source_points"] == []
        assert client.get("/api/sites/auth:au-nhl:105665/areas").status_code == 404
        state = client.get("/api/status").json()
        assert not state["semantic"]["ready"] and state["registered_areas"]["sites"] == 197
        assert coverage["spatial_locations"]["points"] == 5851


def test_multistate_original_features_and_all_source_rings_survive_the_api(tmp_path: Path) -> None:
    index = RegisteredAreasIndex()
    state = index.status()
    assert state.ready and (state.sites, state.features, state.rings, state.coordinate_records) == (
        59, 60, 366, 68490,
    )
    spec = cohort._spec(cohort.DATA_DIR)
    records = {row.site.id: row for row in spec.records}
    burke = records["auth:au-nhl:106061"]
    assert {row.state for row in burke.source_features} == {"SA", "QLD"}
    assert len(burke.source_features) == 2
    with TestClient(create_app(home=tmp_path, areas=index)) as client:
        for identifier in ["auth:au-nhl:106061", "auth:au-nhl:105919"]:
            body = client.get("/api/sites/" + identifier + "/areas").json()
            expected = index.response(identifier, "global-v15").model_dump(mode="json")
            assert body == expected
            assert [row["provider_object_id"] for row in body["features"]] == (
                records[identifier].registered_range.feature_ids
            )
            assert sum(len(ring) for row in body["features"] for ring in row["rings"]) == (
                records[identifier].registered_range.coordinate_records
            )
