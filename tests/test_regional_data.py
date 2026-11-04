"""Offline regional-cohort fixtures and immutable base/source integrity boundaries."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from archsearch import regional_data as regional
from archsearch.api import create_app
from archsearch.catalogue_data import load_catalogue
from archsearch.corpus import build_document, load_curated_corpus, load_pre_nps_corpus
from archsearch.domain import Site
from archsearch.evaluation import evaluate_corpus, load_queries, query_contract_hash
from archsearch.polar_data import load_polar
from archsearch.supplement_data import load_supplement


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def reference(identifier: str, *, authority: bool = False) -> dict[str, Any]:
    return {
        "id": identifier, "title": "Fixture cultural authority" if authority else "Fixture point",
        "uri": f"https://example.org/{identifier}", "publisher": "Fixture source",
        "license": None if authority else "CC0-1.0", "revision": "fixed-fixture-v1",
        "accessed": "2026-11-04", "excerpt": "Documented cultural object." if authority else "",
    }


def site_value(identifier: str, country: str, point: list[float] | None) -> dict[str, Any]:
    authority = reference("qualification:fixture", authority=True)
    coordinate = reference("point-fixture")
    return {
        "id": identifier, "title": "Fixture cultural place " + identifier,
        "description": "Unaltered source description.", "description_zh": "",
        "details": f"Source country association: {country}.", "names": ["Fixture alias"],
        "types": ["historic-site"], "periods": [], "repr_point": point,
        "location_precision": None, "source_uri": authority["uri"],
        "contributors": ["Fixture contributor"], "period_evidence": [],
        "source_kind": "supplement", "source_refs": [authority, coordinate],
        "chronology": {
            "status": "not_reviewed", "method": "fixture identity and source comparison",
            "reviewed_at": None, "note": "No historical stage has been verified.",
            "default_phase_id": None, "phases": [],
        },
        "geography": {
            "authority_id": "supplement:" + identifier, "countries": [country],
            "regions": ["europe-north-america"], "source": coordinate,
            "point_count": int(point is not None),
            "note": "Declared source association; no inferred historical political attribution.",
        },
    }


@pytest.fixture(scope="module")
def base1663() -> list[Site]:
    """Synthetic fixed data only: no production corpus, source archive or model is loaded."""
    return [
        Site.model_validate(site_value(
            f"wd:Q{800000000 + index}", "CA" if index % 2 == 0 else "FR",
            [-100.0, 60.0] if index % 2 == 0 else [-151.0, -16.0],
        ))
        for index in range(1663)
    ]


def reviewed_record(
    identifier: str, country: str, point: list[float] | None, focus: str,
) -> dict[str, Any]:
    return {
        "site": site_value(identifier, country, point), "country_label": country,
        "coordinate": {
            "method": "authority" if point is not None else "unknown", "point": point,
            "source_uri": reference("point-fixture")["uri"] if point is not None else None,
            "statement_id": None, "globe": None, "precision": None, "rank": None,
            "note": "Explicit same-object source point." if point else "No verified public point.",
        },
        "independent_review": {
            "status": "approved", "reviewer": "independent-fixture-agent",
            "method": "Compared physical cultural identity and selected source point.",
            "reviewed_at": "2026-11-04",
        },
        "source_files": [], "provenance": {"fixture": True, "historical_dates_inferred": False},
        "focus": focus,
    }


@dataclass
class Bundle:
    directory: Path
    cache: Path
    spec: dict[str, Any]
    monkeypatch: pytest.MonkeyPatch

    def pin_spec(self) -> None:
        payload = encoded(self.spec)
        (self.directory / regional.SPEC_FILE).write_bytes(payload)
        self.monkeypatch.setattr(regional, "SPEC_SHA256", digest(payload))

    def compile(self) -> dict[str, Any]:
        self.pin_spec()
        records = sorted(self.spec["records"], key=lambda row: (
            digest(("regional-supplement-v1:" + row["site"]["id"]).encode()), row["site"]["id"],
        ))
        sites = [Site.model_validate(row["site"]).model_dump(mode="json") for row in records]
        self.monkeypatch.setattr(regional, "SITES_SHA256", digest(encoded(sites)))
        return regional.rebuild_regional(self.directory)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base1663: list[Site]) -> Bundle:
    directory = tmp_path / "data"
    directory.mkdir()
    cache = tmp_path / "source-cache"
    cache.mkdir()
    artifacts = []
    for filename, value in (
        ("authority.json", {"qualification": "Documented cultural object."}),
        ("point.json", {"longitude": -100, "latitude": 75}),
    ):
        payload = encoded(value)
        (cache / filename).write_bytes(payload)
        artifacts.append({"filename": filename, "sha256": digest(payload),
                          "uri": f"https://example.org/{filename}"})
    records = [
        reviewed_record("auth:fixture:north-1", "CA", [-100.0, 75.0], "northern"),
        reviewed_record("auth:fixture:island-1", "FR", None, "islands-interior"),
    ]
    records[0]["source_files"] = copy.deepcopy(artifacts)
    records[1]["source_files"] = [copy.deepcopy(artifacts[0])]
    base_sites = [site.model_dump(mode="json") for site in base1663]
    spec = {
        "schema_version": 1, "cohort_version": "regional-supplement-v1",
        "corpus_version": "global-v6", "base_count": len(base1663),
        "base_ids_sha256": digest(encoded([site.id for site in base1663])),
        "base_sites_sha256": digest(encoded(base_sites)),
        "selection": "Fixed independently reviewed northern and island fixtures.",
        "records": records,
    }
    result = Bundle(directory, cache, spec, monkeypatch)
    result.compile()
    return result


def test_append_preserves_1663_objects_text_order_and_unknown_location(
    bundle: Bundle, base1663: list[Site],
) -> None:
    before = [site.model_dump(mode="json") for site in base1663]
    documents = [build_document(site) for site in base1663]
    loaded = regional.load_regional(base1663, bundle.directory)
    assert len(loaded) == 1665
    assert all(old is new for old, new in zip(base1663, loaded[:1663], strict=True))
    assert [site.model_dump(mode="json") for site in loaded[:1663]] == before
    assert [build_document(site) for site in loaded[:1663]] == documents
    new = {site.id: site for site in loaded[1663:]}
    assert new["auth:fixture:north-1"].repr_point == (-100, 75)
    unknown = new["auth:fixture:island-1"]
    assert unknown.repr_point is None and unknown.geography is not None
    assert unknown.geography.point_count == 0 and unknown.location_precision is None
    assert all(site.chronology.status == "not_reviewed" and not site.chronology.phases
               for site in new.values())


def test_two_offline_compilations_are_byte_identical_and_preserve_both_focuses(
    bundle: Bundle, base1663: list[Site],
) -> None:
    before = {name: (bundle.directory / name).read_bytes()
              for name in (regional.SITES_FILE, regional.MANIFEST_FILE)}
    manifest = regional.rebuild_regional(bundle.directory)
    assert before == {name: (bundle.directory / name).read_bytes() for name in before}
    assert manifest["counts"] == {
        "base": 1663, "added": 2, "total": 1665, "known_locations": 1,
        "no_verified_coordinate": 1, "northern": 1, "islands_interior": 1,
    }
    focuses = {row["id"]: row["focus"] for row in manifest["records"]}
    assert focuses == {
        "auth:fixture:north-1": "northern", "auth:fixture:island-1": "islands-interior",
    }
    original_ids = [site.id for site in regional.load_regional(base1663, bundle.directory)][1663:]
    bundle.spec["records"].reverse()
    bundle.compile()
    assert (bundle.directory / regional.SITES_FILE).read_bytes() == before[regional.SITES_FILE]
    assert [site.id for site in regional.load_regional(base1663, bundle.directory)][1663:] == (
        original_ids
    )


@pytest.mark.parametrize("change", ["text", "point", "country", "order", "count"])
def test_base_content_order_and_count_changes_cannot_use_the_old_contract(
    bundle: Bundle, base1663: list[Site], change: str,
) -> None:
    altered = list(base1663)
    if change == "text":
        altered[0] = altered[0].model_copy(update={"description": "Changed source text."})
    elif change == "point":
        altered[0] = altered[0].model_copy(update={"repr_point": (-101.0, 60.0)})
    elif change == "country":
        assert altered[0].geography is not None
        altered[0] = altered[0].model_copy(update={
            "geography": altered[0].geography.model_copy(update={"countries": ["US"]}),
        })
    elif change == "order":
        altered.reverse()
    else:
        altered.pop()
    with pytest.raises(regional.RegionalError, match="unchanged1663"):
        regional.load_regional(altered, bundle.directory)


def test_existing_identity_is_rejected_after_repinning_reviewed_fixture(
    bundle: Bundle, base1663: list[Site],
) -> None:
    site = bundle.spec["records"][0]["site"]
    site["id"] = base1663[0].id
    site["geography"]["authority_id"] = "supplement:" + site["id"]
    bundle.compile()
    with pytest.raises(regional.RegionalError, match="existing identity"):
        regional.load_regional(base1663, bundle.directory)


def test_duplicate_new_identity_cannot_be_hidden_by_distinct_focus_labels(bundle: Bundle) -> None:
    site = bundle.spec["records"][1]["site"]
    site["id"] = bundle.spec["records"][0]["site"]["id"]
    site["geography"]["authority_id"] = "supplement:" + site["id"]
    bundle.pin_spec()
    with pytest.raises(regional.RegionalError, match="duplicates an identity"):
        regional.rebuild_regional(bundle.directory)


@pytest.mark.parametrize("change", ["country", "region"])
def test_existing_registry_cannot_gain_unknown_countries_or_regions(
    bundle: Bundle, base1663: list[Site], change: str,
) -> None:
    geography = bundle.spec["records"][0]["site"]["geography"]
    geography["countries" if change == "country" else "regions"] = (
        ["ZZ"] if change == "country" else ["africa"]
    )
    bundle.compile()
    with pytest.raises(regional.RegionalError, match="existing label registry"):
        regional.load_regional(base1663, bundle.directory)


@pytest.mark.parametrize("focus", ["northern", "islands-interior", "other", None])
def test_selection_cannot_drop_a_focus_or_invent_another_focus(
    bundle: Bundle, focus: str | None,
) -> None:
    for row in bundle.spec["records"]:
        row["focus"] = focus
    bundle.pin_spec()
    with pytest.raises(regional.RegionalError):
        regional.rebuild_regional(bundle.directory)


@pytest.mark.parametrize("target", ["spec", "sites", "manifest", "manifest-focus"])
def test_edited_files_cannot_self_sign_new_pins_through_the_manifest(
    bundle: Bundle, base1663: list[Site], target: str,
) -> None:
    path = bundle.directory / regional.MANIFEST_FILE
    manifest = json.loads(path.read_bytes())
    if target == "spec":
        bundle.spec["records"][0]["site"]["description"] = "Self approved edit."
        changed = bundle.directory / regional.SPEC_FILE
        changed.write_bytes(encoded(bundle.spec))
        manifest["files"][regional.SPEC_FILE]["sha256"] = digest(changed.read_bytes())
    elif target == "sites":
        changed = bundle.directory / regional.SITES_FILE
        sites = json.loads(changed.read_bytes())
        sites[0]["repr_point"] = [0, 0]
        changed.write_bytes(encoded(sites))
        manifest["files"][regional.SITES_FILE]["sha256"] = digest(changed.read_bytes())
    elif target == "manifest-focus":
        manifest["records"][0]["focus"] = "fabricated-focus"
    else:
        manifest["counts"]["no_verified_coordinate"] = 0
    path.write_bytes(encoded(manifest))
    with pytest.raises(regional.RegionalError):
        regional.load_regional(base1663, bundle.directory)


def test_compiler_requires_an_independent_output_pin_not_only_a_review_pin(bundle: Bundle) -> None:
    bundle.spec["records"][0]["site"]["description"] = "Approved spec, unapproved new output."
    bundle.pin_spec()
    with pytest.raises(regional.RegionalError, match="independent pin"):
        regional.rebuild_regional(bundle.directory)


@pytest.mark.parametrize("filename", [regional.SPEC_FILE, regional.SITES_FILE,
                                      regional.MANIFEST_FILE])
def test_missing_bundled_material_never_silently_recreates_its_own_contract(
    bundle: Bundle, base1663: list[Site], filename: str,
) -> None:
    (bundle.directory / filename).unlink()
    with pytest.raises(regional.RegionalError):
        regional.load_regional(base1663, bundle.directory)
    assert not (bundle.directory / filename).exists()


def test_source_hash_checks_deduplicate_shared_archives_and_reject_changed_bytes(
    bundle: Bundle,
) -> None:
    assert regional.verify_source_cache(bundle.cache, bundle.directory) == 2
    (bundle.cache / "point.json").write_text("changed", "utf-8")
    with pytest.raises(regional.RegionalError, match="source snapshot differs"):
        regional.verify_source_cache(bundle.cache, bundle.directory)


def test_source_cache_cannot_update_the_frozen_review_to_trust_itself(bundle: Bundle) -> None:
    payload = b'{"longitude":0,"latitude":0}\n'
    (bundle.cache / "point.json").write_bytes(payload)
    bundle.spec["records"][0]["source_files"][1]["sha256"] = digest(payload)
    (bundle.directory / regional.SPEC_FILE).write_bytes(encoded(bundle.spec))
    with pytest.raises(regional.RegionalError, match="independent pin"):
        regional.verify_source_cache(bundle.cache, bundle.directory)


def test_evidence_cache_is_optional_for_compilation_but_explicit_verification_requires_it(
    bundle: Bundle,
) -> None:
    for path in bundle.cache.iterdir():
        path.unlink()
    regional.rebuild_regional(bundle.directory)
    with pytest.raises(regional.RegionalError):
        regional.verify_source_cache(bundle.cache, bundle.directory)


@pytest.mark.parametrize(
    "filename", ["../escape.json", "sub/../../escape.json", "/absolute.json",
                 r"sub\..\..\escape.json", r"\rooted.json", r"C:\absolute.json",
                 r"C:relative.json", r"\\server\share\evidence.json"],
)
def test_source_snapshot_paths_cannot_escape_the_chosen_cache(
    bundle: Bundle, filename: str,
) -> None:
    bundle.spec["records"][0]["source_files"][0]["filename"] = filename
    bundle.pin_spec()
    with pytest.raises(regional.RegionalError, match="inside the chosen cache"):
        regional.rebuild_regional(bundle.directory)


@pytest.mark.parametrize("field", ["uri", "sha256"])
def test_a_shared_cache_filename_cannot_have_conflicting_hash_or_origin(
    bundle: Bundle, field: str,
) -> None:
    bundle.spec["records"][1]["source_files"][0][field] = (
        "https://other.example.org/data" if field == "uri" else "b" * 64
    )
    bundle.pin_spec()
    with pytest.raises(regional.RegionalError, match="conflicting contracts"):
        regional.rebuild_regional(bundle.directory)


def test_external_symlink_is_rejected_even_when_its_bytes_match(
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
    with pytest.raises(regional.RegionalError, match="source snapshot differs"):
        regional.verify_source_cache(bundle.cache, bundle.directory)


@pytest.mark.parametrize("change", ["missing-review", "empty-evidence", "unreviewed", "no-culture"])
def test_identity_approval_archived_evidence_and_cultural_qualification_are_required(
    bundle: Bundle, change: str,
) -> None:
    row = bundle.spec["records"][0]
    if change == "missing-review":
        row.pop("independent_review")
    elif change == "empty-evidence":
        row["source_files"] = []
    elif change == "unreviewed":
        row["independent_review"]["status"] = "pending"
    else:
        row["site"]["source_refs"][0]["license"] = "CC0-1.0"
    bundle.pin_spec()
    with pytest.raises(regional.RegionalError):
        regional.rebuild_regional(bundle.directory)


@pytest.fixture(scope="module")
def unchanged_real1663() -> list[Site]:
    return load_supplement(load_polar(load_catalogue(load_curated_corpus())))


def test_real_review_compiles_twice_offline_without_rewriting_1663_records(
    tmp_path: Path, unchanged_real1663: list[Site],
) -> None:
    """The checked-in review alone reproduces both published derived files byte for byte."""
    before = [site.model_dump(mode="json") for site in unchanged_real1663]
    documents = [build_document(site) for site in unchanged_real1663]
    (tmp_path / regional.SPEC_FILE).write_bytes(
        (regional.DATA_DIR / regional.SPEC_FILE).read_bytes(),
    )
    manifest = regional.rebuild_regional(tmp_path)
    published = {
        name: (regional.DATA_DIR / name).read_bytes()
        for name in (regional.SITES_FILE, regional.MANIFEST_FILE)
    }
    assert {name: (tmp_path / name).read_bytes() for name in published} == published
    assert regional.rebuild_regional(tmp_path) == manifest
    assert {name: (tmp_path / name).read_bytes() for name in published} == published
    loaded = regional.load_regional(unchanged_real1663, tmp_path)
    assert len(loaded) == len({site.id for site in loaded}) == 1689
    assert all(old is new for old, new in zip(unchanged_real1663, loaded[:1663], strict=True))
    assert [site.model_dump(mode="json") for site in loaded[:1663]] == before
    assert [build_document(site) for site in loaded[:1663]] == documents
    assert [site.model_dump(mode="json") for site in load_pre_nps_corpus()[:1689]] == [
        site.model_dump(mode="json") for site in loaded
    ]
    assert manifest["counts"] == {
        "base": 1663, "added": 26, "total": 1689, "known_locations": 23,
        "no_verified_coordinate": 3, "northern": 12, "islands_interior": 14,
    }
    additions = loaded[1663:]
    assert Counter(record["focus"] for record in manifest["records"]) == {
        "northern": 12, "islands-interior": 14,
    }
    assert {record["identity_review"]["status"] for record in manifest["records"]} == {
        "approved",
    }
    assert {site.id for site in additions if site.repr_point is None} == {
        "wd:Q4167852", "wd:Q7679508", "auth:pf-dcp:marae-arahurahu",
    }
    assert all(site.source_kind == "supplement" and site.source_refs
               and site.geography is not None
               and site.geography.authority_id == "supplement:" + site.id
               and site.geography.point_count == int(site.repr_point is not None)
               and site.location_precision is None
               and site.chronology.status == "not_reviewed"
               and site.chronology.phases == [] and site.chronology.default_phase_id is None
               and site.periods == [] and site.period_evidence == [] for site in additions)


def test_regional_extension_preserves_all_600_original_chronology_reviews(
    unchanged_real1663: list[Site],
) -> None:
    raw_reviews = json.loads((regional.DATA_DIR / "chronology.json").read_bytes())
    curated = load_curated_corpus()
    loaded = regional.load_regional(unchanged_real1663)
    assert len(curated) == len(raw_reviews) == 600
    assert [site.id for site in loaded[:600]] == [site.id for site in curated]
    assert [site.chronology.model_dump(mode="json") for site in loaded[:600]] == [
        site.chronology.model_dump(mode="json") for site in curated
    ]
    assert all(site.chronology.status == raw_reviews[site.id]["status"]
               for site in loaded[:600])
    assert Counter(site.chronology.status for site in loaded[:500]) == {
        "reviewed": 49, "insufficient": 451,
    }
    assert Counter(site.chronology.status for site in loaded[500:600]) == {"reviewed": 100}


@pytest.fixture(scope="module")
def regional_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    with TestClient(create_app(home=tmp_path_factory.mktemp("regional-offline"))) as client:
        yield client


def test_real_current_api_preserves_regional_locations_and_source_membership(
    regional_client: TestClient, unchanged_real1663: list[Site],
) -> None:
    coverage = regional_client.get("/api/coverage").json()
    assert coverage["corpus_version"] == "global-v12" and coverage["total"] == 1999
    assert {row["id"] for row in coverage["countries"]} == {
        code for site in unchanged_real1663 if site.geography for code in site.geography.countries
    } | {"AS", "GU", "MP", "UM", "NF"}
    assert len(coverage["countries"]) == 202 and len(coverage["regions"]) == 7
    assert {row["id"]: row["count"] for row in coverage["sources"]} == {
        "pleiades": 500, "global": 100, "unesco": 934, "ats": 91, "supplement": 374,
    }
    assert coverage["locations"] == {"mapped": 1898, "polar": 3, "unknown": 98}
    assert coverage["spatial_locations"]["ready"] is True
    assert coverage["spatial_locations"]["points"] == 5851
    assert coverage["spatial_locations"]["display_points"] == 6301
    assert coverage["authority"]["covered"] == coverage["authority"]["eligible_total"] == 1033
    assert coverage["polar_authority"]["covered"] == 91
    status = regional_client.get("/api/status").json()
    assert status["corpus"]["count"] == 1999 and status["corpus"]["version"] == "global-v12"
    assert status["semantic"]["ready"] is False
    assert status["history"]["ready"] is False
    catalogue = regional_client.get("/api/catalogue").json()
    assert catalogue["total"] == len(catalogue["points"]) == 1999
    assert Counter(point["location_status"] for point in catalogue["points"]) == {
        "mapped": 1898, "polar": 3, "unknown": 98,
    }


@pytest.mark.parametrize(("identifier", "point", "country", "region"), [
    ("wd:Q3077812", [-64.75, 81.75], "CA", "europe-north-america"),
    ("wd:Q97066659", [152.71666666666667, 76.13333333333334], "RU", "europe-north-america"),
    ("wd:Q18399201", [135.4297222222222, 70.72361111111111], "RU", "europe-north-america"),
    ("auth:crhp:1167", [-115.36861, 67.74], "CA", "europe-north-america"),
    ("auth:whc-tentative:6331", [10.077777777777778, 5.85861111111111], "CM", "africa"),
    ("auth:rbins:ishango", [29.600555555555555, -0.12694444444444444], "CD", "africa"),
])
def test_real_new_source_points_preserve_longitude_latitude_and_authority_identity(
    regional_client: TestClient, identifier: str, point: list[float], country: str, region: str,
) -> None:
    response = regional_client.get("/api/sites/" + quote(identifier, safe=""))
    assert response.status_code == 200
    detail = response.json()
    assert detail["repr_point"] == point and detail["location_precision"] is None
    assert detail["geography"]["authority_id"] == "supplement:" + identifier
    assert detail["geography"]["countries"] == [country]
    assert detail["geography"]["regions"] == [region]
    assert detail["geography"]["point_count"] == 1
    assert detail["chronology"]["status"] == "not_reviewed"
    assert detail["chronology"]["phases"] == []
    filtered = regional_client.get("/api/catalogue", params={
        "country": country, "region": region,
    }).json()
    entry = next(row for row in filtered["points"] if row["id"] == identifier)
    assert entry["repr_point"] == point and entry["location_status"] == "mapped"
    assert entry["source_points"] == entry["source_location_records"] == []


@pytest.mark.parametrize(("identifier", "country", "region"), [
    ("wd:Q4167852", "US", "europe-north-america"),
    ("wd:Q7679508", "FR", "asia-pacific"),
    ("auth:pf-dcp:marae-arahurahu", "FR", "asia-pacific"),
])
def test_real_unknown_regional_objects_remain_browsable_and_searchable(
    regional_client: TestClient, identifier: str, country: str, region: str,
) -> None:
    uri = "/api/sites/" + quote(identifier, safe="")
    detail = regional_client.get(uri).json()
    assert detail["id"] == identifier and detail["repr_point"] is None
    assert detail["location_precision"] is None and detail["geography"]["point_count"] == 0
    assert detail["chronology"]["status"] == "not_reviewed"
    assert detail["chronology"]["phases"] == []
    catalogue = regional_client.get("/api/catalogue", params={
        "country": country, "region": region,
    }).json()
    point = next(row for row in catalogue["points"] if row["id"] == identifier)
    assert point["repr_point"] is None and point["location_status"] == "unknown"
    assert point["source_points"] == point["source_location_records"] == []
    page = regional_client.get("/api/sites", params={
        "country": country, "region": region, "limit": 100,
    }).json()
    assert next(site for site in page["sites"] if site["id"] == identifier) == detail
    locations = regional_client.get(uri + "/locations").json()
    assert locations["representative_point"] is None and locations["source"] is None
    assert locations["source_points"] == locations["source_location_records"] == []
    search = regional_client.post("/api/search", json={
        "query": detail["title"], "mode": "bm25", "country": country,
        "region": region, "limit": 50,
    })
    assert search.status_code == 200
    assert next(hit["site"] for hit in search.json()["results"]
                if hit["site"]["id"] == identifier) == detail


@pytest.mark.parametrize(("country", "region", "included", "excluded"), [
    ("US", "asia-pacific", {"wd:Q4930787", "wd:Q15226028", "wd:Q22950225"},
     {"wd:Q4167852"}),
    ("FR", "asia-pacific", {"wd:Q7679508", "auth:pf-dcp:marae-arahurahu", "wd:Q16536581"},
     {"wd:Q3077812"}),
    ("DK", "europe-north-america", {"wd:Q1817250", "wd:Q3957914"},
     {"wd:Q4930787"}),
])
def test_shared_country_filters_preserve_separate_objects_and_source_regions(
    regional_client: TestClient, country: str, region: str,
    included: set[str], excluded: set[str],
) -> None:
    params = {"country": country, "region": region}
    catalogue = regional_client.get("/api/catalogue", params=params).json()
    identifiers = {point["id"] for point in catalogue["points"]}
    assert included <= identifiers and not excluded & identifiers
    page = regional_client.get("/api/sites", params={**params, "limit": 100}).json()
    assert page["total"] == catalogue["total"]
    assert {site["id"] for site in page["sites"]} == identifiers
    assert all(country in point["countries"] and region in point["regions"]
               for point in catalogue["points"])
    search = regional_client.post("/api/search", json={
        "query": "historic archaeological", "mode": "bm25", **params, "limit": 50,
    })
    assert search.status_code == 200
    assert {hit["site"]["id"] for hit in search.json()["results"]} <= identifiers


def test_regional_20_paired_queries_create_rankings_and_unscored_manual_template(
    tmp_path: Path,
) -> None:
    queries_file = regional.DATA_DIR / "queries-regional.json"
    pairs = load_queries(queries_file)
    assert len(pairs) == len({pair.id for pair in pairs}) == 20
    assert [pair.id for pair in pairs] == [f"r{index:02d}" for index in range(1, 21)]
    assert all(any("\u4e00" <= character <= "\u9fff" for character in pair.query_zh)
               and pair.query_en.isascii() and pair.query_zh != pair.query_en for pair in pairs)
    report = evaluate_corpus(tmp_path / "empty-home", tmp_path / "regional.json",
                             queries=queries_file)
    assert report["corpus_count"] == 1999
    assert report["query_contract_sha256"] == query_contract_hash(pairs)
    assert report["metrics"] is None and report["metric_gate_reasons"]
    assert report["status"] == "retrieval_incomplete" and report["runs_complete"] is False
    assert report["semantic_ready"] is False and report["qrels"]["confirmed"] is False
    assert set(report["runs"]) == {"bm25_zh", "bm25_en", "semantic_zh", "semantic_en"}
    for run_id, run in report["runs"].items():
        assert [row["query_id"] for row in run["queries"]] == [pair.id for pair in pairs]
        assert all(row["error"] is None and row["elapsed_ms"] is not None
                   if run_id.startswith("bm25_")
                   else row["error"] and row["elapsed_ms"] is None and row["results"] == []
                   for row in run["queries"])
    template = json.loads(Path(report["artifacts"]["qrels_template"]).read_bytes())
    assert template["confirmed"] is False and template["assessor"] == ""
    assert template["judgments"]
    assert all(row["relevance"] is None and row["evidence"] == ""
               for row in template["judgments"])


def test_19_translations_preserve_frozen_english_and_identify_agent_processing() -> None:
    expected_english = {
        "wd:Q130394231": "telegraph station in the Northern Territory",
        "wd:Q1373400": "heritage-listed telegraph station in the Alice Springs, Australia",
        "wd:Q15226028": "archeological site",
        "wd:Q15229078": "national reserve on Chatham Island in New Zealand",
        "wd:Q16536581": "cathedral located in Polynésie française, in France",
        "wd:Q1688000": "defunct town in Russia",
        "wd:Q1817250": "an archaeological site on Nuussuaq Peninsula in Greenland",
        "wd:Q18399201": "upper Palaeolithic site in northeastern Siberia",
        "wd:Q19870764": "protected area in the Northern Territory, Australia",
        "wd:Q22547674": "island in Nunavut, Canada",
        "wd:Q22950225": "small public park and archaeological site in Dededo, Guam",
        "wd:Q28219735": "historic building in the Northern Territory, Australia",
        "wd:Q3077812": "building in Nunavut, Canada",
        "wd:Q38148545": "indigenous national heritage site in Alice Springs NT",
        "wd:Q3957914": "hamlet in Avannaata, Greenland",
        "wd:Q4167852": "archaeological type site",
        "wd:Q668401": "Ekven Cemetery Site",
        "wd:Q7679508": (
            "archaeological site in Wallis and Futuna in the southwestern part of the Pacific Ocean"
        ),
        "wd:Q97066659": "mesolithic site in Siberia",
    }
    spec = json.loads((regional.DATA_DIR / regional.SPEC_FILE).read_bytes())
    translated = {
        row["site"]["id"]: row for row in spec["records"]
        if "description_zh_translation" in row["provenance"]
    }
    assert len(translated) == 19 and set(translated) == set(expected_english)
    for identifier, row in translated.items():
        site = Site.model_validate(row["site"])
        translation = row["provenance"]["description_zh_translation"]
        source = translation["source"]
        assert site.description == translation["original_en"] == expected_english[identifier]
        assert site.description_zh == translation["translated_zh"] and site.description_zh
        assert translation["id"] == identifier
        assert translation["method"] == "agent_translation_from_frozen_wikidata_en_description"
        assert translation["original_wikidata_zh"] is False
        assert translation["review_status"] == "approved"
        assert translation["reviewer"] == "independent-agent:/root/coverage_sources"
        assert translation["candidate_file_sha256"] == (
            "d80393d80c4895a7c028f92f19636e75211294085b4bc88b5e69f33a3540e887"
        )
        assert translation["independent_report_sha256"] == (
            "ae6745a713012e0e12b006981d91353570974279ca32f44c68bdcaab5f1f11dc"
        )
        assert source["field"] == "descriptions.en.value" and source["license"] == "CC0-1.0"
        qid = identifier.removeprefix("wd:")
        assert source["entity_uri"] == "https://www.wikidata.org/wiki/" + qid
        assert f"Special:EntityData/{qid}.json" in source["uri"]
        assert type(source["revision"]) is int and source["revision"] > 0
        assert {
            "filename": source["cache"], "sha256": source["sha256"], "uri": source["uri"],
        } in row["source_files"]
        original_reference = next(reference for reference in site.source_refs
                                  if reference.uri == source["entity_uri"]
                                  and reference.id != "translation:wikidata:" + qid)
        assert original_reference.license == "CC0-1.0"
        assert str(source["revision"]) == (original_reference.revision or "").split(";")[0]
        references = [reference for reference in site.source_refs
                      if reference.id.startswith("translation:")]
        assert len(references) == 1
        reference = references[0]
        assert reference.id == "translation:wikidata:" + qid
        assert reference.uri == source["entity_uri"] and reference.license == "CC0-1.0"
        assert reference.excerpt == expected_english[identifier]
        assert reference.revision == (
            f"{source['revision']}; field: descriptions.en.value; sha256:{source['sha256']}"
        )
        assert reference.publisher == "本项目代理译文；原文：Wikidata contributors"
        assert reference.title == "本项目中文译文（据 Wikidata 英文短描述，非原有中文字段）"
        assert site.description_zh in build_document(site)
    remaining = [row["site"] for row in spec["records"]
                 if row["site"]["id"] not in translated]
    assert len(remaining) == 7
    assert all(not any(reference["id"].startswith("translation:")
                       for reference in site["source_refs"]) for site in remaining)
    assert {site["id"]: site["description_zh"] for site in remaining
            if site["description_zh"]} == {"wd:Q174072": "俄罗斯人类聚居点"}
    assert all(site["description"] == site["description_zh"] == ""
               for site in remaining if site["id"] != "wd:Q174072")


def test_northern_metadata_roles_cannot_contribute_cultural_qualification_text() -> None:
    spec = json.loads((regional.DATA_DIR / regional.SPEC_FILE).read_bytes())
    northern = [Site.model_validate(row["site"]) for row in spec["records"]
                if row["focus"] == "northern"]
    metadata_prefixes = ("region:", "association:", "location-restriction:", "location:")
    metadata = [(site, reference) for site in northern for reference in site.source_refs
                if reference.id.startswith(metadata_prefixes)]
    assert len(northern) == 12 and len(metadata) == 17
    assert Counter(reference.id.split(":", 1)[0] for _, reference in metadata) == {
        "region": 12, "association": 2, "location-restriction": 1, "location": 2,
    }
    for site, reference in metadata:
        assert not reference.id.startswith("qualification:")
        if reference.id.startswith("region:"):
            assert reference.uri.startswith("https://whc.unesco.org/en/statesparties/")
        elif reference.id.startswith("association:"):
            assert reference.id == "association:greenland-member.html"
            assert reference.uri == "https://whc.unesco.org/en/list/1149/"
        elif reference.id.startswith("location-restriction:"):
            assert site.id == "wd:Q4167852"
            assert reference.uri == "https://npgallery.nps.gov/AssetDetail/NRIS/66000157"
        else:
            assert reference.uri.startswith("https://www.historicplaces.ca/en/rep-reg/")
        marker = f"metadata-only-probe-{site.id}-{reference.id}"
        probe = site.model_copy(update={
            "source_refs": [candidate.model_copy(update={"excerpt": marker})
                            if candidate is reference else candidate
                            for candidate in site.source_refs],
        })
        assert build_document(probe) == build_document(site)
        assert marker not in build_document(probe)
    expected_geography_roles = {
        "auth:crhp:1167": "location:historic-bloody.html",
        "wd:Q4802400": "location:historic-arviajuaq.html",
        "wd:Q4167852": "location-restriction:ipiutak-restricted.html",
    }
    for identifier, role in expected_geography_roles.items():
        site = next(site for site in northern if site.id == identifier)
        assert site.geography is not None and site.geography.source.id == role
        assert site.geography.source == next(reference for reference in site.source_refs
                                             if reference.id == role)
