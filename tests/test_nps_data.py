"""Synthetic offline compiler contracts; no fixture claims actual cultural facts."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from archsearch import nps_data as cohort
from archsearch.corpus import build_document
from archsearch.coverage import CatalogueIndex, CoverageRegistry
from archsearch.domain import Site
from archsearch.supplement_data import base_contract


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source(identifier: str) -> dict[str, Any]:
    return {
        "id": "qualification:" + identifier, "title": "Synthetic cultural qualification",
        "uri": "https://example.org/fixture/" + identifier, "publisher": "Synthetic authority",
        "license": None, "excerpt": "Synthetic fixed cultural place only.",
    }


def synthetic_site(identifier: str, country: str, region: str, mapped: bool) -> dict[str, Any]:
    evidence = source(identifier)
    return {
        "id": identifier, "title": "Synthetic place " + identifier,
        "description": "Synthetic test fixture, not a real source assertion.", "names": [],
        "types": ["historic-site"], "periods": [], "period_evidence": [],
        "repr_point": [144.5, 13.4] if mapped else None, "location_precision": None,
        "source_kind": "supplement", "source_uri": evidence["uri"],
        "source_refs": [evidence], "contributors": ["Synthetic authority"],
        "chronology": {"status": "not_reviewed", "phases": [], "default_phase_id": None},
        "geography": {
            "authority_id": "supplement:" + identifier, "countries": [country],
            "regions": [region], "point_count": int(mapped), "source": evidence,
        },
    }


@pytest.fixture(scope="module")
def base1807() -> list[Site]:
    return [Site.model_validate(synthetic_site(
        f"auth:fixture:{index}", ["FM", "PW", "MH"][index % 3], "asia-pacific", True,
    )) for index in range(1807)]


@dataclass
class Bundle:
    directory: Path
    spec: dict[str, Any]
    monkeypatch: pytest.MonkeyPatch

    def pin_spec(self) -> None:
        payload = encoded(self.spec)
        (self.directory / cohort.SPEC_FILE).write_bytes(payload)
        self.monkeypatch.setattr(cohort, "SPEC_SHA256", digest(payload))

    def pin_roster(self) -> None:
        rows = [{key: sorted(row[key]) if isinstance(row[key], list) else row[key]
                 for key in ["refnum", "names", "states", "resource_types", "source_feature_ids"]}
                for row in sorted(self.spec["decisions"], key=lambda row: row["refnum"])]
        self.monkeypatch.setattr(cohort, "SOURCE_ROSTER_SHA256", digest(encoded(rows)))

    def compile(self) -> dict[str, Any]:
        self.pin_spec()
        rows = sorted(self.spec["records"], key=lambda row: (
            digest(("nps-pacific-v1:" + row["site"]["id"]).encode()), row["site"]["id"],
        ))
        normalized = [Site.model_validate(row["site"]).model_dump(mode="json") for row in rows]
        self.monkeypatch.setattr(cohort, "SITES_SHA256", digest(encoded(normalized)))
        return cohort.rebuild_nps(self.directory)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base1807: list[Site]) -> Bundle:
    records, decisions = [], []
    for index, (state, country) in enumerate([("GUAM", "GU"),
                                            ("FEDERATED STATES OF MICRONESIA", "FM"),
                                            ("PALAU", "PW")], 1):
        refnum = f"{index:08d}"
        identifier = "auth:nps-nris:" + refnum
        evidence = source(identifier)
        artifact = {"filename": f"fixture-{index}.txt",
                    "sha256": digest(f"evidence{index}".encode()), "uri": evidence["uri"]}
        decisions.append({
            "refnum": refnum, "names": ["Synthetic place " + str(index)], "states": [state],
            "resource_types": ["building"], "source_feature_ids": [f"0:{index}"],
            "disposition": "include" if index < 3 else "existing",
            "target_id": identifier if index < 3 else base1807[0].id,
            "reason": "Synthetic independent scope decision only.", "evidence": [evidence],
            "source_files": [artifact],
        })
        if index == 3:
            continue
        site = synthetic_site(identifier, country, "nps-pacific", index == 1)
        records.append({
            "site": site, "country_label": cohort.COUNTRY_LABELS[country],
            "location_disclosure": "public" if index == 1 else "unverified",
            "coordinate": {"method": "authority" if index == 1 else "unknown",
                           "point": site["repr_point"],
                           "source_uri": evidence["uri"] if index == 1 else None,
                           "note": "Synthetic provider point; not excavation accuracy."},
            "independent_review": {
                "status": "approved", "reviewer": "Synthetic independent reviewer",
                "method": "Synthetic fixture only; no actual archaeological approval.",
                "reviewed_at": "2026-11-04",
            },
            "source_files": [artifact],
            "provenance": {"synthetic_fixture": True, "MAP_METHOD": "Synthetic derived point",
                           "IS_EXTANT": "Unknown", "SRC_DATE": 12345},
        })
    decisions[0]["source_feature_ids"].append("1:101")
    monkeypatch.setattr(cohort, "CANDIDATES_SHA256", "1" * 64)
    monkeypatch.setattr(cohort, "INDEPENDENT_REVIEW_SHA256", "2" * 64)
    spec = {
        "schema_version": 1, "cohort_version": "nps-pacific-v1", "corpus_version": "global-v11",
        **base_contract(base1807), "candidates_sha256": "1" * 64,
        "source_contract_report_sha256": cohort.SOURCE_CONTRACT_SHA256,
        "independent_report_sha256": "2" * 64, "new_countries": {"GU": "Guam"},
        "selection": "Synthetic fixture cohort, no actual cultural assertions.",
        "decisions": decisions, "records": records,
    }
    result = Bundle(tmp_path, spec, monkeypatch)
    result.pin_roster()
    result.compile()
    return result


def test_append_preserves_original_objects_documents_and_offline_outputs(
    bundle: Bundle, base1807: list[Site],
) -> None:
    fields = [site.model_dump(mode="json") for site in base1807]
    documents = [build_document(site) for site in base1807]
    loaded = cohort.load_nps(base1807, bundle.directory)
    assert len(loaded) == len({site.id for site in loaded}) == 1809
    assert all(old is new for old, new in zip(base1807[1:], loaded[1:1807], strict=True))
    assert [site.model_dump(mode="json") for site in base1807] == fields
    assert [site.model_dump(mode="json") for site in loaded[1:1807]] == fields[1:]
    assert [build_document(site) for site in loaded[:1807]] == documents
    assert sum(site.repr_point is not None for site in loaded[1807:]) == 1
    before = {name: (bundle.directory / name).read_bytes()
              for name in [cohort.SITES_FILE, cohort.MANIFEST_FILE]}
    for _ in range(2):
        manifest = cohort.rebuild_nps(bundle.directory)
        assert before == {name: (bundle.directory / name).read_bytes() for name in before}
    assert manifest["counts"] == {
        "base": 1807, "added": 2, "total": 1809, "source_references": 3, "source_features": 4,
        "decisions": {"existing": 1, "include": 2},
        "known_locations": 1, "no_adopted_coordinate": 1,
    }
    assert manifest["records"][0]["provenance"]["IS_EXTANT"] == "Unknown"
    bundle.spec["records"].reverse()
    bundle.spec["decisions"].reverse()
    bundle.compile()
    assert (bundle.directory / cohort.SITES_FILE).read_bytes() == before[cohort.SITES_FILE]


@pytest.mark.parametrize("disposition", ["existing", "component"])
@pytest.mark.parametrize("mapped", [True, False])
def test_sourced_existing_directory_membership_preserves_all_other_facts_and_documents(
    bundle: Bundle, base1807: list[Site], disposition: str, mapped: bool,
) -> None:
    base = list(base1807)
    raw = synthetic_site("auth:fixture:0", "US", "asia-pacific", mapped)
    raw["geography"]["note"] = "Original source note, unchanged prefix."
    base[0] = Site.model_validate(raw)
    original = base[0]
    before = [site.model_dump(mode="json") for site in base]
    documents = [build_document(site) for site in base]
    decision = bundle.spec["decisions"][2]
    decision.update(disposition=disposition, states=["AMERICAN SAMOA"])
    decision["evidence"][0].update(
        uri=original.source_uri, excerpt="Synthetic association text must not enter search.",
        revision="frozen-synthetic-revision", accessed="2026-11-04",
    )
    bundle.spec.update(base_contract(base))
    bundle.spec["new_countries"]["AS"] = "American Samoa"
    bundle.pin_roster()
    manifest = bundle.compile()
    loaded = cohort.load_nps(base, bundle.directory)
    updated = loaded[0]
    assert updated.geography and original.geography
    assert updated.geography.countries == ["US", "AS"]
    assert updated.geography.regions == ["asia-pacific", "nps-pacific"]
    assert updated.geography.note.startswith(original.geography.note + "\n\n")
    assert "00000003" in updated.geography.note and "AMERICAN SAMOA" in updated.geography.note
    if disposition == "component":
        assert "组成部分" in updated.geography.note
    for field in original.model_dump():
        if field not in {"geography", "source_refs"}:
            assert getattr(updated, field) == getattr(original, field)
    for field in original.geography.model_dump():
        if field not in {"countries", "regions", "note"}:
            assert getattr(updated.geography, field) == getattr(original.geography, field)
    assert all(old is new for old, new in zip(base[1:], loaded[1:1807], strict=True))
    assert [site.model_dump(mode="json") for site in base] == before
    assert [build_document(site) for site in loaded[:1807]] == documents
    assert updated.source_refs[:len(original.source_refs)] == original.source_refs
    association = updated.source_refs[-1]
    assert association.id == "association:nps:00000003:0" and association.excerpt == ""
    assert "NPS登记关联" in association.title
    assert (association.uri, association.publisher, association.license,
            association.revision, association.accessed) == (
        decision["evidence"][0]["uri"], decision["evidence"][0]["publisher"],
        decision["evidence"][0]["license"], decision["evidence"][0]["revision"],
        decision["evidence"][0]["accessed"],
    )
    registry = CoverageRegistry(
        countries={**dict(cohort.COUNTRY_LABELS), "US": "United States"},
        regions={"asia-pacific": "Legacy region", "nps-pacific": "Project NPS grouping"},
    )
    index = CatalogueIndex(loaded, "global-v11", registry)
    assert any(site.id == original.id for site in index.page(
        country="AS", region="nps-pacific",
    ).sites)
    assert manifest["catalogue_associations"] == [{
        "site_id": original.id, "refnum": "00000003", "source_states": ["AMERICAN SAMOA"],
        "country_codes": ["AS"], "region": "nps-pacific", "disposition": disposition,
    }]
    assert len(loaded) == 1809 and manifest["counts"]["added"] == 2


def test_no_accepted_existing_target_keeps_every_base_object_exact(
    bundle: Bundle, base1807: list[Site],
) -> None:
    bundle.spec["decisions"][2].update(disposition="hold", target_id=None)
    manifest = bundle.compile()
    loaded = cohort.load_nps(base1807, bundle.directory)
    assert all(old is new for old, new in zip(base1807, loaded[:1807], strict=True))
    assert manifest["catalogue_associations"] == []


def test_missing_old_geography_gets_only_sourced_membership_not_a_new_location(
    bundle: Bundle, base1807: list[Site],
) -> None:
    base = list(base1807)
    raw = synthetic_site("wd:Q90000001", "US", "asia-pacific", True)
    raw.update(source_kind="global", geography=None)
    base[0] = Site.model_validate(raw)
    original = base[0]
    bundle.spec.update(base_contract(base))
    bundle.spec["decisions"][2]["target_id"] = original.id
    bundle.compile()
    updated = cohort.load_nps(base, bundle.directory)[0]
    assert original.geography is None and updated.geography
    assert updated.geography.countries == ["PW"]
    assert updated.geography.regions == ["nps-pacific"]
    assert updated.geography.point_count == 1
    assert updated.geography.source.id == "association:nps:00000003:0"
    assert updated.geography.source.excerpt == ""
    assert updated.repr_point == original.repr_point
    assert updated.chronology == original.chronology
    assert build_document(updated) == build_document(original)
    assert {key: value for key, value in updated.model_dump().items()
            if key not in {"geography", "source_refs"}} == {
        key: value for key, value in original.model_dump().items()
        if key not in {"geography", "source_refs"}
    }


def test_multiple_source_decisions_union_membership_without_extra_sites_or_duplicates(
    bundle: Bundle, base1807: list[Site],
) -> None:
    base = list(base1807)
    base[0] = Site.model_validate(synthetic_site("auth:fixture:0", "US", "asia-pacific", True))
    for decision in bundle.spec["decisions"]:
        decision.update(disposition="existing", target_id=base[0].id)
    bundle.spec["decisions"][1]["states"] = ["GUAM"]
    bundle.spec["decisions"][2]["disposition"] = "component"
    bundle.spec.update(base_contract(base), records=[])
    bundle.pin_roster()
    manifest = bundle.compile()
    loaded = cohort.load_nps(base, bundle.directory)
    updated = loaded[0]
    assert updated.geography
    assert updated.geography.countries == ["US", "GU", "PW"]
    assert updated.geography.regions == ["asia-pacific", "nps-pacific"]
    assert len(updated.source_refs) == len(base[0].source_refs) + 3
    assert len({ref.id for ref in updated.source_refs}) == len(updated.source_refs)
    assert all(ref.excerpt == "" for ref in updated.source_refs[len(base[0].source_refs):])
    assert len(loaded) == 1807 and manifest["counts"]["added"] == 0
    assert len(manifest["catalogue_associations"]) == 3
    assert cohort.new_country_labels(bundle.directory) == {"GU": "Guam"}
    assert cohort.project_region_labels(bundle.directory) == {"nps-pacific": "NPS太平洋资料分组"}
    assert all(old is new for old, new in zip(base[1:], loaded[1:], strict=True))
    assert [build_document(site) for site in loaded] == [build_document(site) for site in base]


def test_new_country_label_may_come_only_from_an_existing_context(
    bundle: Bundle, base1807: list[Site],
) -> None:
    for decision in bundle.spec["decisions"][:2]:
        decision.update(disposition="hold", target_id=None)
    bundle.spec["decisions"][2]["states"] = ["AMERICAN SAMOA"]
    bundle.spec.update(records=[], new_countries={"AS": "American Samoa"})
    bundle.pin_roster()
    bundle.compile()
    assert cohort.new_country_labels(bundle.directory) == {"AS": "American Samoa"}
    updated = cohort.load_nps(base1807, bundle.directory)
    assert updated[0].geography and updated[0].geography.countries == ["FM", "AS"]
    assert len(updated) == len(base1807)


@pytest.mark.parametrize("change", ["field", "order", "count"])
def test_changed_base_rejected(bundle: Bundle, base1807: list[Site], change: str) -> None:
    altered = list(base1807)
    if change == "field":
        altered[0] = altered[0].model_copy(update={"description": "Changed."})
    elif change == "order":
        altered.reverse()
    else:
        altered.pop()
    with pytest.raises(cohort.NpsError, match="unchanged1807"):
        cohort.load_nps(altered, bundle.directory)


@pytest.mark.parametrize("target", [cohort.SPEC_FILE, cohort.SITES_FILE, cohort.MANIFEST_FILE])
def test_missing_or_self_signed_files_never_load_partial_success(
    bundle: Bundle, base1807: list[Site], target: str,
) -> None:
    path = bundle.directory / target
    payload = path.read_bytes()
    path.unlink()
    with pytest.raises(cohort.NpsError):
        cohort.load_nps(base1807, bundle.directory)
    assert not path.exists()
    value = json.loads(payload)
    if target == cohort.SPEC_FILE:
        value["records"][0]["site"]["description"] = "Self-approved data."
    elif target == cohort.SITES_FILE:
        value[0]["description"] = "Self-approved data."
    else:
        value["counts"]["total"] = 99999
    path.write_bytes(encoded(value))
    if target != cohort.MANIFEST_FILE:
        manifest_path = bundle.directory / cohort.MANIFEST_FILE
        manifest = json.loads(manifest_path.read_bytes())
        manifest["files"][target]["sha256"] = digest(path.read_bytes())
        manifest_path.write_bytes(encoded(manifest))
    with pytest.raises(cohort.NpsError):
        cohort.load_nps(base1807, bundle.directory)


@pytest.mark.parametrize("field", [
    "candidates_sha256", "independent_report_sha256", "source_contract_report_sha256",
])
def test_spec_repin_cannot_replace_external_source_approval(bundle: Bundle, field: str) -> None:
    bundle.spec[field] = "3" * 64
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError, match="binding"):
        cohort.rebuild_nps(bundle.directory)


@pytest.mark.parametrize("change", ["name", "state", "type", "feature", "missing"])
def test_decision_roster_pin_cannot_be_replaced_by_spec_or_manifest(
    bundle: Bundle, change: str,
) -> None:
    row = bundle.spec["decisions"][0]
    if change == "missing":
        bundle.spec["decisions"].pop()
    else:
        field = {"name": "names", "state": "states", "type": "resource_types",
                 "feature": "source_feature_ids"}[change]
        row[field] = [{"name": "Other source name", "state": "PALAU", "type": "site",
                       "feature": "0:999"}[change]]
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError, match="roster"):
        cohort.rebuild_nps(bundle.directory)


@pytest.mark.parametrize("change", ["reference", "feature"])
def test_duplicate_source_ref_or_feature_rejected(bundle: Bundle, change: str) -> None:
    if change == "reference":
        bundle.spec["decisions"].append(copy.deepcopy(bundle.spec["decisions"][0]))
    else:
        bundle.spec["decisions"][1]["source_feature_ids"] = ["0:1"]
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError, match="duplicate"):
        cohort.rebuild_nps(bundle.directory)


@pytest.mark.parametrize("change", ["missing-record", "duplicate-record", "shared-target"])
def test_include_decisions_require_one_to_one_records(bundle: Bundle, change: str) -> None:
    if change == "missing-record":
        bundle.spec["records"].pop()
    elif change == "duplicate-record":
        bundle.spec["records"].append(copy.deepcopy(bundle.spec["records"][0]))
    else:
        bundle.spec["decisions"][1]["target_id"] = bundle.spec["decisions"][0]["target_id"]
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError, match="one-to-one"):
        cohort.rebuild_nps(bundle.directory)


def test_same_country_record_swap_cannot_reassign_register_identity(bundle: Bundle) -> None:
    second = bundle.spec["records"][1]
    second["site"]["geography"]["countries"] = ["GU"]
    second["country_label"] = "Guam"
    bundle.spec["decisions"][1]["states"] = ["GUAM"]
    bundle.pin_roster()
    bundle.compile()
    first_decision, second_decision = bundle.spec["decisions"][:2]
    first_decision["target_id"], second_decision["target_id"] = (
        second_decision["target_id"], first_decision["target_id"],
    )
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError, match="exact canonical register identity"):
        cohort.rebuild_nps(bundle.directory)


@pytest.mark.parametrize("disposition", ["existing", "component"])
def test_existing_component_target_must_belong_to_old_base(
    bundle: Bundle, base1807: list[Site], disposition: str,
) -> None:
    row = bundle.spec["decisions"][2]
    row.update(disposition=disposition, target_id="auth:fixture:absent")
    bundle.compile()
    with pytest.raises(cohort.NpsError, match="original base"):
        cohort.load_nps(base1807, bundle.directory)


@pytest.mark.parametrize("change", ["hold-with-target", "include-without-target", "blank-reason"])
def test_decision_roles_cannot_be_ambiguous(bundle: Bundle, change: str) -> None:
    row = bundle.spec["decisions"][0]
    if change == "hold-with-target":
        row["disposition"] = "hold"
    elif change == "include-without-target":
        row["target_id"] = None
    else:
        row["reason"] = " "
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError):
        cohort.rebuild_nps(bundle.directory)


@pytest.mark.parametrize("change", ["country", "label", "region", "precision", "phase"])
def test_unreviewed_source_geography_and_precision_not_invented(
    bundle: Bundle, change: str,
) -> None:
    row = bundle.spec["records"][0]
    if change == "country":
        row["site"]["geography"]["countries"] = ["PW"]
    elif change == "label":
        row["country_label"] = "United States"
    elif change == "region":
        row["site"]["geography"]["regions"] = ["asia-pacific"]
    elif change == "precision":
        row["site"]["location_precision"] = "precise"
    else:
        row["site"]["chronology"]["status"] = "insufficient"
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError):
        cohort.rebuild_nps(bundle.directory)


@pytest.mark.parametrize("field,value", [
    ("source_uri", "https://example.org/fixture/auth:nps-nris:00000002"),
    ("statement_id", "pretend-GUID"), ("globe", "http://www.wikidata.org/entity/Q2"),
    ("precision", 0.001), ("rank", "normal"),
])
def test_unknown_point_keeps_all_positional_metadata_null(
    bundle: Bundle, field: str, value: object,
) -> None:
    bundle.spec["records"][1]["coordinate"][field] = value
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError):
        cohort.rebuild_nps(bundle.directory)


def test_known_restricted_ref_cannot_gain_point_with_a_public_claim(bundle: Bundle) -> None:
    decision = bundle.spec["decisions"][0]
    record = bundle.spec["records"][0]
    identifier = "auth:nps-nris:87001980"
    decision.update(refnum="87001980", target_id=identifier)
    record["site"] = synthetic_site(identifier, "GU", "nps-pacific", True)
    record["coordinate"]["source_uri"] = record["site"]["source_uri"]
    bundle.pin_roster()
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError, match="restricted"):
        cohort.rebuild_nps(bundle.directory)


@pytest.mark.parametrize("disclosure", ["restricted", "unverified"])
def test_other_nonpublic_refs_cannot_gain_a_point(bundle: Bundle, disclosure: str) -> None:
    assert bundle.spec["decisions"][0]["refnum"] != "87001980"
    bundle.spec["records"][0]["location_disclosure"] = disclosure
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError, match="not verified public"):
        cohort.rebuild_nps(bundle.directory)


@pytest.mark.parametrize("change", ["missing", "unknown-value"])
def test_disclosure_has_no_implicit_public_default(bundle: Bundle, change: str) -> None:
    row = bundle.spec["records"][0]
    if change == "missing":
        del row["location_disclosure"]
    else:
        row["location_disclosure"] = "Unknown"
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError, match="location_disclosure"):
        cohort.rebuild_nps(bundle.directory)


@pytest.mark.parametrize("disclosure", ["public", "restricted", "unverified"])
def test_all_disclosure_values_allow_an_honest_null_point(
    bundle: Bundle, base1807: list[Site], disclosure: str,
) -> None:
    bundle.spec["records"][1]["location_disclosure"] = disclosure
    manifest = bundle.compile()
    identifier = bundle.spec["records"][1]["site"]["id"]
    row = next(row for row in manifest["records"] if row["id"] == identifier)
    assert row["location_disclosure"] == disclosure
    assert row["coordinate"]["point"] is None
    loaded = cohort.load_nps(base1807, bundle.directory)
    assert next(site for site in loaded if site.id == identifier).repr_point is None


@pytest.mark.parametrize("change", ["missing", "invented", "renamed", "old-label"])
def test_new_labels_exactly_match_used_source_codes(bundle: Bundle, change: str) -> None:
    if change == "missing":
        bundle.spec["new_countries"] = {}
    elif change == "invented":
        bundle.spec["new_countries"]["UM"] = cohort.COUNTRY_LABELS["UM"]
    elif change == "renamed":
        bundle.spec["new_countries"]["GU"] = "Other name"
    else:
        bundle.spec["new_countries"]["FM"] = cohort.COUNTRY_LABELS["FM"]
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError, match="labels"):
        cohort.rebuild_nps(bundle.directory)


def test_new_labels_cannot_overwrite_an_existing_base_code(
    bundle: Bundle, base1807: list[Site],
) -> None:
    altered = list(base1807)
    altered[0] = Site.model_validate(synthetic_site("auth:fixture:0", "GU", "asia-pacific", True))
    bundle.spec.update(base_contract(altered))
    bundle.compile()
    with pytest.raises(cohort.NpsError, match="overwrite"):
        cohort.load_nps(altered, bundle.directory)


def test_record_identity_cannot_reuse_base_identity(bundle: Bundle, base1807: list[Site]) -> None:
    altered = list(base1807)
    altered[0] = Site.model_validate(bundle.spec["records"][1]["site"])
    bundle.spec.update(base_contract(altered))
    bundle.spec["decisions"][2]["target_id"] = altered[0].id
    bundle.compile()
    with pytest.raises(cohort.NpsError, match="duplicates an existing identity"):
        cohort.load_nps(altered, bundle.directory)


@pytest.mark.parametrize("filename", ["../outside", "/absolute", r"C:\absolute",
                                      r"sub\..\..\outside"])
def test_cross_platform_source_paths_cannot_escape(bundle: Bundle, filename: str) -> None:
    bundle.spec["decisions"][0]["source_files"][0]["filename"] = filename
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError):
        cohort.rebuild_nps(bundle.directory)


@pytest.mark.parametrize("field", ["sha256", "uri"])
def test_decision_and_record_source_artifact_conflicts_rejected(bundle: Bundle, field: str) -> None:
    artifact = copy.deepcopy(bundle.spec["records"][0]["source_files"][0])
    artifact[field] = "4" * 64 if field == "sha256" else "https://example.org/other"
    bundle.spec["decisions"][2]["source_files"].append(artifact)
    bundle.pin_spec()
    with pytest.raises(cohort.NpsError, match="conflicting"):
        cohort.rebuild_nps(bundle.directory)


def test_cache_optional_but_verifies_decision_only_sources_and_tampering(bundle: Bundle) -> None:
    cohort.rebuild_nps(bundle.directory)
    cache = bundle.directory / "cache"
    with pytest.raises(cohort.NpsError):
        cohort.verify_source_cache(cache, bundle.directory)
    cache.mkdir()
    for index in range(1, 4):
        (cache / f"fixture-{index}.txt").write_bytes(f"evidence{index}".encode())
    assert cohort.verify_source_cache(cache, bundle.directory) == 3
    (cache / "fixture-3.txt").write_bytes(b"tampered decision-only source")
    with pytest.raises(cohort.NpsError, match="snapshot differs"):
        cohort.verify_source_cache(cache, bundle.directory)


def test_source_cache_symlink_cannot_escape_selected_root(bundle: Bundle) -> None:
    cache = bundle.directory / "cache"
    cache.mkdir()
    outside = bundle.directory / "outside"
    outside.write_bytes(b"evidence1")
    try:
        (cache / "fixture-1.txt").symlink_to(outside)
    except OSError:
        pytest.skip("platform does not permit unprivileged symlinks")
    with pytest.raises(cohort.NpsError, match="snapshot differs"):
        cohort.verify_source_cache(cache, bundle.directory)


def test_registry_views_are_immutable_and_empty_cohort_has_no_invented_increment(
    bundle: Bundle, base1807: list[Site],
) -> None:
    labels = cohort.new_country_labels(bundle.directory)
    assert labels == {"GU": "Guam"}
    with pytest.raises(TypeError):
        labels["GU"] = "Overwrite"  # type: ignore[index]
    assert cohort.project_region_labels(bundle.directory) == {"nps-pacific": "NPS太平洋资料分组"}
    for decision in bundle.spec["decisions"]:
        decision.update(disposition="hold", target_id=None)
    bundle.spec.update(records=[], new_countries={})
    manifest = bundle.compile()
    assert manifest["counts"]["added"] == 0 and manifest["counts"]["total"] == 1807
    assert cohort.new_country_labels(bundle.directory) == {}
    assert cohort.project_region_labels(bundle.directory) == {}
    loaded = cohort.load_nps(base1807, bundle.directory)
    assert all(old is new for old, new in zip(base1807, loaded, strict=True))
