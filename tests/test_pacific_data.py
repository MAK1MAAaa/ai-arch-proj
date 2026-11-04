"""Synthetic, offline failure contracts; these fixtures assert no real cultural facts."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from archsearch import pacific_data as cohort
from archsearch.corpus import build_document
from archsearch.domain import Site
from archsearch.supplement_data import base_contract


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def synthetic_site(identifier: str, country: str, region: str, mapped: bool) -> dict[str, Any]:
    source = {
        "id": "qualification:" + identifier, "title": "Synthetic culture evidence",
        "uri": "https://example.org/fixture/" + identifier, "publisher": "Synthetic authority",
        "license": None, "excerpt": "Synthetic cultural qualification only.",
    }
    return {
        "id": identifier, "title": "Synthetic fixture " + identifier,
        "description": "Synthetic test fixture, not a real source assertion.", "names": [],
        "types": ["historic-site"], "periods": [], "period_evidence": [],
        "repr_point": [134.5, 7.3] if mapped else None, "location_precision": None,
        "source_kind": "supplement", "source_uri": source["uri"],
        "source_refs": [source], "contributors": ["Synthetic authority"],
        "chronology": {"status": "not_reviewed", "phases": [], "default_phase_id": None},
        "geography": {
            "authority_id": "supplement:" + identifier, "countries": [country],
            "regions": [region], "point_count": int(mapped), "source": source,
        },
    }


@pytest.fixture(scope="module")
def base1800() -> list[Site]:
    labels = list(cohort.EXPECTED_GEOGRAPHY.values())
    return [Site.model_validate(synthetic_site(
        f"auth:fixture:{index}", *labels[index % len(labels)], True,
    )) for index in range(1800)]


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
            digest(("pacific-interior-supplement-v1:" + row["site"]["id"]).encode()),
            row["site"]["id"],
        ))
        sites = [Site.model_validate(row["site"]).model_dump(mode="json") for row in records]
        self.monkeypatch.setattr(cohort, "SITES_SHA256", digest(encoded(sites)))
        return cohort.rebuild_pacific(self.directory)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base1800: list[Site]) -> Bundle:
    records = []
    for index, (identifier, (country, region)) in enumerate(cohort.EXPECTED_GEOGRAPHY.items()):
        mapped = identifier in cohort.EXPECTED_POINT_IDS
        site = synthetic_site(identifier, country, region, mapped)
        records.append({
            "site": site, "country_label": country,
            "coordinate": {
                "method": "authority" if mapped else "unknown", "point": site["repr_point"],
                "source_uri": site["source_uri"] if mapped else None,
                "note": "Synthetic evidence, no real location assertion.",
            },
            "independent_review": {
                "status": "approved", "reviewer": "Synthetic independent reviewer",
                "method": "Synthetic fixture approval, not actual archaeological approval.",
                "reviewed_at": "2026-11-04",
            },
            "source_files": [{
                "filename": f"fixture-{index}.txt", "sha256": digest(f"evidence{index}".encode()),
                "uri": site["source_uri"],
            }],
            "provenance": {"synthetic_fixture": True},
        })
    proof = "1" * 64
    monkeypatch.setattr(cohort, "INDEPENDENT_REVIEW_SHA256", proof)
    spec = {
        "schema_version": 1, "cohort_version": "pacific-interior-supplement-v1",
        "corpus_version": "global-v10", **base_contract(base1800),
        "reviewed_candidates_sha256": cohort.CANDIDATES_SHA256,
        "independent_report_sha256": proof,
        "selection": "Synthetic fixture selection, not published cultural records.",
        "records": records,
    }
    result = Bundle(tmp_path, spec, monkeypatch)
    result.compile()
    return result


def test_offline_append_keeps_base_objects_documents_and_reproducible_order(
    bundle: Bundle, base1800: list[Site],
) -> None:
    fields = [site.model_dump(mode="json") for site in base1800]
    documents = [digest(build_document(site).encode()) for site in base1800]
    loaded = cohort.load_pacific(base1800, bundle.directory)
    assert len(loaded) == len({site.id for site in loaded}) == 1807
    assert all(old is new for old, new in zip(base1800, loaded[:1800], strict=True))
    assert [site.model_dump(mode="json") for site in loaded[:1800]] == fields
    assert [digest(build_document(site).encode()) for site in loaded[:1800]] == documents
    assert {site.id for site in loaded[1800:]} == cohort.EXPECTED_IDS
    assert sum(site.repr_point is not None for site in loaded[1800:]) == 1
    expected = {name: (bundle.directory / name).read_bytes()
                for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)}
    manifest = cohort.rebuild_pacific(bundle.directory)
    assert expected == {name: (bundle.directory / name).read_bytes() for name in expected}
    assert manifest["counts"] == {
        "base": 1800, "added": 7, "total": 1807, "countries": 5,
        "known_locations": 1, "no_adopted_coordinate": 6,
    }
    bundle.spec["records"].reverse()
    bundle.compile()
    assert (bundle.directory / cohort.SITES_FILE).read_bytes() == expected[cohort.SITES_FILE]


@pytest.mark.parametrize("change", ["description", "order", "count"])
def test_changed_base_rejected(bundle: Bundle, base1800: list[Site], change: str) -> None:
    altered = list(base1800)
    if change == "description":
        altered[0] = altered[0].model_copy(update={"description": "Unreviewed edit."})
    elif change == "order":
        altered.reverse()
    else:
        altered.pop()
    with pytest.raises(cohort.PacificError, match="unchanged1800"):
        cohort.load_pacific(altered, bundle.directory)


@pytest.mark.parametrize("target", [cohort.SPEC_FILE, cohort.SITES_FILE, cohort.MANIFEST_FILE])
def test_missing_or_self_signed_artifact_never_silently_loads_partial_cohort(
    bundle: Bundle, base1800: list[Site], target: str,
) -> None:
    path = bundle.directory / target
    original = path.read_bytes()
    path.unlink()
    with pytest.raises(cohort.PacificError):
        cohort.load_pacific(base1800, bundle.directory)
    assert not path.exists()
    value = json.loads(original)
    if target == cohort.SPEC_FILE:
        value["records"][0]["site"]["description"] = "Self-approved fact."
    elif target == cohort.SITES_FILE:
        value[0]["description"] = "Self-approved fact."
    else:
        value["counts"]["known_locations"] = 7
    path.write_bytes(encoded(value))
    manifest_path = bundle.directory / cohort.MANIFEST_FILE
    if target != cohort.MANIFEST_FILE:
        manifest = json.loads(manifest_path.read_bytes())
        manifest["files"][target]["sha256"] = digest(path.read_bytes())
        manifest_path.write_bytes(encoded(manifest))
    with pytest.raises(cohort.PacificError):
        cohort.load_pacific(base1800, bundle.directory)


@pytest.mark.parametrize("field", ["reviewed_candidates_sha256", "independent_report_sha256"])
def test_spec_repin_does_not_replace_frozen_source_or_independent_proof(
    bundle: Bundle, field: str,
) -> None:
    bundle.spec[field] = "2" * 64
    bundle.pin_spec()
    with pytest.raises(cohort.PacificError, match="binding"):
        cohort.rebuild_pacific(bundle.directory)


@pytest.mark.parametrize("change", ["country", "region", "unknown-metadata", "new-point", "phase"])
def test_repin_cannot_reassign_identity_or_invent_point_or_chronology(
    bundle: Bundle, change: str,
) -> None:
    row = bundle.spec["records"][0]
    if change == "country":
        row["site"]["geography"]["countries"] = ["MH"]
    elif change == "region":
        row["site"]["geography"]["regions"] = ["africa"]
    elif change == "unknown-metadata":
        row["coordinate"]["precision"] = 0.01
    elif change == "new-point":
        row["site"]["repr_point"] = [1, 2]
        row["site"]["geography"]["point_count"] = 1
        row["coordinate"].update(
            method="authority", point=[1, 2], source_uri=row["site"]["source_uri"],
        )
    else:
        row["site"]["chronology"]["status"] = "insufficient"
    bundle.pin_spec()
    with pytest.raises(cohort.PacificError):
        cohort.rebuild_pacific(bundle.directory)


def test_duplicate_and_preexisting_identities_rejected(
    bundle: Bundle, base1800: list[Site],
) -> None:
    duplicate = copy.deepcopy(bundle.spec["records"][0])
    bundle.spec["records"].append(duplicate)
    bundle.pin_spec()
    with pytest.raises(cohort.PacificError, match="duplicates an identity"):
        cohort.rebuild_pacific(bundle.directory)
    bundle.spec["records"].pop()
    base = list(base1800)
    base[0] = Site.model_validate(duplicate["site"])
    bundle.spec.update(base_contract(base))
    bundle.compile()
    with pytest.raises(cohort.PacificError, match="duplicates an existing identity"):
        cohort.load_pacific(base, bundle.directory)


def test_base_cannot_silently_invent_missing_country_registry(
    bundle: Bundle, base1800: list[Site],
) -> None:
    altered = []
    for site in base1800:
        assert site.geography
        altered.append(site.model_copy(update={
            "geography": site.geography.model_copy(update={"countries": ["CD"]}),
        }))
    bundle.spec.update(base_contract(altered))
    bundle.compile()
    with pytest.raises(cohort.PacificError, match="existing label registry"):
        cohort.load_pacific(altered, bundle.directory)


@pytest.mark.parametrize("field", ["uri", "sha256"])
def test_source_filename_cannot_have_conflicting_contracts(bundle: Bundle, field: str) -> None:
    source = copy.deepcopy(bundle.spec["records"][0]["source_files"][0])
    source[field] = "https://example.org/other" if field == "uri" else "3" * 64
    bundle.spec["records"][1]["source_files"].append(source)
    bundle.pin_spec()
    with pytest.raises(cohort.PacificError, match="conflicting"):
        cohort.rebuild_pacific(bundle.directory)


@pytest.mark.parametrize("filename", [
    "../outside", "/absolute", r"C:\absolute", r"sub\..\..\outside",
])
def test_source_cache_paths_cannot_escape_windows_or_linux(bundle: Bundle, filename: str) -> None:
    bundle.spec["records"][0]["source_files"][0]["filename"] = filename
    bundle.pin_spec()
    with pytest.raises(cohort.PacificError):
        cohort.rebuild_pacific(bundle.directory)


def test_cache_optional_for_rebuild_but_exact_for_explicit_verification(bundle: Bundle) -> None:
    cohort.rebuild_pacific(bundle.directory)
    cache = bundle.directory / "cache"
    with pytest.raises(cohort.PacificError):
        cohort.verify_source_cache(cache, bundle.directory)
    cache.mkdir()
    for index in range(7):
        (cache / f"fixture-{index}.txt").write_bytes(f"evidence{index}".encode())
    assert cohort.verify_source_cache(cache, bundle.directory) == 7
    (cache / "fixture-0.txt").write_bytes(b"tampered")
    with pytest.raises(cohort.PacificError, match="snapshot differs"):
        cohort.verify_source_cache(cache, bundle.directory)


def test_cache_symlink_cannot_escape_selected_directory(bundle: Bundle) -> None:
    cache = bundle.directory / "cache"
    cache.mkdir()
    outside = bundle.directory / "outside"
    outside.write_bytes(b"evidence0")
    try:
        (cache / "fixture-0.txt").symlink_to(outside)
    except OSError:
        pytest.skip("platform does not permit unprivileged symlinks")
    with pytest.raises(cohort.PacificError, match="snapshot differs"):
        cohort.verify_source_cache(cache, bundle.directory)
