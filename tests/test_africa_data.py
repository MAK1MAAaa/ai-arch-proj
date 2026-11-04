"""Synthetic offline failure contracts for the independently reviewed Africa compiler."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from archsearch import africa_data as cohort
from archsearch.corpus import build_document
from archsearch.domain import Site
from archsearch.supplement_data import base_contract


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fixture_site(identifier: str, country: str, mapped: bool) -> dict[str, Any]:
    source = {
        "id": "qualification:" + identifier,
        "title": "Synthetic authority evidence",
        "uri": "https://example.org/cultural-record/" + identifier,
        "publisher": "Synthetic authority",
        "license": None,
        "excerpt": "Synthetic cultural qualification only.",
    }
    return {
        "id": identifier, "title": "Synthetic cultural record " + identifier,
        "description": "Synthetic test data; not a real source assertion.",
        "names": [], "types": ["historic-site"], "periods": [],
        "repr_point": [10.0, 6.0] if mapped else None,
        "location_precision": None, "source_uri": source["uri"],
        "contributors": ["Synthetic authority"], "period_evidence": [],
        "source_kind": "supplement", "source_refs": [source],
        "chronology": {"status": "not_reviewed", "phases": [], "default_phase_id": None},
        "geography": {
            "authority_id": "supplement:" + identifier, "countries": [country],
            "regions": ["africa"], "source": source, "point_count": int(mapped),
        },
    }


@pytest.fixture(scope="module")
def base1795() -> list[Site]:
    countries = sorted(cohort.EXPECTED_COUNTRIES)
    return [Site.model_validate(fixture_site(
        f"auth:fixture:{index}", countries[index % len(countries)], True,
    )) for index in range(cohort.BASE_COUNT)]


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
        records = sorted(self.spec["records"], key=lambda row: (
            digest((cohort.COHORT_VERSION + ":" + row["site"]["id"]).encode()), row["site"]["id"],
        ))
        sites = [Site.model_validate(row["site"]).model_dump(mode="json") for row in records]
        self.monkeypatch.setattr(cohort, "SITES_SHA256", digest(encoded(sites)))
        return cohort.rebuild_africa(self.directory)


@pytest.fixture
def bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base1795: list[Site],
) -> Bundle:
    records = []
    for index, (identifier, country) in enumerate(zip(
        sorted(cohort.EXPECTED_IDS), ["NE", "NE", "AO", "CM", "CD"], strict=True,
    )):
        mapped = identifier.endswith((":6251", ":6320"))
        site = fixture_site(identifier, country, mapped)
        coordinate = {
            "method": "authority" if mapped else "unknown", "point": site["repr_point"],
            "source_uri": site["source_uri"] if mapped else None,
            "statement_id": None, "globe": None, "precision": None, "rank": None,
            "note": "Synthetic point evidence; null means no adopted coordinate.",
        }
        records.append({
            "site": site, "country_label": country, "coordinate": coordinate,
            "independent_review": {
                "status": "approved", "reviewer": "Synthetic independent reviewer",
                "method": "Synthetic source-contract fixture, not real archaeological approval.",
                "reviewed_at": "2026-11-04",
            },
            "source_files": [{
                "filename": f"fixture-{index}.txt", "sha256": digest(f"source{index}".encode()),
                "uri": site["source_uri"],
            }],
            "provenance": {"fixture": True},
        })
    report_pin = "1" * 64
    monkeypatch.setattr(cohort, "INDEPENDENT_REVIEW_SHA256", report_pin)
    spec = {
        "schema_version": 1, "cohort_version": cohort.COHORT_VERSION,
        "corpus_version": cohort.CORPUS_VERSION, **base_contract(base1795),
        "reviewed_candidates_sha256": cohort.CANDIDATES_SHA256,
        "independent_report_sha256": report_pin,
        "selection": "Synthetic offline contract fixtures, not published records.",
        "records": records,
    }
    result = Bundle(tmp_path, spec, monkeypatch)
    result.compile()
    return result


def test_append_preserves_all_base_fields_objects_documents_and_order(
    bundle: Bundle, base1795: list[Site],
) -> None:
    before = [site.model_dump(mode="json") for site in base1795]
    documents = [build_document(site) for site in base1795]
    loaded = cohort.load_africa(base1795, bundle.directory)
    assert len(loaded) == len({site.id for site in loaded}) == 1800
    assert all(old is new for old, new in zip(base1795, loaded[:1795], strict=True))
    assert [site.model_dump(mode="json") for site in loaded[:1795]] == before
    assert [build_document(site) for site in loaded[:1795]] == documents
    assert {site.id for site in loaded[1795:]} == cohort.EXPECTED_IDS
    assert sum(site.repr_point is not None for site in loaded[1795:]) == 2
    assert all(site.chronology.status == "not_reviewed" for site in loaded[1795:])


def test_rebuild_is_offline_and_byte_reproducible(bundle: Bundle) -> None:
    published = {name: (bundle.directory / name).read_bytes()
                 for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)}
    manifest = cohort.rebuild_africa(bundle.directory)
    assert cohort.rebuild_africa(bundle.directory) == manifest
    assert published == {name: (bundle.directory / name).read_bytes() for name in published}
    assert manifest["counts"] == {
        "base": 1795, "added": 5, "total": 1800, "countries": 4,
        "known_locations": 2, "no_adopted_coordinate": 3,
    }


@pytest.mark.parametrize("change", ["text", "point", "country", "order", "count"])
def test_changed_base_cannot_reuse_frozen_contract(
    bundle: Bundle, base1795: list[Site], change: str,
) -> None:
    altered = list(base1795)
    if change == "text":
        altered[0] = altered[0].model_copy(update={"description": "Unreviewed edit."})
    elif change == "point":
        altered[0] = altered[0].model_copy(update={"repr_point": (0.0, 0.0)})
    elif change == "country":
        geography = altered[0].geography
        assert geography is not None
        altered[0] = altered[0].model_copy(update={
            "geography": geography.model_copy(update={"countries": ["ZZ"]}),
        })
    elif change == "order":
        altered.reverse()
    else:
        altered.pop()
    with pytest.raises(cohort.AfricaError, match="unchanged1795"):
        cohort.load_africa(altered, bundle.directory)


@pytest.mark.parametrize("target", ["spec", "sites", "manifest", "review-proof"])
def test_manifest_cannot_self_sign_modified_source_facts(
    bundle: Bundle, base1795: list[Site], target: str,
) -> None:
    path = bundle.directory / cohort.MANIFEST_FILE
    manifest = json.loads(path.read_bytes())
    if target == "spec":
        bundle.spec["records"][0]["site"]["description"] = "Self-approved edit."
        changed = bundle.directory / cohort.SPEC_FILE
        changed.write_bytes(encoded(bundle.spec))
        manifest["files"][cohort.SPEC_FILE]["sha256"] = digest(changed.read_bytes())
    elif target == "sites":
        changed = bundle.directory / cohort.SITES_FILE
        values = json.loads(changed.read_bytes())
        values[0]["repr_point"] = [0, 0]
        changed.write_bytes(encoded(values))
        manifest["files"][cohort.SITES_FILE]["sha256"] = digest(changed.read_bytes())
    elif target == "review-proof":
        manifest["independent_source_review"]["report_sha256"] = "2" * 64
    else:
        manifest["counts"]["known_locations"] = 5
    path.write_bytes(encoded(manifest))
    with pytest.raises(cohort.AfricaError):
        cohort.load_africa(base1795, bundle.directory)


@pytest.mark.parametrize("field", ["reviewed_candidates_sha256", "independent_report_sha256"])
def test_repinning_spec_cannot_replace_source_or_independent_review(
    bundle: Bundle, field: str,
) -> None:
    bundle.spec[field] = "2" * 64
    bundle.pin_spec()
    with pytest.raises(cohort.AfricaError, match="binding"):
        cohort.rebuild_africa(bundle.directory)


def test_repinning_spec_alone_cannot_authorize_new_derived_sites(bundle: Bundle) -> None:
    bundle.spec["records"][0]["site"]["description"] = "Edited reviewed fixture source."
    bundle.pin_spec()
    with pytest.raises(cohort.AfricaError, match="independent pin"):
        cohort.rebuild_africa(bundle.directory)


@pytest.mark.parametrize("filename", [cohort.SPEC_FILE, cohort.SITES_FILE, cohort.MANIFEST_FILE])
def test_loading_does_not_silently_reconstruct_missing_files(
    bundle: Bundle, base1795: list[Site], filename: str,
) -> None:
    (bundle.directory / filename).unlink()
    with pytest.raises(cohort.AfricaError):
        cohort.load_africa(base1795, bundle.directory)
    assert not (bundle.directory / filename).exists()


@pytest.mark.parametrize("change", ["duplicate", "replacement", "country"])
def test_repinning_cannot_change_the_independently_reviewed_selection(
    bundle: Bundle, change: str,
) -> None:
    site = bundle.spec["records"][0]["site"]
    if change == "country":
        site["geography"]["countries"] = ["ZZ"]
    else:
        site["id"] = (bundle.spec["records"][1]["site"]["id"] if change == "duplicate"
                      else "auth:whc-tentative:999999")
        site["geography"]["authority_id"] = "supplement:" + site["id"]
    bundle.pin_spec()
    with pytest.raises(cohort.AfricaError):
        cohort.rebuild_africa(bundle.directory)


def test_repinning_base_proof_does_not_allow_an_already_present_identity(
    bundle: Bundle, base1795: list[Site],
) -> None:
    altered = list(base1795)
    altered[-1] = Site.model_validate(bundle.spec["records"][0]["site"])
    bundle.spec.update(base_contract(altered))
    bundle.compile()
    with pytest.raises(cohort.AfricaError, match="duplicates an existing identity"):
        cohort.load_africa(altered, bundle.directory)


def test_append_does_not_invent_country_labels_absent_from_base_registry(
    bundle: Bundle, base1795: list[Site],
) -> None:
    altered = []
    for site in base1795:
        geography = site.geography
        assert geography is not None
        altered.append(site.model_copy(update={
            "geography": geography.model_copy(update={"countries": ["CD"]}),
        }))
    bundle.spec.update(base_contract(altered))
    bundle.compile()
    with pytest.raises(cohort.AfricaError, match="existing label registry"):
        cohort.load_africa(altered, bundle.directory)


@pytest.mark.parametrize("change", [
    "pending-review", "no-source", "point-mismatch", "unreferenced-coordinate", "invented-phase",
    "no-culture", "invented-location-precision", "unknown-with-precision", "unknown-with-source",
    "wrong-point-count", "wrong-region",
])
def test_review_source_chronology_and_location_invariants_survive_repin(
    bundle: Bundle, change: str,
) -> None:
    row = next(row for row in bundle.spec["records"] if row["coordinate"]["method"] == (
        "unknown" if change.startswith("unknown-") else "authority"
    ))
    if change == "pending-review":
        row["independent_review"]["status"] = "pending"
    elif change == "no-source":
        row["source_files"] = []
    elif change == "point-mismatch":
        row["coordinate"]["point"] = [0, 0]
    elif change == "unreferenced-coordinate":
        row["coordinate"]["source_uri"] = "https://example.org/unreferenced"
    elif change == "invented-phase":
        row["site"]["chronology"]["status"] = "insufficient"
    elif change == "invented-location-precision":
        row["site"]["location_precision"] = "rough"
    elif change == "unknown-with-precision":
        row["coordinate"]["precision"] = 0.01
    elif change == "unknown-with-source":
        row["coordinate"]["source_uri"] = row["site"]["source_uri"]
    elif change == "wrong-point-count":
        row["site"]["geography"]["point_count"] = 2
    elif change == "wrong-region":
        row["site"]["geography"]["regions"] = ["arab-states"]
    else:
        for source in row["site"]["source_refs"]:
            source["license"] = "CC0-1.0"
    bundle.pin_spec()
    with pytest.raises(cohort.AfricaError):
        cohort.rebuild_africa(bundle.directory)


@pytest.mark.parametrize("field", ["uri", "sha256"])
def test_shared_source_filename_cannot_hide_conflicting_contracts(
    bundle: Bundle, field: str,
) -> None:
    source = copy.deepcopy(bundle.spec["records"][0]["source_files"][0])
    source[field] = "https://example.org/other" if field == "uri" else "3" * 64
    bundle.spec["records"][1]["source_files"].append(source)
    bundle.pin_spec()
    with pytest.raises(cohort.AfricaError, match="conflicting"):
        cohort.rebuild_africa(bundle.directory)


@pytest.mark.parametrize("filename", [
    "../outside.json", "sub/../../outside.json", "/absolute.json", r"sub\..\..\outside.json",
    r"C:\absolute.json", r"C:relative.json", r"\\server\share\outside.json",
])
def test_source_paths_cannot_escape_windows_or_linux(bundle: Bundle, filename: str) -> None:
    bundle.spec["records"][0]["source_files"][0]["filename"] = filename
    bundle.pin_spec()
    with pytest.raises(cohort.AfricaError):
        cohort.rebuild_africa(bundle.directory)


def test_cache_is_optional_for_rebuild_and_exact_when_explicitly_verified(bundle: Bundle) -> None:
    cohort.rebuild_africa(bundle.directory)
    cache = bundle.directory / "cache"
    with pytest.raises(cohort.AfricaError):
        cohort.verify_source_cache(cache, bundle.directory)
    cache.mkdir()
    for index in range(5):
        (cache / f"fixture-{index}.txt").write_bytes(f"source{index}".encode())
    assert cohort.verify_source_cache(cache, bundle.directory) == 5
    (cache / "fixture-0.txt").write_bytes(b"tampered")
    with pytest.raises(cohort.AfricaError, match="snapshot differs"):
        cohort.verify_source_cache(cache, bundle.directory)


def test_cache_symlink_cannot_escape_selected_root(bundle: Bundle) -> None:
    cache = bundle.directory / "cache"
    cache.mkdir()
    outside = bundle.directory / "outside.txt"
    outside.write_bytes(b"source0")
    try:
        (cache / "fixture-0.txt").symlink_to(outside)
    except OSError:
        pytest.skip("platform does not permit unprivileged symlinks")
    with pytest.raises(cohort.AfricaError, match="snapshot differs"):
        cohort.verify_source_cache(cache, bundle.directory)
