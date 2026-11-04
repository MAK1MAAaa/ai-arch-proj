"""Synthetic SG receipts test offline gates; they assert no real monument facts or approvals."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from archsearch import singapore_data as cohort
from archsearch.corpus import build_document
from archsearch.domain import Site
from archsearch.supplement_data import base_contract


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def base() -> list[Site]:
    source = {
        "id": "synthetic:base",
        "title": "Synthetic source",
        "uri": "https://example.org/base",
        "publisher": "Synthetic authority",
        "excerpt": "Synthetic cultural fixture.",
    }
    return [
        Site.model_validate(
            {
                "id": f"auth:fixture:{index}",
                "title": f"Original synthetic place {index}",
                "description": "Original description",
                "details": "Original details",
                "names": ["Original alias"],
                "types": ["historic-site"],
                "periods": [],
                "period_evidence": [],
                "repr_point": None,
                "source_kind": "supplement",
                "source_uri": source["uri"],
                "source_refs": [source],
                "contributors": [],
                "geography": {
                    "authority_id": f"supplement:auth:fixture:{index}",
                    "countries": ["SG"],
                    "regions": ["asia-pacific"],
                    "source": source,
                    "point_count": 0,
                },
            }
        )
        for index in range(cohort.BASE_COUNT)
    ]


@dataclass
class Bundle:
    directory: Path
    cache: Path
    roster: dict[str, Any]
    review: dict[str, Any]
    monkeypatch: pytest.MonkeyPatch

    def model(self) -> cohort.SingaporeSpec:
        return cohort.SingaporeSpec.model_validate({"roster": self.roster, "review": self.review})

    def pin_roster(self) -> None:
        raw = encoded(self.roster)
        (self.directory / cohort.ROSTER_FILE).write_bytes(raw)
        self.monkeypatch.setattr(cohort, "SOURCE_ROSTER_SHA256", digest(raw))

    def pin_review(self) -> None:
        raw = encoded(self.review)
        (self.directory / cohort.SPEC_FILE).write_bytes(raw)
        self.monkeypatch.setattr(cohort, "SPEC_SHA256", digest(raw))

    def pin_facts(self) -> None:
        self.monkeypatch.setattr(
            cohort, "SOURCE_FACTS_SHA256", digest(encoded(cohort._source_facts(self.model())))
        )

    def compile(self) -> dict[str, Any]:
        self.pin_roster()
        self.pin_review()
        sites = cohort.compile_singapore(self.model())
        self.monkeypatch.setattr(
            cohort,
            "SITES_SHA256",
            digest(encoded([site.model_dump(mode="json") for site in sites])),
        )
        return cohort.rebuild_singapore(self.directory)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base: list[Site]) -> Bundle:
    cache = tmp_path / "cache"
    cache.mkdir()

    def evidence(
        key: str, uri: str, excerpt: str = "Synthetic whole qualification."
    ) -> dict[str, Any]:
        raw = ("Synthetic source only: " + key).encode()
        (cache / f"{key}.txt").write_bytes(raw)
        return {
            "source": {
                "id": "fixture:" + key,
                "title": "Synthetic authority source",
                "uri": uri,
                "publisher": "Synthetic authority",
                "excerpt": excerpt,
            },
            "artifact": {"filename": f"{key}.txt", "sha256": digest(raw), "uri": uri},
        }

    metadata = evidence("metadata", cohort.DATASET_URI)
    licence = evidence("licence", cohort.LICENCE_URI)
    country = evidence("country", cohort.UN_M49_URI, "Singapore")
    coordinate = evidence(
        "rfc7946",
        "https://www.rfc-editor.org/rfc/rfc7946.html",
        "Geographic coordinates use WGS84.",
    )
    monkeypatch.setattr(cohort, "UN_M49_SHA256", country["artifact"]["sha256"])
    features = []
    for identifier in range(1, 6):
        slug = "Former-Synthetic-Place" if identifier == 1 else f"synthetic-monument-{identifier}"
        row = {
            "OBJECTID": identifier,
            "ADDRESSBLOCKHOUSENUMBER": "001",
            "ADDRESSBUILDINGNAME": None,
            "ADDRESSPOSTALCODE": "000123",
            "ADDRESSSTREETNAME": "Synthetic Street",
            "ADDRESSTYPE": None,
            "HYPERLINK": cohort.ROOTS_PREFIX + slug,
            "LANDXADDRESSPOINT": 29000,
            "LANDYADDRESSPOINT": 30000.25,
            "NAME": f"Synthetic whole {identifier}",
            "PHOTOURL": "https://example.org/not-downloaded.png",
            "ADDRESSFLOORNUMBER": None,
            "INC_CRC": "ABCDEF0123456789",
            "FMEL_UPD_D": "20260414163250",
            "ADDRESSUNITNUMBER": None,
            "DESCRIPTION": "Original licensed dataset description, not linked page prose.",
        }
        original = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [103.85, 1.29]},
            "properties": row,
        }
        features.append(
            {
                "source_index": identifier - 1,
                "source_row": row,
                "geometry": original["geometry"],
                "feature_sha256": cohort.feature_hash(original),
            }
        )
    raw_source = {
        "type": "FeatureCollection",
        "name": "MONUMENTS",
        "features": [
            {"type": "Feature", "geometry": row["geometry"], "properties": row["source_row"]}
            for row in features
        ],
    }
    raw = (json.dumps(raw_source, ensure_ascii=False, indent=2) + "\n").encode()
    (cache / "source.geojson").write_bytes(raw)
    artifact = {"filename": "source.geojson", "uri": cohort.GEOJSON_URI, "sha256": digest(raw)}
    roster = {
        "schema_version": 1,
        "dataset_id": cohort.DATASET_ID,
        "collection_name": "MONUMENTS",
        "source_artifact": artifact,
        "features": features,
    }
    decisions = []
    records = []
    for identifier, disposition in [
        (1, "include"),
        (2, "include"),
        (3, "existing"),
        (4, "component"),
        (5, "hold"),
    ]:
        row = features[identifier - 1]["source_row"]
        proof = evidence(f"whole-{identifier}", row["HYPERLINK"])
        whole = {
            "source_object_id": identifier,
            "title": row["NAME"],
            "business_uri": row["HYPERLINK"],
            "scope_kind": "composite_whole" if identifier == 2 else "whole_place",
            "supported_scope_literal": "Synthetic whole scope only.",
            "scope_evidence": [proof],
            "point": {
                "adoption": "provider_reference" if identifier == 1 else "not_adopted",
                "role": "provider_point_used_as_reference_no_centre_or_precision_claim",
                "reason": "Synthetic published reference role review.",
                "evidence": [coordinate],
            },
        }
        target = (
            cohort.project_id(row["HYPERLINK"])
            if disposition == "include"
            else None
            if disposition == "hold"
            else base[0 if disposition == "existing" else 1].id
        )
        decisions.append(
            {
                "whole": whole,
                "disposition": disposition,
                "target_id": target,
                "reason": "Independent synthetic decision, not an actual source approval.",
                "evidence": [proof],
            }
        )
        if disposition == "include":
            records.append(
                {
                    "source_object_id": identifier,
                    "evidence": [proof],
                    "independent_review": {
                        "status": "approved",
                        "reviewer": "Synthetic reviewer",
                        "method": "Fixture only; no human or expert confirmation.",
                        "reviewed_at": "2026-11-05",
                    },
                    "provenance": {"synthetic_fixture": True},
                }
            )
    review = {
        "schema_version": 1,
        "cohort_version": cohort.COHORT_VERSION,
        "corpus_version": cohort.CORPUS_VERSION,
        **base_contract(base),
        "candidates_sha256": "1" * 64,
        "handoff_sha256": "2" * 64,
        "independent_report_sha256": "3" * 64,
        "selection": cohort.SELECTION,
        "metadata": {
            "source_feature_count": 5,
            "published_coverage_literal": "Data from Mar 2021",
            "catalogue_last_updated_literal": "16 Apr 2026",
            "update_frequency_literal": "Updated annually",
            "evidence": metadata,
            "provider_declared_crs": None,
            "coordinate_interpretation": (
                "GeoJSON_default_WGS84_longitude_latitude_not_explicit_provider_precision"
            ),
            "coordinate_evidence": [coordinate],
        },
        "licence": {
            "name": cohort.LICENCE,
            "evidence": licence,
            "attribution": (
                f"Synthetic Monuments data, NHB, 2026-11-05, "
                f"{cohort.DATASET_URI}, {cohort.LICENCE_URI}"
            ),
            "accessed": "2026-11-05",
            "scope": "published_dataset_fields_and_reference_points_not_linked_pages_or_images",
        },
        "country": {
            "code": "SG",
            "region": "asia-pacific",
            "source_m49_cells": [
                "001",
                "World",
                "142",
                "Asia",
                "035",
                "South-eastern Asia",
                "",
                "",
                "Singapore",
                "702",
                "SG",
                "SGP",
                "",
                "",
                "x",
            ],
            "region_role": "project_catalogue_grouping_from_m49_asia_south_eastern_asia",
            "role": "modern_source_catalogue_association_not_point_inferred_sovereignty",
            "evidence": [country],
        },
        "decisions": decisions,
        "records": records,
    }
    for name, value in [
        ("RAW_SOURCE_SHA256", artifact["sha256"]),
        ("METADATA_SHA256", metadata["artifact"]["sha256"]),
        ("LICENCE_SHA256", licence["artifact"]["sha256"]),
        ("CANDIDATES_SHA256", "1" * 64),
        ("HANDOFF_SHA256", "2" * 64),
        ("INDEPENDENT_REVIEW_SHA256", "3" * 64),
        ("SITES_SHA256", "4" * 64),
    ]:
        monkeypatch.setattr(cohort, name, value)
    result = Bundle(tmp_path, cache, roster, review, monkeypatch)
    result.pin_roster()
    result.pin_review()
    result.pin_facts()
    return result


def test_compile_preserves_base_fields_order_documents_and_source_description(
    bundle: Bundle, base: list[Site]
) -> None:
    original = [site.model_dump(mode="json") for site in base]
    documents = [build_document(site) for site in base]
    manifest = bundle.compile()
    loaded = cohort.load_singapore(base, bundle.directory)
    assert [site.model_dump(mode="json") for site in loaded[: cohort.BASE_COUNT]] == original
    assert [build_document(site) for site in loaded[: cohort.BASE_COUNT]] == documents
    assert len(loaded) == cohort.BASE_COUNT + 2
    assert manifest["counts"]["adopted_reference_points"] == 1
    assert manifest["counts"]["new_historical_phases"] == 0
    assert manifest["metadata"]["published_coverage_literal"] == "Data from Mar 2021"
    assert manifest["metadata"]["catalogue_last_updated_literal"] == "16 Apr 2026"
    assert manifest["source_feature_clocks"][0]["FMEL_UPD_D"] == "20260414163250"
    assert cohort.verify_source_cache(bundle.cache, bundle.directory) == 10
    additions = {site.title: site for site in loaded[cohort.BASE_COUNT :]}
    point = additions["Synthetic whole 1"]
    assert point.repr_point == (103.85, 1.29) and point.location_precision is None
    assert point.description == bundle.roster["features"][0]["source_row"]["DESCRIPTION"]
    assert point.description_zh == "" and not point.periods and not point.chronology.phases
    assert (
        point.geography and point.geography.countries == ["SG"] and point.geography.point_count == 1
    )
    assert additions["Synthetic whole 2"].repr_point is None
    assert (
        additions["Synthetic whole 2"].geography
        and additions["Synthetic whole 2"].geography.point_count == 0
    )
    assert "not-downloaded.png" not in build_document(point)
    assert "000123" in build_document(point)
    assert cohort.rebuild_singapore(bundle.directory) == manifest


def test_runtime_needs_only_normalized_roster_review_sites_and_manifest(
    bundle: Bundle, base: list[Site]
) -> None:
    bundle.compile()
    for path in bundle.cache.iterdir():
        path.unlink()
    assert len(cohort.load_singapore(base, bundle.directory)) == cohort.BASE_COUNT + 2
    with pytest.raises(cohort.SingaporeError, match="source snapshots"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)


@pytest.mark.parametrize(
    "pin",
    [
        "RAW_SOURCE_SHA256",
        "METADATA_SHA256",
        "LICENCE_SHA256",
        "CANDIDATES_SHA256",
        "HANDOFF_SHA256",
        "INDEPENDENT_REVIEW_SHA256",
        "SOURCE_FACTS_SHA256",
        "SOURCE_ROSTER_SHA256",
        "SPEC_SHA256",
        "SITES_SHA256",
    ],
)
def test_all_source_and_compiled_pins_fail_closed(bundle: Bundle, pin: str) -> None:
    bundle.monkeypatch.setattr(cohort, pin, "")
    with pytest.raises(cohort.SingaporeError, match="not configured"):
        cohort._spec(bundle.directory)


@pytest.mark.parametrize("mutation", ["scope", "point", "target", "description"])
def test_resigning_derived_files_cannot_adopt_changed_source_facts(
    bundle: Bundle, mutation: str
) -> None:
    if mutation == "scope":
        bundle.review["decisions"][0]["whole"]["supported_scope_literal"] = "Unapproved whole scope"
    elif mutation == "point":
        bundle.review["decisions"][1]["whole"]["point"]["adoption"] = "provider_reference"
    elif mutation == "target":
        bundle.review["decisions"][2]["target_id"] = "auth:fixture:another"
    else:
        feature = bundle.roster["features"][0]
        feature["source_row"]["DESCRIPTION"] = "A replacement unapproved description"
        feature["feature_sha256"] = cohort.feature_hash(
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": feature["source_row"],
            }
        )
    with pytest.raises(cohort.SingaporeError, match="complete approved source facts"):
        bundle.compile()


def test_base_existing_target_and_sites_cannot_be_changed(bundle: Bundle, base: list[Site]) -> None:
    bundle.compile()
    changed = [base[0].model_copy(update={"details": "Changed"}), *base[1:]]
    with pytest.raises(cohort.SingaporeError, match="unchanged3116"):
        cohort.load_singapore(changed, bundle.directory)
    bundle.review["decisions"][2]["target_id"] = "auth:fixture:absent"
    bundle.pin_facts()
    bundle.compile()
    with pytest.raises(cohort.SingaporeError, match="target is absent"):
        cohort.load_singapore(base, bundle.directory)


@pytest.mark.parametrize(
    "name", [cohort.SITES_FILE, cohort.MANIFEST_FILE, cohort.ROSTER_FILE, cohort.SPEC_FILE]
)
def test_corrupt_or_oversized_local_files_are_rejected(
    bundle: Bundle, base: list[Site], name: str
) -> None:
    bundle.compile()
    path = bundle.directory / name
    path.write_bytes(b"damaged")
    with pytest.raises(cohort.SingaporeError):
        cohort.load_singapore(base, bundle.directory)


def test_bounded_source_and_data_paths_are_checked_before_reading(bundle: Bundle) -> None:
    bundle.monkeypatch.setattr(cohort, "MAX_ROSTER_BYTES", 4)
    with pytest.raises(cohort.SingaporeError, match="bounded contract"):
        cohort._spec(bundle.directory)
    with pytest.raises(cohort.SingaporeError, match="escapes"):
        cohort._read_bounded(bundle.directory, "../outside.json", 10)


def test_full_roster_decisions_and_feature_order_cannot_be_truncated(bundle: Bundle) -> None:
    bundle.review["decisions"].pop()
    bundle.pin_facts()
    bundle.pin_review()
    with pytest.raises(cohort.SingaporeError, match="every original source feature"):
        cohort._spec(bundle.directory)
    roster = copy.deepcopy(bundle.roster)
    roster["features"].reverse()
    with pytest.raises(ValidationError, match="ordered original"):
        cohort.SingaporeSourceRoster.model_validate(roster)


def test_source_point_is_exact_not_an_address_conversion_or_singapore_bbox(bundle: Bundle) -> None:
    feature = bundle.roster["features"][0]
    feature["geometry"]["coordinates"] = [-179.0, -35.0]
    feature["feature_sha256"] = cohort.feature_hash(
        {"type": "Feature", "geometry": feature["geometry"], "properties": feature["source_row"]}
    )
    bundle.pin_facts()
    bundle.compile()
    site = next(
        site
        for site in cohort.compile_singapore(bundle.model())
        if site.title == "Synthetic whole 1"
    )
    assert site.repr_point == (-179.0, -35.0) and site.location_precision is None
    assert site.repr_point != (
        feature["source_row"]["LANDXADDRESSPOINT"],
        feature["source_row"]["LANDYADDRESSPOINT"],
    )
    assert site.geography and site.geography.countries == ["SG"]


def test_original_uri_case_long_slug_and_field_types_are_preserved(bundle: Bundle) -> None:
    row = copy.deepcopy(bundle.roster["features"][0]["source_row"])
    assert cohort.SingaporeSourceRow.model_validate(row).hyperlink.endswith(
        "Former-Synthetic-Place"
    )
    uri = cohort.ROOTS_PREFIX + "X" * 84
    assert len(cohort.project_id(uri).rsplit(":", 1)[-1]) == 70
    assert cohort.project_id(uri) != cohort.project_id(uri.lower())
    row["OBJECTID"] = True
    with pytest.raises(ValidationError):
        cohort.SingaporeSourceRow.model_validate(row)
    row["OBJECTID"] = 1
    row["district"] = "Invented district"
    with pytest.raises(ValidationError):
        cohort.SingaporeSourceRow.model_validate(row)
    with pytest.raises(ValidationError):
        cohort.ProviderPoint.model_validate({"type": "Point", "coordinates": [True, 1.3]})


def test_cache_byte_tampering_and_coordinate_precision_invention_are_rejected(
    bundle: Bundle,
) -> None:
    bundle.compile()
    path = bundle.cache / "source.geojson"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(cohort.SingaporeError, match="snapshot differs"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)
    point = copy.deepcopy(bundle.review["decisions"][0]["whole"]["point"])
    point["location_precision"] = "rough"
    with pytest.raises(ValidationError):
        cohort.PointDecision.model_validate(point)


def test_current_official_entry_is_separate_from_original_uri_identity(bundle: Bundle) -> None:
    decision = bundle.review["decisions"][0]
    original = copy.deepcopy(bundle.roster["features"][0]["source_row"])
    current_uri = cohort.ROOTS_PREFIX + "current-correct-prison-entry"
    decision["whole"]["primary_source_uri"] = current_uri
    with pytest.raises(ValidationError, match="own retained whole-object evidence"):
        cohort.SingaporeDecision.model_validate(decision)
    proof = copy.deepcopy(decision["evidence"][0])
    proof["source"].update(
        uri=current_uri, id="qualification:current-uri", excerpt="AuditOnlyExcludedName"
    )
    payload = b"Synthetic current whole-object primary proof"
    (bundle.cache / "current-primary.txt").write_bytes(payload)
    proof["artifact"].update(
        uri=current_uri, filename="current-primary.txt", sha256=digest(payload)
    )
    decision["evidence"] = [proof]
    bundle.pin_facts()
    bundle.compile()
    site = next(
        site for site in cohort.compile_singapore(bundle.model()) if site.title == original["NAME"]
    )
    assert site.source_uri == current_uri
    assert site.id == cohort.project_id(original["HYPERLINK"])
    assert site.id != cohort.project_id(current_uri)
    assert bundle.roster["features"][0]["source_row"] == original
    assert original["HYPERLINK"] in site.details and current_uri in site.details
    assert any(source.uri == cohort.DATASET_URI for source in site.source_refs)
    assert "AuditOnlyExcludedName" not in build_document(site)
    for invalid in [
        "https://example.org/monument",
        "https://user@www.roots.gov.sg/monument",
        current_uri + "?signature=temporary",
        current_uri + "#fragment",
    ]:
        changed = copy.deepcopy(decision["whole"])
        changed["primary_source_uri"] = invalid
        with pytest.raises(ValidationError, match="safe stable official"):
            cohort.SingaporeWhole.model_validate(changed)


def test_positive_scope_is_searchable_but_audit_and_held_names_are_not(bundle: Bundle) -> None:
    whole = bundle.review["decisions"][0]["whole"]
    whole["supported_scope_literal"] = "Blocks 1, 2 and 3, two courtyards."
    bundle.review["decisions"][0]["reason"] = "ExcludedCandidateAuditName"
    audit = copy.deepcopy(bundle.review["decisions"][0]["evidence"][0])
    audit["source"].update(id="qualification:audit-only", excerpt="ExcludedCandidateAuditName")
    bundle.review["decisions"][0]["evidence"] = [audit]
    bundle.review["records"][0]["evidence"] = [audit]
    bundle.review["records"][0]["provenance"]["excluded_candidate"] = "AnotherExcludedName"
    bundle.review["decisions"][1]["whole"]["point"]["reason"] = "UnadoptedPointAuditName"
    bundle.pin_facts()
    sites = cohort.compile_singapore(bundle.model())
    first = next(site for site in sites if site.title == "Synthetic whole 1")
    assert whole["supported_scope_literal"] in first.details
    assert whole["supported_scope_literal"] in build_document(first)
    document = "\n".join(build_document(site) for site in sites)
    for excluded in [
        "ExcludedCandidateAuditName",
        "AnotherExcludedName",
        "UnadoptedPointAuditName",
        "Synthetic whole 5",
    ]:
        assert excluded not in document
    unknown = next(site for site in sites if site.title == "Synthetic whole 2")
    assert unknown.geography and "未采用来源Point" in unknown.geography.note
    assert "UnadoptedPointAuditName" in unknown.geography.note
    assert first.geography and "提供者未给计算方法或精度" in first.geography.note


def test_cli_rebuild_checks_the_safe_pre_singapore_base(
    bundle: Bundle,
    base: list[Site],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from archsearch import corpus

    bundle.compile()
    monkeypatch.setattr(corpus, "load_pre_singapore_corpus", lambda _: base)
    monkeypatch.setattr(
        "sys.argv", ["singapore_data", "--data-dir", str(bundle.directory), "--rebuild"]
    )
    cohort.main()
    assert json.loads(capsys.readouterr().out)["added"] == 2
    changed = [base[0].model_copy(update={"details": "Changed"}), *base[1:]]
    monkeypatch.setattr(corpus, "load_pre_singapore_corpus", lambda _: changed)
    with pytest.raises(SystemExit) as stopped:
        cohort.main()
    assert stopped.value.code == 1
    assert "unchanged3116" in capsys.readouterr().err
