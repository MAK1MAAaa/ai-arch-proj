"""Source-qualified additions must not rewrite the existing corpus or its evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from archsearch import supplement_data as supplement
from archsearch.api import create_app
from archsearch.catalogue_data import load_catalogue
from archsearch.corpus import build_document, load_curated_corpus
from archsearch.domain import Site
from archsearch.polar_data import load_polar


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@pytest.fixture(scope="module")
def unchanged_base() -> list[Site]:
    return load_polar(load_catalogue(load_curated_corpus()))


def reference(identifier: str, *, authority: bool = False) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": "Fixture cultural authority" if authority else "Fixture Wikidata identity",
        "uri": f"https://example.org/{identifier}",
        "publisher": "Fixture heritage authority" if authority else "Wikidata contributors",
        "license": None if authority else "CC0-1.0",
        "revision": "fixed-fixture-v1",
        "accessed": "2026-11-04",
        "excerpt": "Listed cultural site." if authority else "",
    }


def reviewed_record(identifier: str, country: str, point: list[float] | None) -> dict[str, Any]:
    authority = reference("qualified-fixture", authority=True)
    coordinate_source = reference("wikidata-fixture")
    known = point is not None
    site = {
        "id": identifier,
        "title": "Fixture monument" if known else "Fixture historical grave",
        "description": "Original CC0 description." if known else "",
        "description_zh": "",
        "details": "",
        "names": ["Source alias"],
        "types": ["historic-site"],
        "periods": [],
        "repr_point": point,
        "location_precision": None,
        "source_uri": authority["uri"],
        "contributors": [authority["publisher"]],
        "period_evidence": [],
        "source_kind": "supplement",
        "source_refs": [authority, coordinate_source] if known else [authority],
        "chronology": {
            "status": "not_reviewed", "method": "identity-only fixture review",
            "reviewed_at": None, "note": "Historical stages are not reviewed.",
            "default_phase_id": None, "phases": [],
        },
        "geography": {
            "authority_id": "supplement:" + identifier,
            "countries": [country], "regions": ["asia-pacific"],
            "source": coordinate_source if known else authority,
            "point_count": 1 if known else 0,
            "note": "Source membership; representative point is not an excavation coordinate.",
        },
    }
    return {
        "site": site,
        "country_label": "Bhutan" if country == "BT" else "Niue",
        "coordinate": {
            "method": "wikidata" if known else "unknown", "point": point,
            "source_uri": coordinate_source["uri"] if known else None,
            "statement_id": "Q900000001$selected-point" if known else None,
            "globe": "http://www.wikidata.org/entity/Q2" if known else None,
            "precision": 0.001 if known else None, "rank": "normal" if known else None,
            "note": "Fixed Earth statement." if known else "No known public site coordinate.",
        },
        "independent_review": {
            "status": "approved", "reviewer": "independent-fixture-agent",
            "method": "Compared authority qualification and selected source statement.",
            "reviewed_at": "2026-11-04",
        },
        "source_files": [],
        "provenance": {"fixture": True, "inference": "No historical dates generated."},
    }


@dataclass
class Bundle:
    directory: Path
    cache: Path
    spec: dict[str, Any]
    monkeypatch: pytest.MonkeyPatch

    def pin_spec(self) -> None:
        payload = encoded(self.spec)
        (self.directory / supplement.SPEC_FILE).write_bytes(payload)
        self.monkeypatch.setattr(supplement, "SPEC_SHA256", digest(payload))

    def compile(self) -> dict[str, Any]:
        self.pin_spec()
        records = sorted(self.spec["records"], key=lambda row: (
            hashlib.sha256(("country-supplement-v1:" + row["site"]["id"]).encode()).hexdigest(),
            row["site"]["id"],
        ))
        payload = encoded([
            Site.model_validate(row["site"]).model_dump(mode="json") for row in records
        ])
        self.monkeypatch.setattr(supplement, "SITES_SHA256", digest(payload))
        return supplement.rebuild_supplement(self.directory)


@pytest.fixture
def bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unchanged_base: list[Site],
) -> Bundle:
    directory = tmp_path / "data"
    directory.mkdir()
    cache = tmp_path / "source-cache"
    cache.mkdir()
    records = [
        reviewed_record("wd:Q900000001", "BT", [90.0, 27.0]),
        reviewed_record("auth:fixture:unknown-1", "NU", None),
    ]
    artifacts = []
    for filename, value in (
        ("authority.json", {"qualification": "Listed cultural site."}),
        ("point.json", {"P625": {"longitude": 90, "latitude": 27, "globe": "Q2"}}),
    ):
        payload = encoded(value)
        (cache / filename).write_bytes(payload)
        artifacts.append({"filename": filename, "sha256": digest(payload),
                          "uri": f"https://example.org/{filename}"})
    records[0]["source_files"] = copy.deepcopy(artifacts)
    records[1]["source_files"] = [copy.deepcopy(artifacts[0])]
    spec = {
        "schema_version": 1, "cohort_version": "country-supplement-v1",
        "corpus_version": "global-v5", **supplement.base_contract(unchanged_base),
        "selection": "Fixed independently reviewed fixture; no generated historical phases.",
        "records": records,
    }
    monkeypatch.setattr(supplement, "EXPECTED_COUNTRIES", frozenset({"BT", "NU"}))
    result = Bundle(directory, cache, spec, monkeypatch)
    result.compile()
    return result


def test_append_preserves_all_old_objects_original_text_and_unknown_coordinates(
    unchanged_base: list[Site], bundle: Bundle,
) -> None:
    original = [site.model_dump(mode="json") for site in unchanged_base]
    documents = [build_document(site) for site in unchanged_base]
    loaded = supplement.load_supplement(unchanged_base, bundle.directory)
    assert len(unchanged_base) == bundle.spec["base_count"] == 1625
    assert len(loaded) == 1627
    assert all(before is after for before, after in zip(unchanged_base, loaded[:1625], strict=True))
    assert [site.model_dump(mode="json") for site in loaded[:1625]] == original
    assert [build_document(site) for site in loaded[:1625]] == documents
    additions = {site.id: site for site in loaded[1625:]}
    assert additions["wd:Q900000001"].repr_point == (90, 27)
    unknown = additions["auth:fixture:unknown-1"]
    assert unknown.repr_point is None
    assert unknown.geography is not None and unknown.geography.point_count == 0
    assert unknown.location_precision is None
    assert all(site.chronology.status == "not_reviewed" and not site.chronology.phases
               for site in additions.values())


def test_deterministic_rebuild_is_byte_stable_and_source_order_does_not_change_selection(
    unchanged_base: list[Site], bundle: Bundle,
) -> None:
    first = (bundle.directory / supplement.SITES_FILE).read_bytes()
    first_manifest = (bundle.directory / supplement.MANIFEST_FILE).read_bytes()
    supplement.rebuild_supplement(bundle.directory)
    assert (bundle.directory / supplement.SITES_FILE).read_bytes() == first
    assert (bundle.directory / supplement.MANIFEST_FILE).read_bytes() == first_manifest
    original_ids = [site.id for site in supplement.load_supplement(
        unchanged_base, bundle.directory,
    )][1625:]
    bundle.spec["records"].reverse()
    bundle.compile()
    assert (bundle.directory / supplement.SITES_FILE).read_bytes() == first
    assert [site.id for site in supplement.load_supplement(
        unchanged_base, bundle.directory,
    )][1625:] == original_ids


def test_labels_are_read_only_new_codes_and_cannot_overwrite_the_base_registry(
    bundle: Bundle,
) -> None:
    labels = supplement.country_labels(bundle.directory)
    assert dict(labels) == {"BT": "Bhutan", "NU": "Niue"}
    with pytest.raises(TypeError):
        labels["FR"] = "overwritten"  # type: ignore[index]
    assert "FR" not in supplement.country_labels(bundle.directory)


def test_reusing_an_existing_wikidata_identity_is_rejected_even_with_reviewed_pins(
    unchanged_base: list[Site], bundle: Bundle,
) -> None:
    existing = next(site.id for site in unchanged_base if site.id.startswith("wd:"))
    bundle.spec["records"][0]["site"]["id"] = existing
    bundle.spec["records"][0]["site"]["geography"]["authority_id"] = "supplement:" + existing
    bundle.compile()
    with pytest.raises(supplement.SupplementError, match="duplicates an existing"):
        supplement.load_supplement(unchanged_base, bundle.directory)


@pytest.mark.parametrize("change", ["count", "text", "order", "country"])
def test_changed_base_cannot_silently_redefine_the_old_corpus_contract(
    unchanged_base: list[Site], bundle: Bundle, change: str,
) -> None:
    changed = unchanged_base.copy()
    if change == "count":
        changed.pop()
    elif change == "text":
        changed[0] = changed[0].model_copy(update={"description": "Changed original source."})
    elif change == "order":
        changed[0], changed[1] = changed[1], changed[0]
    else:
        index = next(index for index, site in enumerate(changed) if site.geography is not None)
        geo = changed[index].geography
        assert geo is not None
        changed[index] = changed[index].model_copy(update={
            "geography": geo.model_copy(update={"countries": ["BT"]}),
        })
    with pytest.raises(supplement.SupplementError, match="unchanged1625"):
        supplement.load_supplement(changed, bundle.directory)


def test_supplement_cannot_relabel_a_country_that_the_base_already_covers(
    unchanged_base: list[Site], bundle: Bundle,
) -> None:
    bundle.monkeypatch.setattr(supplement, "EXPECTED_COUNTRIES", frozenset({"FR", "NU"}))
    bundle.spec["records"][0]["site"]["geography"]["countries"] = ["FR"]
    bundle.spec["records"][0]["country_label"] = "France"
    bundle.compile()
    with pytest.raises(supplement.SupplementError, match="no longer represent"):
        supplement.load_supplement(unchanged_base, bundle.directory)


def test_small_fixture_country_set_does_not_relax_literal_base_count(bundle: Bundle) -> None:
    bundle.spec["base_count"] = 2
    bundle.pin_spec()
    with pytest.raises(supplement.SupplementError, match="1625"):
        supplement.rebuild_supplement(bundle.directory)


@pytest.mark.parametrize("change", ["duplicate-id", "missing-country", "duplicate-country"])
def test_country_selection_and_identity_partition_are_exact(bundle: Bundle, change: str) -> None:
    if change == "duplicate-id":
        bundle.spec["records"].append(copy.deepcopy(bundle.spec["records"][0]))
    elif change == "missing-country":
        bundle.spec["records"].pop()
    else:
        bundle.spec["records"][1]["site"]["geography"]["countries"] = ["BT"]
    bundle.pin_spec()
    with pytest.raises(supplement.SupplementError, match="incomplete or duplicates"):
        supplement.rebuild_supplement(bundle.directory)


@pytest.mark.parametrize(
    ("field", "bad"),
    [("globe", "http://www.wikidata.org/entity/Q405"), ("globe", "Q2"),
     ("rank", "deprecated"), ("rank", "unknown"), ("statement_id", None),
     ("precision", -0.00001), ("precision", float("nan")),
     ("precision", float("inf")), ("source_uri", None)],
)
def test_invalid_wikidata_coordinate_provenance_is_not_relabelled(
    bundle: Bundle, field: str, bad: Any,
) -> None:
    bundle.spec["records"][0]["coordinate"][field] = bad
    bundle.pin_spec()
    with pytest.raises(supplement.SupplementError):
        supplement.rebuild_supplement(bundle.directory)


@pytest.mark.parametrize(
    "change", ["known-point-removed", "unknown-point-invented", "site-only-substitute", "mismatch"],
)
def test_unknown_and_known_source_coordinates_cannot_be_interchanged(
    bundle: Bundle, change: str,
) -> None:
    if change == "known-point-removed":
        bundle.spec["records"][0]["coordinate"]["point"] = None
    elif change == "unknown-point-invented":
        bundle.spec["records"][1]["coordinate"]["point"] = [0, 0]
    elif change == "site-only-substitute":
        bundle.spec["records"][1]["site"]["repr_point"] = [0, 0]
        bundle.spec["records"][1]["site"]["geography"]["point_count"] = 1
    else:
        bundle.spec["records"][0]["coordinate"]["point"] = [0, 0]
    bundle.pin_spec()
    with pytest.raises(supplement.SupplementError):
        supplement.rebuild_supplement(bundle.directory)


def test_selected_coordinate_source_must_be_one_of_the_record_references(bundle: Bundle) -> None:
    bundle.spec["records"][0]["coordinate"]["source_uri"] = "https://example.org/absent"
    bundle.pin_spec()
    with pytest.raises(supplement.SupplementError, match="absent from"):
        supplement.rebuild_supplement(bundle.directory)


@pytest.mark.parametrize("kind", ["pleiades", "global", "unesco"])
def test_nullable_supplement_does_not_relax_older_source_cohorts(
    bundle: Bundle, kind: str,
) -> None:
    raw = copy.deepcopy(bundle.spec["records"][1]["site"])
    raw["source_kind"] = kind
    with pytest.raises(ValueError, match="existing source cohorts require"):
        Site.model_validate(raw)


@pytest.mark.parametrize("change", ["period", "period-evidence", "phase", "chronology-status"])
def test_identity_approval_cannot_smuggle_in_historical_phases_or_periods(
    bundle: Bundle, change: str,
) -> None:
    site = bundle.spec["records"][0]["site"]
    if change == "period":
        site["periods"] = ["roman"]
    elif change == "period-evidence":
        site["period_evidence"] = [{
            "resource_type": "Name", "resource_uri": "https://example.org/name",
            "period_id": "roman", "period_uri": "https://example.org/period",
        }]
    elif change == "chronology-status":
        site["chronology"].update(status="insufficient", reviewed_at="2026-11-04")
    else:
        site["chronology"].update(status="reviewed", reviewed_at="2026-11-04",
                                  default_phase_id="construction")
        site["chronology"]["phases"] = [{
            "id": "construction", "kind": "construction", "label": "Unapproved building date",
            "start_year": 1200, "end_year": 1200, "precision": "exact_year",
            "sources": [reference("qualified-fixture", authority=True)], "note": "",
        }]
    bundle.pin_spec()
    with pytest.raises(supplement.SupplementError):
        supplement.rebuild_supplement(bundle.directory)


@pytest.mark.parametrize("change", ["pending", "reviewer", "method", "date", "missing"])
def test_no_import_without_a_complete_independent_identity_approval(
    bundle: Bundle, change: str,
) -> None:
    record = bundle.spec["records"][0]
    if change == "missing":
        record.pop("independent_review")
    else:
        record["independent_review"][{
            "pending": "status", "reviewer": "reviewer", "method": "method", "date": "reviewed_at",
        }[change]] = {"pending": "pending", "date": "2026-13-40"}.get(change, " ")
    bundle.pin_spec()
    with pytest.raises(supplement.SupplementError):
        supplement.rebuild_supplement(bundle.directory)


@pytest.mark.parametrize("change", ["only-wikidata", "long-excerpt", "split-excerpts"])
def test_cultural_qualification_requires_short_authority_evidence(
    bundle: Bundle, change: str,
) -> None:
    refs = bundle.spec["records"][0]["site"]["source_refs"]
    if change == "only-wikidata":
        refs[0]["license"] = "CC0-1.0"
    elif change == "long-excerpt":
        refs[0]["excerpt"] = " ".join(f"word{index}" for index in range(26))
    else:
        refs[0]["excerpt"] = " ".join(f"first{index}" for index in range(14))
        duplicate = copy.deepcopy(refs[0])
        duplicate["id"] += "-second"
        duplicate["excerpt"] = " ".join(f"second{index}" for index in range(14))
        refs.append(duplicate)
    bundle.pin_spec()
    with pytest.raises(supplement.SupplementError):
        supplement.rebuild_supplement(bundle.directory)


@pytest.mark.parametrize("change", ["sites", "spec", "manifest"])
def test_rehashing_mutated_local_files_cannot_replace_the_independent_review_pin(
    unchanged_base: list[Site], bundle: Bundle, change: str,
) -> None:
    path = bundle.directory / supplement.MANIFEST_FILE
    manifest = json.loads(path.read_bytes())
    if change == "sites":
        target = bundle.directory / supplement.SITES_FILE
        sites = json.loads(target.read_bytes())
        sites[0]["description"] = "Locally edited source summary."
        target.write_bytes(encoded(sites))
        manifest["files"][supplement.SITES_FILE]["sha256"] = digest(target.read_bytes())
    elif change == "spec":
        target = bundle.directory / supplement.SPEC_FILE
        spec = json.loads(target.read_bytes())
        spec["records"][0]["site"]["description"] = "Self approved local edit."
        target.write_bytes(encoded(spec))
        manifest["files"][supplement.SPEC_FILE]["sha256"] = digest(target.read_bytes())
    else:
        manifest["counts"]["unknown_locations"] = 0
    path.write_bytes(encoded(manifest))
    with pytest.raises(supplement.SupplementError):
        supplement.load_supplement(unchanged_base, bundle.directory)


@pytest.mark.parametrize(
    "filename", ["../escape.json", "sub/../../escape.json", "/absolute.json",
                 r"sub\..\..\escape.json", r"\rooted.json", r"C:\absolute.json",
                 r"C:relative.json", r"\\server\share\point.json"],
)
def test_source_artifact_paths_cannot_leave_the_selected_cache(
    bundle: Bundle, filename: str,
) -> None:
    bundle.spec["records"][0]["source_files"][0]["filename"] = filename
    bundle.pin_spec()
    with pytest.raises(supplement.SupplementError, match="inside the chosen cache"):
        supplement.rebuild_supplement(bundle.directory)


def test_source_qualification_without_an_archived_evidence_contract_is_rejected(
    bundle: Bundle,
) -> None:
    bundle.spec["records"][0]["source_files"] = []
    bundle.pin_spec()
    with pytest.raises(supplement.SupplementError):
        supplement.rebuild_supplement(bundle.directory)


@pytest.mark.parametrize("filename", [supplement.SPEC_FILE, supplement.SITES_FILE,
                                      supplement.MANIFEST_FILE])
def test_missing_frozen_input_fails_loading_instead_of_rebuilding_its_own_contract(
    unchanged_base: list[Site], bundle: Bundle, filename: str,
) -> None:
    (bundle.directory / filename).unlink()
    with pytest.raises(supplement.SupplementError):
        supplement.load_supplement(unchanged_base, bundle.directory)


def test_source_cache_validation_deduplicates_shared_archives_and_checks_bytes(
    bundle: Bundle,
) -> None:
    assert supplement.verify_source_cache(bundle.cache, bundle.directory) == 2
    (bundle.cache / "point.json").write_text("changed snapshot", encoding="utf-8")
    with pytest.raises(supplement.SupplementError, match="source snapshot differs"):
        supplement.verify_source_cache(bundle.cache, bundle.directory)


def test_rehashing_a_changed_source_cache_cannot_self_update_the_independent_review(
    bundle: Bundle,
) -> None:
    changed = b'{"P625": {"longitude": 0, "latitude": 0}}\n'
    (bundle.cache / "point.json").write_bytes(changed)
    bundle.spec["records"][0]["source_files"][1]["sha256"] = digest(changed)
    (bundle.directory / supplement.SPEC_FILE).write_bytes(encoded(bundle.spec))
    with pytest.raises(supplement.SupplementError, match="independent pin"):
        supplement.verify_source_cache(bundle.cache, bundle.directory)


def test_source_cache_must_exist_instead_of_being_silently_trusted(bundle: Bundle) -> None:
    (bundle.cache / "point.json").unlink()
    with pytest.raises(supplement.SupplementError):
        supplement.verify_source_cache(bundle.cache, bundle.directory)


def test_source_cache_symlink_cannot_point_outside_the_snapshot_directory(
    tmp_path: Path, bundle: Bundle,
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_bytes((bundle.cache / "point.json").read_bytes())
    link = bundle.cache / "point.json"
    link.unlink()
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("This Windows account cannot create symlinks.")
    with pytest.raises(supplement.SupplementError, match="source snapshot differs"):
        supplement.verify_source_cache(bundle.cache, bundle.directory)


def test_frozen_real_supplement_adds_38_countries_without_rewriting_the_1625_base(
    tmp_path: Path, unchanged_base: list[Site],
) -> None:
    """The actual pinned review must compile offline without a model or source cache."""
    review = supplement.DATA_DIR / supplement.SPEC_FILE
    (tmp_path / supplement.SPEC_FILE).write_bytes(review.read_bytes())
    original_documents = [build_document(site) for site in unchanged_base]
    original_sites = [site.model_dump(mode="json") for site in unchanged_base]
    manifest = supplement.rebuild_supplement(tmp_path)
    loaded = supplement.load_supplement(unchanged_base, tmp_path)

    assert manifest["counts"] == {
        "base": 1625, "added": 38, "countries": 38, "total": 1663,
        "known_locations": 35, "unknown_locations": 3,
    }
    assert len(loaded) == 1663 and len({site.id for site in loaded}) == 1663
    assert all(before is after for before, after in zip(unchanged_base, loaded[:1625], strict=True))
    assert [site.model_dump(mode="json") for site in loaded[:1625]] == original_sites
    assert [build_document(site) for site in loaded[:1625]] == original_documents

    additions = loaded[1625:]
    codes = [site.geography.countries[0] for site in additions if site.geography]
    expected_codes = set(
        "BI BN BS BT BZ CD CF CG CK DJ DM GD GN GQ GW GY KI KW LC LI LR MC MV NR NU "
        "SB SC SL SO SS SZ TL TO TT TV VC WS ZM".split()
    )
    assert len(codes) == len(set(codes)) == 38
    assert set(codes) == supplement.EXPECTED_COUNTRIES == expected_codes
    assert not set(codes) & {
        code for site in unchanged_base if site.geography for code in site.geography.countries
    }
    assert set(supplement.country_labels(tmp_path)) == expected_codes
    assert all(site.source_kind == "supplement" and site.source_refs for site in additions)
    assert all(site.types == ["historic-site"] and not site.periods and not site.period_evidence
               and site.chronology.status == "not_reviewed" and not site.chronology.phases
               and site.chronology.default_phase_id is None for site in additions)
    assert all(site.location_precision is None and site.geography is not None
               and site.geography.point_count == int(site.repr_point is not None)
               for site in additions)
    assert {site.geography.countries[0] for site in additions
            if site.repr_point is None and site.geography} == {"KI", "NR", "NU"}
    assert {record["identity_review"]["status"] for record in manifest["records"]} == {"approved"}

    first_files = {
        filename: (tmp_path / filename).read_bytes()
        for filename in (supplement.SITES_FILE, supplement.MANIFEST_FILE)
    }
    assert {
        filename: (supplement.DATA_DIR / filename).read_bytes() for filename in first_files
    } == first_files
    assert supplement.rebuild_supplement(tmp_path) == manifest
    assert {filename: (tmp_path / filename).read_bytes() for filename in first_files} == first_files


@pytest.fixture(scope="module")
def bundled_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    with TestClient(create_app(home=tmp_path_factory.mktemp("supplement-offline"))) as client:
        yield client


def test_real_api_exposes_197_source_declared_countries_and_independent_supplement_counts(
    bundled_client: TestClient,
) -> None:
    response = bundled_client.get("/api/coverage")
    assert response.status_code == 200
    coverage = response.json()
    assert coverage["corpus_version"] == "global-v6" and coverage["total"] == 1689
    countries = {row["id"]: row for row in coverage["countries"]}
    assert len(countries) == 197
    labels = supplement.country_labels()
    assert all(countries[code]["label"] == label
               and countries[code]["count"] == (2 if code == "CD" else 1)
               for code, label in labels.items())
    previous = json.loads((supplement.DATA_DIR / "catalogue_manifest.json").read_bytes())
    assert len(previous["countries"]) == 159
    assert all(countries[row["id"]]["label"] == row["label"] for row in previous["countries"])
    assert {row["id"]: row["count"] for row in coverage["sources"]} == {
        "pleiades": 500, "global": 100, "unesco": 934, "ats": 91, "supplement": 64,
    }
    assert coverage["locations"] == {"mapped": 1679, "polar": 3, "unknown": 7}
    assert coverage["authority"]["covered"] == coverage["authority"]["eligible_total"] == 1033
    assert coverage["polar_authority"]["covered"] == 91
    spatial = coverage["spatial_locations"]
    assert spatial["ready"] and spatial["records"] == 1033 and spatial["points"] == 5632
    assert spatial["display_points"] == 6069
    status = bundled_client.get("/api/status").json()
    assert status["corpus"]["count"] == 1689 and status["corpus"]["version"] == "global-v6"
    assert status["semantic"]["ready"] is False and status["history"]["ready"] is False


@pytest.mark.parametrize(("code", "identifier"), [
    ("KI", "auth:dva:betio-coast-watchers-memorial"),
    ("NR", "auth:sprep:d6eab109-2e10-4654-b3c4-5bb94f6a8867"),
    ("NU", "auth:commonwealth:67579"),
])
def test_real_unknown_authority_records_remain_browsable_searchable_and_unmapped(
    bundled_client: TestClient, code: str, identifier: str,
) -> None:
    response = bundled_client.get("/api/catalogue", params={"country": code})
    assert response.status_code == 200
    catalogue = response.json()
    assert catalogue["total"] == 1
    point = catalogue["points"][0]
    assert point["id"] == identifier and point["source_kind"] == "supplement"
    assert point["countries"] == [code] and point["chronology_status"] == "not_reviewed"
    assert point["repr_point"] is None and point["location_status"] == "unknown"
    assert point["source_points"] == point["source_location_records"] == []

    uri = "/api/sites/" + quote(identifier, safe="")
    detail_response = bundled_client.get(uri)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["repr_point"] is None and detail["location_precision"] is None
    assert detail["geography"]["countries"] == [code]
    assert detail["geography"]["point_count"] == 0
    assert detail["chronology"]["status"] == "not_reviewed" and not detail["chronology"]["phases"]
    assert detail["source_refs"] and detail["source_uri"].startswith("https://")
    page = bundled_client.get("/api/sites", params={"country": code, "limit": 1}).json()
    assert page["total"] == 1 and page["sites"] == [detail]

    locations = bundled_client.get(uri + "/locations")
    assert locations.status_code == 200
    assert locations.json()["representative_point"] is None
    assert locations.json()["source_points"] == locations.json()["source_location_records"] == []
    assert locations.json()["source"] is None

    result = bundled_client.post("/api/search", json={
        "query": detail["title"], "mode": "bm25", "country": code, "limit": 10,
    })
    assert result.status_code == 200
    assert result.json()["total_candidates"] == 1
    assert [hit["site"]["id"] for hit in result.json()["results"]] == [identifier]
    assert result.json()["results"][0]["site"]["repr_point"] is None
