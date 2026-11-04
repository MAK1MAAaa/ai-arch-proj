"""Offline source contracts for the South America cohort and unchanged earlier corpus."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from archsearch import southamerica_data as cohort
from archsearch.catalogue_data import load_catalogue
from archsearch.corpus import build_document, load_curated_corpus, load_pre_nps_corpus
from archsearch.domain import Site
from archsearch.polar_data import load_polar
from archsearch.regional_data import load_regional
from archsearch.supplement_data import SourceArtifact, load_supplement


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture(scope="module")
def base1689() -> list[Site]:
    return load_regional(load_supplement(load_polar(load_catalogue(load_curated_corpus()))))


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
            digest((cohort.COHORT_VERSION + ":" + row["site"]["id"]).encode()),
            row["site"]["id"],
        ))
        sites = [Site.model_validate(row["site"]).model_dump(mode="json") for row in records]
        self.monkeypatch.setattr(cohort, "SITES_SHA256", digest(encoded(sites)))
        return cohort.rebuild_southamerica(self.directory)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Bundle:
    for name in (cohort.SPEC_FILE, cohort.SITES_FILE, cohort.MANIFEST_FILE):
        (tmp_path / name).write_bytes((cohort.DATA_DIR / name).read_bytes())
    return Bundle(tmp_path, json.loads((tmp_path / cohort.SPEC_FILE).read_bytes()), monkeypatch)


def test_real_bundle_preserves_every_earlier_field_object_document_and_order(
    bundle: Bundle, base1689: list[Site],
) -> None:
    before = [site.model_dump(mode="json") for site in base1689]
    documents = [build_document(site) for site in base1689]
    loaded = cohort.load_southamerica(base1689, bundle.directory)
    assert len(base1689) == 1689
    assert len(loaded) == len({site.id for site in loaded}) == 1700
    assert all(old is new for old, new in zip(base1689, loaded[:1689], strict=True))
    assert [site.model_dump(mode="json") for site in loaded[:1689]] == before
    assert [build_document(site) for site in loaded[:1689]] == documents
    assert [site.model_dump(mode="json") for site in load_pre_nps_corpus()[:1700]] == [
        site.model_dump(mode="json") for site in loaded
    ]
    additions = loaded[1689:]
    assert Counter(site.geography.countries[0] for site in additions if site.geography) == {
        "BR": 2, "BO": 2, "UY": 1, "CO": 1, "CL": 3, "PE": 2,
    }
    assert all(site.source_kind == "supplement" and site.types == ["historic-site"]
               and site.location_precision is None and site.geography is not None
               and site.geography.authority_id == "supplement:" + site.id
               and site.geography.regions == ["latin-america-caribbean"]
               and site.geography.point_count == int(site.repr_point is not None)
               and not site.periods and not site.period_evidence
               and site.chronology.status == "not_reviewed" and not site.chronology.phases
               and site.chronology.default_phase_id is None for site in additions)


def test_null_and_authority_points_keep_their_independently_reviewed_meaning(
    bundle: Bundle, base1689: list[Site],
) -> None:
    additions = {site.id: site for site in cohort.load_southamerica(base1689, bundle.directory)
                 if site.id not in {old.id for old in base1689}}
    unknown = additions["wd:Q98115650"]
    assert unknown.repr_point is None and unknown.geography is not None
    assert unknown.geography.point_count == 0 and unknown.location_precision is None
    assert sum(site.repr_point is None for site in additions.values()) == 1
    assert additions["wd:Q56678621"].repr_point == pytest.approx(
        (-44.03805555555555, -19.477183333333333),
    )
    assert additions["wd:Q970713"].repr_point == pytest.approx(
        (-65.41573055555556, -17.612250000000003),
    )
    rows = {row["site"]["id"]: row for row in bundle.spec["records"]}
    assert rows[unknown.id]["coordinate"]["method"] == "unknown"
    assert rows[unknown.id]["coordinate"]["precision"] is None
    for identifier in ("wd:Q56678621", "wd:Q970713"):
        evidence = rows[identifier]["coordinate"]
        assert evidence["method"] == "authority"
        assert evidence["point"] == list(additions[identifier].repr_point or ())
        assert evidence["source_uri"] in {
            source.uri for source in additions[identifier].source_refs
        }
    for row in rows.values():
        coordinate = row["coordinate"]
        if coordinate["method"] == "wikidata":
            assert coordinate["statement_id"] and coordinate["rank"] in {"normal", "preferred"}
            assert coordinate["globe"] in {
                "http://www.wikidata.org/entity/Q2", "https://www.wikidata.org/entity/Q2",
            }
            assert coordinate["point"] == row["site"]["repr_point"]


def test_review_and_derived_files_rebuild_offline_byte_for_byte(bundle: Bundle) -> None:
    published = {name: (bundle.directory / name).read_bytes()
                 for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)}
    first = cohort.rebuild_southamerica(bundle.directory)
    assert cohort.rebuild_southamerica(bundle.directory) == first
    assert published == {name: (bundle.directory / name).read_bytes() for name in published}
    assert first["counts"]["base"] == 1689
    assert first["counts"]["added"] == 11 and first["counts"]["total"] == 1700
    assert first["counts"]["known_locations"] == 10
    assert bundle.spec["reviewed_candidates_sha256"] == cohort.CANDIDATES_SHA256
    assert bundle.spec["independent_report_sha256"] == cohort.INDEPENDENT_REVIEW_SHA256
    assert bundle.spec["delegated_report_sha256"] == cohort.DELEGATED_REVIEW_SHA256
    assert bundle.spec["translation_candidates_sha256"] == cohort.TRANSLATION_CANDIDATES_SHA256
    assert bundle.spec["translation_report_sha256"] == cohort.TRANSLATION_REVIEW_SHA256
    assert {row["independent_review"]["status"] for row in bundle.spec["records"]} == {
        "approved",
    }
    assert len({source["filename"] for row in bundle.spec["records"]
                for source in row["source_files"]}) == 38


@pytest.mark.parametrize("change", ["text", "point", "country", "order", "count"])
def test_changed_base_cannot_reuse_the_frozen_1689_contract(
    bundle: Bundle, base1689: list[Site], change: str,
) -> None:
    altered = list(base1689)
    if change == "text":
        altered[0] = altered[0].model_copy(update={"description": "Unapproved source edit."})
    elif change == "point":
        altered[0] = altered[0].model_copy(update={"repr_point": (0.0, 0.0)})
    elif change == "country":
        index = next(index for index, site in enumerate(altered) if site.geography is not None)
        geography = altered[index].geography
        assert geography is not None
        altered[index] = altered[index].model_copy(update={
            "geography": geography.model_copy(update={"countries": ["ZZ"]}),
        })
    elif change == "order":
        altered.reverse()
    else:
        altered.pop()
    with pytest.raises(cohort.SouthAmericaError):
        cohort.load_southamerica(altered, bundle.directory)


@pytest.mark.parametrize("target", ["spec", "sites", "manifest", "review-proof"])
def test_bundle_cannot_self_sign_modified_source_facts_in_its_manifest(
    bundle: Bundle, base1689: list[Site], target: str,
) -> None:
    path = bundle.directory / cohort.MANIFEST_FILE
    manifest = json.loads(path.read_bytes())
    if target == "spec":
        bundle.spec["records"][0]["site"]["description"] = "Self-approved historical summary."
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
        manifest["independent_report_sha256"] = "0" * 64
    else:
        manifest["counts"]["known_locations"] = 11
    path.write_bytes(encoded(manifest))
    with pytest.raises(cohort.SouthAmericaError):
        cohort.load_southamerica(base1689, bundle.directory)


@pytest.mark.parametrize("field", [
    "reviewed_candidates_sha256", "independent_report_sha256", "delegated_report_sha256",
    "translation_candidates_sha256", "translation_report_sha256",
])
def test_source_and_independent_review_pins_cannot_be_replaced_only_in_the_spec(
    bundle: Bundle, field: str,
) -> None:
    bundle.spec[field] = "0" * 64
    bundle.pin_spec()
    with pytest.raises(cohort.SouthAmericaError):
        cohort.rebuild_southamerica(bundle.directory)


def test_repinning_review_alone_does_not_authorize_new_derived_sites(bundle: Bundle) -> None:
    bundle.spec["records"][0]["site"]["description"] = "Edited reviewed fixture source."
    bundle.pin_spec()
    with pytest.raises(cohort.SouthAmericaError):
        cohort.rebuild_southamerica(bundle.directory)


@pytest.mark.parametrize("filename", [cohort.SPEC_FILE, cohort.SITES_FILE, cohort.MANIFEST_FILE])
def test_missing_bundle_artifact_is_not_silently_reconstructed_by_loading(
    bundle: Bundle, base1689: list[Site], filename: str,
) -> None:
    (bundle.directory / filename).unlink()
    with pytest.raises(cohort.SouthAmericaError):
        cohort.load_southamerica(base1689, bundle.directory)
    assert not (bundle.directory / filename).exists()


def test_duplicate_new_identity_is_rejected_before_compilation(bundle: Bundle) -> None:
    site = bundle.spec["records"][1]["site"]
    site["id"] = bundle.spec["records"][0]["site"]["id"]
    site["geography"]["authority_id"] = "supplement:" + site["id"]
    bundle.pin_spec()
    with pytest.raises(cohort.SouthAmericaError):
        cohort.rebuild_southamerica(bundle.directory)


def test_append_rejects_an_identity_already_present_in_its_unchanged_base(
    bundle: Bundle, base1689: list[Site],
) -> None:
    site = bundle.spec["records"][0]["site"]
    site["id"] = base1689[-1].id
    site["geography"]["authority_id"] = "supplement:" + site["id"]
    bundle.compile()
    with pytest.raises(cohort.SouthAmericaError):
        cohort.load_southamerica(base1689, bundle.directory)


@pytest.mark.parametrize("change", [
    "missing-review", "pending-review", "no-source", "unknown-coordinate", "point-mismatch",
    "unreferenced-coordinate", "deprecated-wikidata", "invented-phase", "no-culture",
    "invented-location-precision", "unknown-with-precision", "wrong-point-count",
])
def test_record_sources_location_and_chronology_constraints_survive_a_repin(
    bundle: Bundle, change: str,
) -> None:
    row = next(row for row in bundle.spec["records"] if row["coordinate"]["method"] == "wikidata")
    if change == "unknown-with-precision":
        row = next(row for row in bundle.spec["records"]
                   if row["coordinate"]["method"] == "unknown")
    if change == "missing-review":
        row.pop("independent_review")
    elif change == "pending-review":
        row["independent_review"]["status"] = "pending"
    elif change == "no-source":
        row["source_files"] = []
    elif change == "unknown-coordinate":
        row["coordinate"]["method"] = "unknown"
    elif change == "point-mismatch":
        row["coordinate"]["point"] = [0, 0]
    elif change == "unreferenced-coordinate":
        row["coordinate"]["source_uri"] = "https://example.org/unreferenced"
    elif change == "deprecated-wikidata":
        row["coordinate"]["rank"] = "deprecated"
    elif change == "invented-phase":
        row["site"]["chronology"]["status"] = "insufficient"
    elif change == "invented-location-precision":
        row["site"]["location_precision"] = "rough"
    elif change == "unknown-with-precision":
        row["coordinate"]["precision"] = 0.01
    elif change == "wrong-point-count":
        row["site"]["geography"]["point_count"] = 2
    else:
        for source in row["site"]["source_refs"]:
            source["license"] = "CC0-1.0"
    bundle.pin_spec()
    with pytest.raises(cohort.SouthAmericaError):
        cohort.rebuild_southamerica(bundle.directory)


@pytest.mark.parametrize("field", ["uri", "sha256"])
def test_shared_source_filename_cannot_hide_conflicting_contracts(
    bundle: Bundle, field: str,
) -> None:
    source = copy.deepcopy(bundle.spec["records"][0]["source_files"][0])
    source[field] = "https://example.org/other" if field == "uri" else "0" * 64
    bundle.spec["records"][1]["source_files"].append(source)
    bundle.pin_spec()
    with pytest.raises(cohort.SouthAmericaError):
        cohort.rebuild_southamerica(bundle.directory)


@pytest.mark.parametrize("filename", [
    "../outside.json", "sub/../../outside.json", "/absolute.json",
    r"sub\..\..\outside.json", r"C:\absolute.json", r"C:relative.json",
    r"\\server\share\outside.json",
])
def test_source_paths_cannot_escape_on_windows_or_linux(bundle: Bundle, filename: str) -> None:
    bundle.spec["records"][0]["source_files"][0]["filename"] = filename
    bundle.pin_spec()
    with pytest.raises(cohort.SouthAmericaError):
        cohort.rebuild_southamerica(bundle.directory)


def test_raw_evidence_cache_is_optional_for_rebuild_but_required_when_verified(
    tmp_path: Path, bundle: Bundle,
) -> None:
    cohort.rebuild_southamerica(bundle.directory)
    with pytest.raises(cohort.SouthAmericaError):
        cohort.verify_source_cache(tmp_path / "absent-source-cache", bundle.directory)


def test_source_cache_verifier_checks_bytes_and_deduplicates_shared_artifacts(
    tmp_path: Path, bundle: Bundle,
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    payload = b"fixed synthetic source evidence\n"
    (cache / "fixture.txt").write_bytes(payload)
    artifact = SourceArtifact(filename="fixture.txt", sha256=digest(payload),
                              uri="https://example.org/source")
    spec = cohort.SouthAmericaSpec.model_validate(bundle.spec)
    records = [record.model_copy(update={"source_files": [artifact]}) for record in spec.records]
    fixture = spec.model_copy(update={"records": records})
    bundle.monkeypatch.setattr(cohort, "_spec", lambda _directory: fixture)
    assert cohort.verify_source_cache(cache, bundle.directory) == 1
    (cache / "fixture.txt").write_text("changed bytes", encoding="utf-8")
    with pytest.raises(cohort.SouthAmericaError):
        cohort.verify_source_cache(cache, bundle.directory)
