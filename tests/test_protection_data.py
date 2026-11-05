"""Reviewed Hague facts preserve source scope without inventing locations or chronology."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from archsearch import protection_data as cohort
from archsearch.bounds import SpatialBounds
from archsearch.catalogue_data import load_catalogue
from archsearch.corpus import (
    CORPUS_VERSION,
    build_document,
    load_corpus,
    load_curated_corpus,
    load_pre_nps_corpus,
    source_excerpts,
)
from archsearch.coverage import CatalogueIndex
from archsearch.domain import Site
from archsearch.polar_data import load_polar
from archsearch.regional_data import load_regional
from archsearch.southamerica_data import load_southamerica
from archsearch.spatial_data import load_world_locations
from archsearch.supplement_data import base_contract, load_supplement


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture(scope="module")
def base1700() -> list[Site]:
    return load_southamerica(
        load_regional(load_supplement(load_polar(load_catalogue(load_curated_corpus())))),
    )


def make_record(source_id: int = 1) -> dict[str, Any]:
    source_uri = f"https://example.org/chp001/{source_id}"
    identifier = f"auth:unesco-chp:{source_id}"
    title = f"Archaeological site {source_id}"
    title_fr = f"Site archéologique {source_id}"
    source_ref = {
        "id": f"qualification:chp001:{source_id}", "title": title,
        "uri": source_uri, "publisher": "Fixture authority", "license": "CC BY-SA 4.0",
        "revision": cohort.SOURCE_MODIFIED, "accessed": "2026-11-04", "excerpt": title,
    }
    locations = [
        {"source_index": 0, "component_id": source_id, "name_en": "Archaeological site",
         "name_fr": "Site archéologique", "original_coordinate": "3,2",
         "coordinate": [2.0, 3.0], "map_eligible": True,
         "reason": "Public cultural site coordinate."},
        {"source_index": 1, "component_id": source_id + 1000, "name_en": "Storage building",
         "name_fr": "Entrepôt", "original_coordinate": "3.01,2.01",
         "coordinate": [2.01, 3.01], "map_eligible": False,
         "reason": "Storage is retained as source evidence, not plotted as an original site."},
        {"source_index": 2, "component_id": source_id + 2000, "name_en": "Second source label",
         "name_fr": "Deuxième étiquette", "original_coordinate": "3,2",
         "coordinate": [2.0, 3.0], "map_eligible": True,
         "reason": "A repeated source coordinate retains its independent record and order."},
    ]
    source_record = {
        "site_id": source_id, "uuid": str(UUID(int=source_id)), "title_en": title,
        "title_fr": title_fr, "iso2": "FR", "country_title_en": "France",
        "regional_group": "Europe and North America", "year_inscription": "2026",
        "protection_en": "Enhanced Protection List", "protection_fr": "Protection renforcée",
        "coordinates": {"lon": 2.0, "lat": 3.0}, "component_count": len(locations),
        "components": [{"component_id": item["component_id"], "name_en": item["name_en"],
                        "name_fr": item["name_fr"], "coordinates": item["original_coordinate"]}
                       for item in locations],
    }
    return {
        "source_id": source_id, "source_uuid": str(UUID(int=source_id)),
        "country_label": "France",
        "site": {
            "id": identifier, "title": title, "description": "", "description_zh": "",
            "details": "Source country association: France (FR).", "names": [title_fr],
            "types": ["historic-site"], "periods": [], "repr_point": [2.0, 3.0],
            "location_precision": None, "source_uri": source_uri,
            "contributors": ["Fixture authority"], "period_evidence": [],
            "source_kind": "supplement", "source_refs": [source_ref],
            "chronology": {"status": "not_reviewed", "method": "Identity review only.",
                           "reviewed_at": None, "note": "Protection year is not a site phase.",
                           "phases": [], "default_phase_id": None},
            "geography": {"authority_id": "supplement:" + identifier, "countries": ["FR"],
                          "regions": ["europe-north-america"], "source": source_ref,
                          "point_count": 1, "note": "Three source records, one storage excluded."},
        },
        "coordinate": {"method": "authority", "point": [2.0, 3.0], "source_uri": source_uri,
                       "statement_id": None, "globe": None, "precision": None, "rank": None,
                       "note": "Original source main point is longitude,latitude."},
        "independent_review": {"status": "approved", "reviewer": "independent-fixture-agent",
                               "method": "Source identity and location comparison, not chronology.",
                               "reviewed_at": "2026-11-04"},
        "locations": locations,
        "source_files": [
            {"filename": "records.json", "sha256": digest(b"fixture records"),
             "uri": "https://example.org/chp001/records"},
            {"filename": "metadata.json", "sha256": digest(b"fixture metadata"),
             "uri": "https://example.org/chp001/metadata"},
        ],
        "provenance": {"source_record": source_record,
                       "protection_year_is_not_historical_phase": True},
    }


@dataclass
class Bundle:
    directory: Path
    spec: dict[str, Any]
    monkeypatch: pytest.MonkeyPatch

    def pin_spec(self) -> None:
        payload = encoded(self.spec)
        (self.directory / cohort.SPEC_FILE).write_bytes(payload)
        self.monkeypatch.setattr(cohort, "SPEC_SHA256", digest(payload))

    def compile(self) -> dict[str, Any]:
        self.pin_spec()
        model = cohort.ProtectionSpec.model_validate(self.spec)
        rows = sorted(model.records, key=lambda row: (
            digest((cohort.COHORT_VERSION + ":" + row.site.id).encode()), row.site.id,
        ))
        sites = encoded([row.site.model_dump(mode="json") for row in rows])
        locations = encoded({
            "version": cohort.LOCATIONS_VERSION, "source_sha256": cohort.SOURCE_SHA256,
            "records": {row.site.id: [item.model_dump(mode="json") for item in row.locations]
                        for row in rows},
        })
        self.monkeypatch.setattr(cohort, "SITES_SHA256", digest(sites))
        self.monkeypatch.setattr(cohort, "LOCATIONS_SHA256", digest(locations))
        return cohort.rebuild_protection(self.directory)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base1700: list[Site]) -> Bundle:
    record = make_record()
    decisions = [
        {"source_id": source_id, "source_uuid": str(UUID(int=source_id)),
         "title": record["site"]["title"] if source_id == 1 else f"Source row {source_id}",
         "disposition": "include" if source_id == 1 else (
             "existing" if source_id == 2 else "component" if source_id == 3 else "hold"
         ),
         "target_id": record["site"]["id"] if source_id == 1 else (
             base1700[0].id if source_id in {2, 3} else None
         ),
         "reason": "Independent fixture decision with original source identity."}
        for source_id in range(1, 176)
    ]
    spec = {
        "schema_version": 1, "cohort_version": cohort.COHORT_VERSION,
        "corpus_version": cohort.CORPUS_VERSION, **base_contract(base1700),
        "source_sha256": cohort.SOURCE_SHA256, "metadata_sha256": cohort.METADATA_SHA256,
        "source_modified": cohort.SOURCE_MODIFIED,
        "review_reports": {"identity": "a" * 64, "scope": "b" * 64},
        "selection": "All 175 source rows reviewed; no source row implies a new site.",
        "decisions": decisions, "records": [record],
    }
    monkeypatch.setattr(cohort, "EXPECTED_REVIEW_REPORTS", dict(spec["review_reports"]))
    identities = sorted(
        (row["source_id"], row["source_uuid"], row["title"]) for row in decisions
    )
    monkeypatch.setattr(cohort, "SOURCE_IDENTITIES_SHA256", digest(encoded(identities)))
    result = Bundle(tmp_path, spec, monkeypatch)
    result.compile()
    return result


def test_source_component_lat_lon_is_converted_without_swapping_the_main_point() -> None:
    assert cohort.component_coordinate(" 34.61278806 , 36.24570489 ") == (
        36.24570489, 34.61278806,
    )
    assert cohort.component_coordinate("-0,+0") == (0.0, -0.0)
    assert cohort.component_coordinate("-90,180") == (180.0, -90.0)
    record = cohort.ProtectionRecord.model_validate(make_record())
    assert record.site.repr_point == (2.0, 3.0)
    assert record.locations[0].coordinate == record.site.repr_point


@pytest.mark.parametrize("text", [
    "", "1", "1,2,3", "null,1", "NaN,1", "1,Infinity", "1e999,2",
    "91,0", "0,181", "1_0,2", "0x10,2", "一,2", "1;2",
])
def test_invalid_component_literals_are_never_repaired_or_zero_filled(text: str) -> None:
    with pytest.raises(ValueError):
        cohort.component_coordinate(text)


@pytest.mark.parametrize("point", [
    [True, 0], [0, False], ["2", 3], [2], [2, 3, 4],
    [float("nan"), 3], [2, float("inf")], [181, 3], [2, 91],
])
def test_reviewed_coordinates_reject_coercion_nonfinite_and_invalid_bounds(point: Any) -> None:
    location = copy.deepcopy(make_record()["locations"][0])
    location.update(original_coordinate=None, coordinate=point)
    with pytest.raises(ValueError):
        cohort.LocationReview.model_validate(location)


def test_source_coordinate_and_reviewed_coordinate_must_agree_exactly() -> None:
    location = copy.deepcopy(make_record()["locations"][0])
    location["coordinate"] = [3.0, 2.0]
    with pytest.raises(ValueError):
        cohort.LocationReview.model_validate(location)
    location.update(original_coordinate=None, coordinate=None)
    with pytest.raises(ValueError):
        cohort.LocationReview.model_validate(location)


def test_storage_and_duplicate_positions_remain_in_audit_but_only_approved_sites_are_mapped(
    bundle: Bundle,
) -> None:
    locations = json.loads((bundle.directory / cohort.LOCATIONS_FILE).read_bytes())
    raw = locations["records"]["auth:unesco-chp:1"]
    assert [item["source_index"] for item in raw] == [0, 1, 2]
    assert raw[1]["name_en"] == "Storage building" and raw[1]["map_eligible"] is False
    actual = cohort.load_protection_locations(bundle.directory)
    assert actual.points["auth:unesco-chp:1"] == ((2.0, 3.0), (2.0, 3.0))
    records = actual.records["auth:unesco-chp:1"]
    assert [item.source_index for item in records] == [0, 1]
    assert "source_index:0" in records[0].ref and "source_index:2" in records[1].ref
    assert all("1001" not in item.ref for item in records)
    assert actual.source["dataset_id"] == "chp001"
    assert actual.source["license"] == "CC BY-SA 4.0"


def test_rebuild_is_deterministic_and_does_not_mutate_the_earlier_corpus(
    bundle: Bundle, base1700: list[Site],
) -> None:
    before = [site.model_dump(mode="json") for site in base1700]
    documents = [build_document(site) for site in base1700]
    published = {name: (bundle.directory / name).read_bytes() for name in (
        cohort.SITES_FILE, cohort.LOCATIONS_FILE, cohort.MANIFEST_FILE,
    )}
    first = cohort.rebuild_protection(bundle.directory)
    assert cohort.rebuild_protection(bundle.directory) == first
    assert published == {name: (bundle.directory / name).read_bytes() for name in published}
    loaded = cohort.load_protection(base1700, bundle.directory)
    assert len(loaded) == 1701 and len({site.id for site in loaded}) == 1701
    assert all(old is new for old, new in zip(base1700, loaded[:1700], strict=True))
    assert [site.model_dump(mode="json") for site in loaded[:1700]] == before
    assert [build_document(site) for site in loaded[:1700]] == documents
    assert loaded[-1].chronology.status == "not_reviewed"
    assert not loaded[-1].chronology.phases and loaded[-1].chronology.default_phase_id is None
    assert first["counts"]["source_rows"] == 175
    assert first["counts"]["dispositions"] == {
        "include": 1, "existing": 1, "component": 1, "hold": 172,
    }
    assert first["counts"]["locations"] == 3
    assert first["counts"]["map_eligible_locations"] == 2


@pytest.mark.parametrize("change", ["text", "point", "country", "order", "missing"])
def test_changed_earlier_1700_record_contract_is_rejected(
    bundle: Bundle, base1700: list[Site], change: str,
) -> None:
    changed = list(base1700)
    if change == "text":
        changed[0] = changed[0].model_copy(update={"description": "New unsupported summary."})
    elif change == "point":
        changed[0] = changed[0].model_copy(update={"repr_point": (0.0, 0.0)})
    elif change == "country":
        index = next(i for i, site in enumerate(changed) if site.geography is not None)
        geography = changed[index].geography
        assert geography is not None
        changed[index] = changed[index].model_copy(update={
            "geography": geography.model_copy(update={"countries": ["ZZ"]}),
        })
    elif change == "order":
        changed.reverse()
    else:
        changed.pop()
    with pytest.raises(cohort.ProtectionError):
        cohort.load_protection(changed, bundle.directory)


@pytest.mark.parametrize("target", ["spec", "sites", "manifest", "locations"])
def test_modified_files_cannot_self_sign_their_new_checksums_in_the_manifest(
    bundle: Bundle, base1700: list[Site], target: str,
) -> None:
    manifest_path = bundle.directory / cohort.MANIFEST_FILE
    manifest = json.loads(manifest_path.read_bytes())
    if target == "spec":
        bundle.spec["records"][0]["site"]["description"] = "An invented history."
        path = bundle.directory / cohort.SPEC_FILE
        path.write_bytes(encoded(bundle.spec))
        manifest["files"][cohort.SPEC_FILE] = digest(path.read_bytes())
    elif target == "sites":
        path = bundle.directory / cohort.SITES_FILE
        rows = json.loads(path.read_bytes())
        rows[0]["repr_point"] = [0, 0]
        path.write_bytes(encoded(rows))
        manifest["files"][cohort.SITES_FILE] = digest(path.read_bytes())
    elif target == "locations":
        path = bundle.directory / cohort.LOCATIONS_FILE
        payload = json.loads(path.read_bytes())
        payload["records"]["auth:unesco-chp:1"][1]["map_eligible"] = True
        path.write_bytes(encoded(payload))
        manifest["files"][cohort.LOCATIONS_FILE] = digest(path.read_bytes())
    else:
        manifest["counts"]["added"] = 2
    manifest_path.write_bytes(encoded(manifest))
    with pytest.raises(cohort.ProtectionError):
        cohort.load_protection(base1700, bundle.directory)


def test_missing_or_corrupt_map_sidecar_preserves_search_facts_but_rejects_locations(
    bundle: Bundle, base1700: list[Site],
) -> None:
    path = bundle.directory / cohort.LOCATIONS_FILE
    original = path.read_bytes()
    for payload in (None, b"{}\n"):
        if payload is None:
            path.unlink()
        else:
            path.write_bytes(payload)
        assert len(cohort.load_protection(base1700, bundle.directory)) == 1701
        with pytest.raises(cohort.ProtectionError):
            cohort.load_protection_locations(bundle.directory)
        cohort.rebuild_protection(bundle.directory)
        assert path.read_bytes() == original


@pytest.mark.parametrize("mutation", [
    "missing_decision", "duplicate_source_id", "duplicate_uuid", "unapproved_record",
    "missing_record", "wrong_target", "wrong_record_uuid", "missing_review",
])
def test_full_source_audit_and_admitted_identity_binding_are_not_optional(
    bundle: Bundle, mutation: str,
) -> None:
    if mutation == "missing_decision":
        bundle.spec["decisions"].pop()
    elif mutation == "duplicate_source_id":
        bundle.spec["decisions"][1]["source_id"] = 1
    elif mutation == "duplicate_uuid":
        bundle.spec["decisions"][1]["source_uuid"] = bundle.spec["decisions"][0]["source_uuid"]
    elif mutation == "unapproved_record":
        bundle.spec["decisions"][0].update(disposition="hold", target_id=None)
    elif mutation == "missing_record":
        bundle.spec["decisions"][3].update(disposition="include", target_id="auth:unesco-chp:4")
    elif mutation == "wrong_target":
        bundle.spec["decisions"][0]["target_id"] = "auth:unesco-chp:4"
    elif mutation == "wrong_record_uuid":
        bundle.spec["records"][0]["source_uuid"] = str(UUID(int=999))
    else:
        bundle.spec["review_reports"] = {}
    bundle.pin_spec()
    with pytest.raises((cohort.ProtectionError, ValueError)):
        cohort.rebuild_protection(bundle.directory)


@pytest.mark.parametrize("field,value", [
    ("source_id", 999999), ("source_uuid", str(UUID(int=999999))),
    ("title", "A substituted source row with the same audit count"),
])
def test_complete_audit_count_cannot_hide_a_substituted_source_identity(
    bundle: Bundle, field: str, value: Any,
) -> None:
    bundle.spec["decisions"][-1][field] = value
    assert len(bundle.spec["decisions"]) == 175
    bundle.pin_spec()
    with pytest.raises(cohort.ProtectionError):
        cohort.rebuild_protection(bundle.directory)


def test_admitted_record_title_must_match_its_source_audit_identity(bundle: Bundle) -> None:
    bundle.spec["decisions"][0]["title"] = "Another original name in a revised source fixture"
    identities = sorted((row["source_id"], row["source_uuid"], row["title"])
                        for row in bundle.spec["decisions"])
    bundle.monkeypatch.setattr(cohort, "SOURCE_IDENTITIES_SHA256", digest(encoded(identities)))
    bundle.pin_spec()
    with pytest.raises(cohort.ProtectionError):
        cohort.rebuild_protection(bundle.directory)


@pytest.mark.parametrize("kind", ["existing", "component"])
def test_existing_and_component_decisions_must_target_the_unchanged_base(
    bundle: Bundle, base1700: list[Site], kind: str,
) -> None:
    decision = next(row for row in bundle.spec["decisions"] if row["disposition"] == kind)
    decision["target_id"] = "auth:unesco-chp:999999"
    bundle.compile()
    with pytest.raises(cohort.ProtectionError):
        cohort.load_protection(base1700, bundle.directory)


@pytest.mark.parametrize("field", ["source_sha256", "metadata_sha256", "source_modified"])
def test_pinned_source_version_and_license_snapshot_cannot_be_replaced(
    bundle: Bundle, field: str,
) -> None:
    bundle.spec[field] = "0" * 64 if field.endswith("sha256") else "2020-01-01T00:00:00Z"
    bundle.pin_spec()
    with pytest.raises((cohort.ProtectionError, ValueError)):
        cohort.rebuild_protection(bundle.directory)


@pytest.mark.parametrize("mutation", [
    "wrong_namespace", "wrong_source_id", "precision", "rank", "source_point_count",
    "reordered_locations", "no_eligible", "invented_stage",
])
def test_reviewed_record_cannot_gain_unapproved_identity_precision_location_or_phase(
    mutation: str,
) -> None:
    row = make_record()
    if mutation == "wrong_namespace":
        row["site"]["id"] = "auth:other-authority:1"
        row["site"]["geography"]["authority_id"] = "supplement:auth:other-authority:1"
    elif mutation == "wrong_source_id":
        row["source_id"] = 2
    elif mutation in {"precision", "rank"}:
        row["coordinate"][mutation] = 0.001 if mutation == "precision" else "preferred"
    elif mutation == "source_point_count":
        row["site"]["geography"]["point_count"] = 3
    elif mutation == "reordered_locations":
        row["locations"].reverse()
    elif mutation == "no_eligible":
        for item in row["locations"]:
            item["map_eligible"] = False
    else:
        row["site"]["chronology"].update(status="reviewed", reviewed_at="2026-11-04")
    with pytest.raises(ValueError):
        cohort.ProtectionRecord.model_validate(row)


@pytest.mark.parametrize("mutation", [
    "missing_source_record", "title", "description", "description_zh", "alias", "point",
    "country", "main_point_order", "component_count", "component_label",
    "component_identity", "component_literal", "omit_excluded_storage",
])
def test_normalized_record_must_remain_traceable_to_the_original_source_fields(
    mutation: str,
) -> None:
    row = make_record()
    if mutation == "missing_source_record":
        row["provenance"].pop("source_record")
    elif mutation == "title":
        row["site"]["title"] = "Corrected-looking but unreviewed name"
    elif mutation in {"description", "description_zh"}:
        row["site"][mutation] = "Invented historical narrative absent from this source."
    elif mutation == "alias":
        row["site"]["names"].append("New inferred Chinese name")
    elif mutation == "point":
        row["site"]["repr_point"] = [4.0, 5.0]
        row["coordinate"]["point"] = [4.0, 5.0]
    elif mutation == "country":
        row["site"]["geography"]["countries"] = ["DE"]
    elif mutation == "main_point_order":
        row["provenance"]["source_record"]["coordinates"] = {"lon": 3.0, "lat": 2.0}
    elif mutation == "component_count":
        row["provenance"]["source_record"]["component_count"] = 4
    elif mutation == "component_label":
        row["locations"][0]["name_en"] = "New name copied from another property"
    elif mutation == "component_identity":
        row["locations"][0]["component_id"] = 99
    elif mutation == "component_literal":
        row["locations"][0].update(original_coordinate="3.1,2.1", coordinate=[2.1, 3.1])
    else:
        row["locations"].pop(1)
        row["locations"][1]["source_index"] = 1
    with pytest.raises(ValueError):
        cohort.ProtectionRecord.model_validate(row)


def test_a_componentless_property_uses_only_its_original_main_point() -> None:
    row = make_record()
    original = row["provenance"]["source_record"]
    original.update(components=[], component_count=0)
    row["locations"] = [{
        "source_index": 0, "component_id": None, "name_en": original["title_en"],
        "name_fr": original["title_fr"], "original_coordinate": None,
        "coordinate": [2.0, 3.0], "map_eligible": True,
        "reason": "Only the source main representative is provided; no component invented.",
    }]
    parsed = cohort.ProtectionRecord.model_validate(row)
    assert parsed.locations[0].coordinate == parsed.site.repr_point
    row["locations"][0]["coordinate"] = [2.1, 3.1]
    with pytest.raises(ValueError):
        cohort.ProtectionRecord.model_validate(row)


def test_arqa_storage_627_is_retained_but_cannot_be_approved_as_an_original_site() -> None:
    row = make_record(626)
    row["locations"][1]["component_id"] = 627
    row["provenance"]["source_record"]["components"][1]["component_id"] = 627
    assert cohort.ProtectionRecord.model_validate(row).locations[1].map_eligible is False
    row["locations"][1]["map_eligible"] = True
    with pytest.raises(ValueError):
        cohort.ProtectionRecord.model_validate(row)


def test_source_evidence_cache_verification_deduplicates_shared_files_and_never_executes(
    bundle: Bundle, tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "records.json").write_bytes(b"fixture records")
    (cache / "metadata.json").write_bytes(b"fixture metadata")
    assert cohort.verify_source_cache(cache, bundle.directory) == 2
    (cache / "records.json").write_bytes(b"modified source bytes")
    with pytest.raises(cohort.ProtectionError):
        cohort.verify_source_cache(cache, bundle.directory)


def test_archived_source_code_is_checked_as_bytes_without_execution(
    bundle: Bundle, tmp_path: Path,
) -> None:
    payload = b"raise RuntimeError('Source evidence must never execute')\n"
    bundle.spec["records"][0]["source_files"] = [{
        "filename": "evidence.py", "sha256": digest(payload),
        "uri": "https://example.org/authority-evidence",
    }]
    bundle.pin_spec()
    cache = tmp_path / "data-only-cache"
    cache.mkdir()
    (cache / "evidence.py").write_bytes(payload)
    assert cohort.verify_source_cache(cache, bundle.directory) == 1


@pytest.mark.parametrize("mutation", ["replace_scope", "add_role", "drop_identity"])
def test_repinning_the_spec_cannot_replace_external_independent_review_pins(
    bundle: Bundle, mutation: str,
) -> None:
    if mutation == "replace_scope":
        bundle.spec["review_reports"]["scope"] = "0" * 64
    elif mutation == "add_role":
        bundle.spec["review_reports"]["self_approved"] = "c" * 64
    else:
        bundle.spec["review_reports"].pop("identity")
    bundle.pin_spec()
    with pytest.raises(cohort.ProtectionError):
        cohort.rebuild_protection(bundle.directory)


@pytest.mark.parametrize("disposition,target", [
    ("include", None), ("existing", None), ("component", None), ("hold", "whc:1"),
])
def test_hold_is_explicitly_targetless_and_approved_relationships_are_not(
    disposition: str, target: str | None,
) -> None:
    with pytest.raises(ValueError):
        cohort.SourceDecision.model_validate({
            "source_id": 1, "source_uuid": str(UUID(int=1)), "title": "Site",
            "disposition": disposition, "target_id": target, "reason": "Reviewed scope.",
        })


@pytest.mark.parametrize("field,value", [
    ("source_index", True), ("source_index", "0"), ("source_index", 0.0),
    ("component_id", False), ("component_id", "1"), ("component_id", 1.0),
    ("map_eligible", "false"), ("map_eligible", 0), ("map_eligible", 1),
])
def test_location_identity_and_eligibility_do_not_coerce_json_types(field: str, value: Any) -> None:
    location = make_record()["locations"][0]
    location[field] = value
    with pytest.raises(ValueError):
        cohort.LocationReview.model_validate(location)


def test_missing_audit_point_remains_null_and_an_explicit_zero_point_is_legitimate() -> None:
    location = copy.deepcopy(make_record()["locations"][0])
    location.update(original_coordinate=None, coordinate=None, map_eligible=False)
    parsed = cohort.LocationReview.model_validate(location)
    assert parsed.coordinate is None and parsed.map_eligible is False
    location.update(original_coordinate="0,0", coordinate=[0.0, 0.0], map_eligible=True)
    assert cohort.LocationReview.model_validate(location).coordinate == (0.0, 0.0)
    record = make_record()
    record["site"]["repr_point"] = None
    record["site"]["geography"]["point_count"] = 0
    record["coordinate"]["point"] = None
    with pytest.raises(ValueError):
        cohort.ProtectionRecord.model_validate(record)


@pytest.mark.parametrize("value", ["", "not-a-uuid", "00000000000000000000000000000001"])
def test_source_uuid_requires_original_uuid_structure(value: str) -> None:
    record = make_record()
    record["source_uuid"] = value
    with pytest.raises(ValueError):
        cohort.ProtectionRecord.model_validate(record)


@pytest.mark.parametrize("target", ["property", "component"])
def test_original_source_identity_does_not_equate_boolean_and_integer_values(target: str) -> None:
    record = make_record()
    original = record["provenance"]["source_record"]
    if target == "property":
        original["site_id"] = True
    else:
        original["components"][0]["component_id"] = True
    with pytest.raises(ValueError):
        cohort.ProtectionRecord.model_validate(record)


@pytest.mark.parametrize("filename", ["../outside.json", "C:\\outside.json", "/tmp/outside.json"])
def test_invalid_cache_contract_is_reported_as_a_domain_error(
    bundle: Bundle, filename: str,
) -> None:
    bundle.spec["records"][0]["source_files"][0]["filename"] = filename
    bundle.pin_spec()
    with pytest.raises(cohort.ProtectionError):
        cohort.verify_source_cache(bundle.directory, bundle.directory)


def test_conflicting_source_filename_contracts_fail_before_publishing(bundle: Bundle) -> None:
    artifact = copy.deepcopy(bundle.spec["records"][0]["source_files"][0])
    artifact["sha256"] = "0" * 64
    bundle.spec["records"][0]["source_files"].append(artifact)
    bundle.pin_spec()
    with pytest.raises(cohort.ProtectionError):
        cohort.rebuild_protection(bundle.directory)


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_source_identifiers_are_not_coerced_from_other_json_types(value: Any) -> None:
    row = make_record()
    row["source_id"] = value
    with pytest.raises(ValueError):
        cohort.ProtectionRecord.model_validate(row)
    decision = {"source_id": value, "source_uuid": str(UUID(int=1)), "title": "Site",
                "disposition": "hold", "target_id": None, "reason": "Pending review."}
    with pytest.raises(ValueError):
        cohort.SourceDecision.model_validate(decision)


@pytest.fixture
def published_directory(tmp_path: Path) -> Path:
    for filename in (cohort.SPEC_FILE, cohort.SITES_FILE,
                     cohort.LOCATIONS_FILE, cohort.MANIFEST_FILE):
        (tmp_path / filename).write_bytes((cohort.DATA_DIR / filename).read_bytes())
    return tmp_path


def test_published_source_roster_and_admission_counts_bind_the_fixed_source(
    published_directory: Path,
) -> None:
    payload = (published_directory / cohort.SPEC_FILE).read_bytes()
    assert digest(payload) == "d758e31a6c6ccda66cdc9d7a5181835f5a2bb44ea403f0aeb5f573dfd162d511"
    spec = cohort.ProtectionSpec.model_validate_json(payload)
    assert len(spec.decisions) == len({row.source_id for row in spec.decisions}) == 175
    assert len({row.source_uuid for row in spec.decisions}) == 175
    assert Counter(row.disposition for row in spec.decisions) == {
        "include": 95, "existing": 35, "component": 25, "hold": 20,
    }
    assert spec.review_reports == {
        "identity": "5b6ecf576a67db544caae12e015987bdfb003cbb0180dd6ca20ea3679a9447be",
        "scope": "5bc41c05e6a81ea88b9a86c5a74d156b3e65e2a516dbf58af6024406900d8f18",
        "payload": "4c71a53b33b093f7031189b5fe7fb2e2972d37b8beb0b456a5e0626e6acdcc1d",
    }
    assert len(spec.records) == 95
    assert Counter(row.site.geography.countries[0] for row in spec.records
                   if row.site.geography is not None) == {
        "LB": 60, "UA": 22, "YE": 7, "BF": 3, "BR": 2, "MX": 1,
    }
    admitted = {row.site.id for row in spec.records}
    assert admitted == {row.target_id for row in spec.decisions if row.disposition == "include"}


def test_published_extension_preserves_old1700_fields_order_objects_and_shared_documents(
    published_directory: Path, base1700: list[Site],
) -> None:
    before = [site.model_dump(mode="json") for site in base1700]
    documents = [digest(build_document(site).encode()) for site in base1700]
    loaded = cohort.load_protection(base1700, published_directory)
    assert len(loaded) == len({site.id for site in loaded}) == 1795
    assert len(base1700) == 1700
    assert all(old is new for old, new in zip(base1700, loaded[:1700], strict=True))
    assert [site.model_dump(mode="json") for site in loaded[:1700]] == before
    assert [digest(build_document(site).encode()) for site in loaded[:1700]] == documents
    assert [site.model_dump(mode="json") for site in load_pre_nps_corpus()[:1795]] == [
        site.model_dump(mode="json") for site in loaded
    ]
    assert all(site.source_kind == "supplement" and site.types == ["historic-site"]
               and site.description == site.description_zh == ""
               and site.location_precision is None and site.repr_point is not None
               and site.geography is not None and site.geography.point_count == 1
               and site.geography.authority_id == "supplement:" + site.id
               and not site.periods and not site.period_evidence
               and site.chronology.status == "not_reviewed" and not site.chronology.phases
               and site.chronology.default_phase_id is None for site in loaded[1700:])


def test_published_derivatives_rebuild_without_raw_source_cache_byte_for_byte(
    tmp_path: Path,
) -> None:
    (tmp_path / cohort.SPEC_FILE).write_bytes((cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes())
    filenames = (cohort.SITES_FILE, cohort.LOCATIONS_FILE, cohort.MANIFEST_FILE)
    expected = {filename: (cohort.DATA_DIR / filename).read_bytes() for filename in filenames}
    first = cohort.rebuild_protection(tmp_path)
    assert expected == {filename: (tmp_path / filename).read_bytes() for filename in filenames}
    assert cohort.rebuild_protection(tmp_path) == first
    assert expected == {filename: (tmp_path / filename).read_bytes() for filename in filenames}
    assert digest(expected[cohort.SITES_FILE]) == (
        "b1e3e6e86189609f352c75ad3fd34d9084010411f8a83c78ddb504a9ead05e98"
    )
    assert digest(expected[cohort.LOCATIONS_FILE]) == (
        "68d63415fd12fe8b16af66aec683c18f5082af7483b384282594a02c0d1186fa"
    )
    assert first["counts"] == {
        "base": 1700, "added": 95, "total": 1795, "source_rows": 175,
        "dispositions": {"include": 95, "existing": 35, "component": 25, "hold": 20},
        "locations": 108, "map_eligible_locations": 107,
    }


def test_real_components_keep_original_order_and_excluded_warehouse_evidence(
    published_directory: Path,
) -> None:
    spec = cohort.ProtectionSpec.model_validate_json(
        (published_directory / cohort.SPEC_FILE).read_bytes(),
    )
    source = cohort.load_protection_locations(published_directory)
    raw = json.loads((published_directory / cohort.LOCATIONS_FILE).read_bytes())["records"]
    assert len(source.points) == len(raw) == 95
    assert sum(map(len, raw.values())) == 108
    assert sum(map(len, source.points.values())) == 107
    for record in spec.records:
        originals = record.provenance["source_record"]["components"]
        assert raw[record.site.id] == [item.model_dump(mode="json") for item in record.locations]
        if originals:
            assert [item.source_index for item in record.locations] == list(range(len(originals)))
            assert [item.original_coordinate for item in record.locations] == [
                item["coordinates"] for item in originals
            ]
            assert [item.component_id for item in record.locations] == [
                item["component_id"] for item in originals
            ]
        expected = tuple(item.coordinate for item in record.locations if item.map_eligible)
        assert source.points[record.site.id] == expected
        assert all(entry.coordinate == expected[index]
                   for index, entry in enumerate(source.records[record.site.id]))
    assert len(source.points["auth:unesco-chp:630"]) == 12
    assert len(source.points["auth:unesco-chp:658"]) == 2
    arqa = raw["auth:unesco-chp:626"]
    assert len(arqa) == 2 and arqa[1]["component_id"] == 627
    assert arqa[1]["map_eligible"] is False
    assert arqa[1]["coordinate"] == [36.0490818, 34.5326699]
    assert source.points["auth:unesco-chp:626"] == ((36.046708, 34.5303896),)


def test_real_combined_source_groups_preserve_world5632_sequence_and_individual_licenses() -> None:
    old_locations = load_world_locations()
    new_locations = cohort.load_protection_locations()
    index = CatalogueIndex(load_corpus(), CORPUS_VERSION)
    combined = index.spatial
    assert combined is not None
    assert combined.version == ("world-locations-v1+protection-locations-v1+"
                                "nps-pacific-locations-v1")
    assert len(old_locations.points) == 1033
    assert sum(map(len, old_locations.points.values())) == 5632
    assert all(combined.points[key] == value for key, value in old_locations.points.items())
    assert all(combined.records[key] == value for key, value in old_locations.records.items())
    assert all(combined.points[key] == value for key, value in new_locations.points.items())
    coverage = index.spatial_coverage()
    assert coverage is not None and coverage.ready
    assert (coverage.records, coverage.points, coverage.distinct_points,
            coverage.duplicate_points, coverage.display_points) == (1239, 5851, 5546, 305, 7907)
    groups = {group.version: group for group in coverage.source_groups}
    assert set(groups) == {"world-locations-v1", "protection-locations-v1",
                           "nps-pacific-locations-v1"}
    assert set(groups["world-locations-v1"].site_ids) == set(old_locations.points)
    assert set(groups["protection-locations-v1"].site_ids) == set(new_locations.points)
    assert groups["world-locations-v1"].source.uri.endswith("/whc001/")
    assert groups["protection-locations-v1"].source.uri.endswith("/chp001/")
    assert groups["world-locations-v1"].source.sha256 == old_locations.source["records_sha256"]
    assert groups["protection-locations-v1"].source.sha256 == cohort.SOURCE_SHA256
    assert all(groups[version].source.license == "CC BY-SA 4.0" for version in (
        "world-locations-v1", "protection-locations-v1",
    ))
    assert groups["nps-pacific-locations-v1"].source.license == (
        "NPS government structured metadata; other source rights retained"
    )
    arqa = next(site for site in index.sites if site.id == "auth:unesco-chp:626")
    detail = index.site_locations(arqa)
    assert detail.source == groups["protection-locations-v1"].source
    assert detail.representative_point == (36.046708, 34.5303896)


def test_actual_warehouse_point_does_not_match_arqa_as_an_original_cultural_site() -> None:
    index = CatalogueIndex(load_corpus(), CORPUS_VERSION)
    excluded = SpatialBounds.from_csv("36.04907,34.53266,36.04909,34.53268")
    included = SpatialBounds.from_csv("36.04669,34.53037,36.04673,34.53041")
    assert "auth:unesco-chp:626" not in {site.id for site in index.page(bbox=excluded).sites}
    assert "auth:unesco-chp:626" in {site.id for site in index.page(bbox=included).sites}
    assert index.page(bbox=SpatialBounds.from_csv("-180,-90,180,90")).total == 3507
    assert index.coverage().locations.model_dump() == {"mapped": 3504, "polar": 3, "unknown": 390}


def test_false_overlap_flag_and_component_rows_are_not_fabricated_as_new_sites() -> None:
    spec = cohort.ProtectionSpec.model_validate_json(
        (cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes(),
    )
    decisions = {decision.source_id: decision for decision in spec.decisions}
    assert decisions[459].target_id == "whc:1810"
    assert decisions[482].target_id == "678374"
    assert decisions[514].target_id == decisions[517].target_id == "whc:1602"
    assert decisions[660].disposition == "hold" and decisions[660].target_id is None
    admitted = {record.source_id for record in spec.records}
    assert not admitted.intersection({459, 482, 514, 517, 575, 576, 577, 578, 660})


def test_administrative_refs_are_visible_without_becoming_search_text_or_site_dates() -> None:
    spec = cohort.ProtectionSpec.model_validate_json(
        (cohort.DATA_DIR / cohort.SPEC_FILE).read_bytes(),
    )
    assert len(spec.records) == 95
    for record in spec.records:
        site = record.site
        original = record.provenance["source_record"]
        references = [source for source in site.source_refs
                      if source.id == f"administrative:unesco-chp:{record.source_id}"]
        assert len(references) == 1
        reference = references[0]
        assert original["protection_en"] in reference.title
        assert original["protection_fr"] in reference.title
        assert original["year_inscription"] in reference.title
        assert "不是建造年" in reference.title
        assert reference.uri == site.source_uri
        assert reference.publisher == "UNESCO" and reference.license == "CC BY-SA 4.0"
        assert reference.revision is not None
        assert cohort.SOURCE_MODIFIED in reference.revision
        assert cohort.SOURCE_SHA256 in reference.revision
        assert reference.excerpt == ""
        assert source_excerpts(site) == [site.title]
        assert reference.title not in build_document(site)
        assert "行政列入年" not in build_document(site)
        assert site.periods == site.period_evidence == []
        assert site.chronology.status == "not_reviewed"
        assert site.chronology.phases == [] and site.chronology.default_phase_id is None
