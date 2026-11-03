"""Licensed full-world catalogue normalization, identity partitions and source uncertainty."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from archsearch import catalogue_data as catalogue
from archsearch.corpus import load_curated_corpus


def record(identifier: str = "123") -> dict[str, Any]:
    return {
        "id_no": identifier,
        "category": "Cultural",
        "region": "Asia and the Pacific",
        "name_en": "<i>Historic Harbor</i>",
        "name_zh": "历史港口",
        "name_fr": "Port historique",
        "name_es": None,
        "name_ar": None,
        "name_ru": None,
        "short_description_en": "<p>A harbor.</p><script>untrusted()</script><p>Built in 1200.</p>",
        "short_description_zh": "<p>一处港口。</p>",
        "date_inscribed": "1999",
        "iso_codes": ["CN"],
        "states_names": ["China"],
        "coordinates": {
            "type": "Feature",
            "geometry": {
                "type": "MultiPoint",
                "coordinates": [[179.0, 10.0], [-179.0, 10.0]],
            },
        },
        "geo_point_2d": {"lon": 0, "lat": 10},
        "components_count": 300,
    }


def test_normalization_preserves_official_bilingual_text_without_deriving_phase_dates() -> None:
    site = catalogue.normalize_record(record())
    assert site.id == "whc:123" and site.source_kind == "unesco"
    assert site.description == "A harbor. Built in 1200."
    assert site.description_zh == "一处港口。"
    assert site.names == ["Historic Harbor", "历史港口", "Port historique"]
    assert site.chronology.status == "not_reviewed" and not site.chronology.phases
    assert site.chronology.default_phase_id is None
    assert site.periods == [] and site.period_evidence == []
    assert site.source_refs[0].license == "CC BY-SA 4.0"
    assert catalogue.RECORDS_SHA256 in (site.source_refs[0].revision or "")


def test_source_position_order_survives_dateline_without_inventing_a_mean_or_component_count() -> (
    None
):
    site = catalogue.normalize_record(record())
    assert site.repr_point == (179, 10)
    assert site.geography is not None and site.geography.point_count == 2
    assert site.geography.point_count != record()["components_count"]
    assert "不取均值" in site.geography.note and "不是整体中心" in site.geography.note


def test_missing_description_is_preserved_without_fabricated_translation() -> None:
    row = record("1809")
    row.update(short_description_en=None, short_description_zh=None, name_zh=None)
    site = catalogue.normalize_record(row)
    assert site.description == site.description_zh == ""
    assert "历史港口" not in site.names


def test_special_jerusalem_designation_stays_unassigned_instead_of_guessing_jordan() -> None:
    row = record("148")
    row.update(iso_codes=None, states_names=["Jerusalem (Site proposed by Jordan)"])
    site = catalogue.normalize_record(row)
    assert site.geography is not None and site.geography.countries == []
    assert "Jerusalem (Site proposed by Jordan)" in site.geography.note
    assert "不补推主权归属" in site.geography.note


def test_missing_coordinates_require_an_independently_verified_fallback_not_zero() -> None:
    row = record()
    row["coordinates"] = None
    with pytest.raises(catalogue.CatalogueError, match="no verified representative"):
        catalogue.normalize_record(row)
    row = record("868")
    row["coordinates"] = None
    site = catalogue.normalize_record(row)
    assert site.repr_point == (-0.7229444444444445, 45.18405555555555)
    assert site.source_refs[1].id == "wikidata:Q2962473"
    assert site.source_refs[1].license == "CC0-1.0"
    assert "P757=868" in site.source_refs[1].excerpt
    assert site.geography is not None and site.geography.point_count == 1


def test_serial_property_fallback_records_both_relationship_directions_and_component_point() -> (
    None
):
    row = record("1567")
    row["coordinates"] = None
    site = catalogue.normalize_record(row)
    assert site.repr_point == (2.75563, 51.13696)
    assert site.geography is not None and site.geography.point_count == 1
    assert "组成部分" in site.geography.note and "不是整体中心" in site.geography.note
    assert len(site.source_refs) == 3
    assert "P757" in site.source_refs[1].excerpt and "P527" in site.source_refs[1].excerpt
    assert "P361" in site.source_refs[2].excerpt and "P625" in site.source_refs[2].excerpt


@pytest.mark.parametrize("position", [[181, 0], [0, -91], [True, 1], [float("nan"), 1], ["1", 1]])
def test_invalid_source_positions_are_not_converted_to_zero(position: list[Any]) -> None:
    row = record()
    row["coordinates"]["geometry"]["coordinates"] = [position]
    with pytest.raises(catalogue.CatalogueError, match="invalid WGS84"):
        catalogue.normalize_record(row)


def test_a_genuine_zero_longitude_is_not_confused_with_a_missing_value() -> None:
    row = record()
    row["coordinates"]["geometry"] = {"type": "Point", "coordinates": [0, 51]}
    assert catalogue.normalize_record(row).repr_point == (0, 51)


@pytest.mark.parametrize(
    "changes", [{"category": "Natural"}, {"id_no": "bad"}, {"region": "Other"}]
)
def test_incompatible_source_identity_or_selection_is_rejected(changes: dict[str, str]) -> None:
    row = record()
    row.update(changes)
    with pytest.raises(catalogue.CatalogueError):
        catalogue.normalize_record(row)


def test_country_names_are_resolved_from_membership_not_array_positions() -> None:
    rows = [
        {"iso_codes": ["FR"], "states_names": ["France"]},
        {"iso_codes": ["BE", "FR"], "states_names": ["France", "Belgium"]},
    ]
    assert catalogue.country_registry(rows) == {"FR": "France", "BE": "Belgium"}
    rows.append({"iso_codes": ["FR"], "states_names": ["Belgium"]})
    with pytest.raises(catalogue.CatalogueError, match="conflicting singleton"):
        catalogue.country_registry(rows)


def test_ambiguous_country_sets_do_not_acquire_guessed_labels() -> None:
    with pytest.raises(catalogue.CatalogueError, match="independently resolved"):
        catalogue.country_registry(
            [{"iso_codes": ["FR", "BE"], "states_names": ["Belgium", "France"]}]
        )


def test_bundled_catalogue_covers_all_source_partitions_and_preserves_curated_material() -> None:
    curated = load_curated_corpus()
    sites = catalogue.load_catalogue(curated)
    assert len(sites) == len({site.id for site in sites}) == 1534
    assert sum(site.geography is not None for site in sites) == 1033
    assert (
        len({code for site in sites if site.geography for code in site.geography.countries}) == 159
    )
    for before, after in zip(curated, sites[:600], strict=True):
        assert before.id == after.id
        assert before.repr_point == after.repr_point
        assert before.chronology == after.chronology
        assert before.description == after.description
    for site in sites[600:]:
        assert site.source_kind == "unesco" and site.chronology.status == "not_reviewed"
        assert site.geography is not None
    for site in sites[:600]:
        if site.geography:
            assert "保留原策展" in site.geography.note


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    for filename in (*catalogue.ARTIFACTS, "catalogue_manifest.json", "global_manifest.json"):
        shutil.copyfile(catalogue.DATA_DIR / filename, tmp_path / filename)
    return tmp_path


def rewrite_artifact(bundle: Path, filename: str, value: Any) -> None:
    path = bundle / filename
    path.write_text(json.dumps(value, ensure_ascii=False), "utf-8")
    manifest = json.loads((bundle / "catalogue_manifest.json").read_text("utf-8"))
    manifest["files"][filename]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (bundle / "catalogue_manifest.json").write_text(json.dumps(manifest), "utf-8")


def test_checksums_detect_accidental_data_changes(bundle: Path) -> None:
    with (bundle / "world_sites.json").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(catalogue.CatalogueError, match="checksum mismatch"):
        catalogue.load_catalogue(load_curated_corpus(), bundle)


@pytest.mark.parametrize(
    "change",
    ["license", "partition", "country-registry", "region-registry", "selection", "country-labels"],
)
def test_manifest_selection_license_and_registries_are_validated(bundle: Path, change: str) -> None:
    path = bundle / "catalogue_manifest.json"
    manifest = json.loads(path.read_text("utf-8"))
    if change == "license":
        manifest["source"]["license"] = "unknown"
    elif change == "partition":
        manifest["partition"]["added_ids"].pop()
    elif change == "country-registry":
        manifest["countries"].append(manifest["countries"][0])
    elif change == "selection":
        manifest["selection"]["categories"] = ["Natural"]
    elif change == "country-labels":
        first, second = manifest["countries"][:2]
        first["label"], second["label"] = second["label"], first["label"]
        manifest["country_registry_sha256"] = hashlib.sha256(
            catalogue._json_bytes(manifest["countries"])
        ).hexdigest()
    else:
        manifest["regions"].pop()
    path.write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(catalogue.CatalogueError):
        catalogue.load_catalogue(load_curated_corpus(), bundle)


def test_a_curated_identity_bridge_cannot_be_silently_permuted(bundle: Path) -> None:
    geography = json.loads((bundle / "world_geography.json").read_text("utf-8"))
    first, second = [key for key in geography if key.startswith("wd:")][:2]
    geography[first]["authority_id"], geography[second]["authority_id"] = (
        geography[second]["authority_id"],
        geography[first]["authority_id"],
    )
    rewrite_artifact(bundle, "world_geography.json", geography)
    with pytest.raises(catalogue.CatalogueError, match="identity bridge"):
        catalogue.load_catalogue(load_curated_corpus(), bundle)


def test_import_cannot_claim_completed_chronology_review(bundle: Path) -> None:
    rows = json.loads((bundle / "world_sites.json").read_text("utf-8"))
    rows[0]["chronology"].update(status="insufficient", method="metadata", reviewed_at="2026-11-04")
    rewrite_artifact(bundle, "world_sites.json", rows)
    with pytest.raises(catalogue.CatalogueError, match="cannot assert reviewed"):
        catalogue.load_catalogue(load_curated_corpus(), bundle)


@pytest.mark.parametrize("namespace", ["whc:", "wd:"])
def test_nullable_polar_contract_does_not_relax_world_catalogue_source_point_counts(
    bundle: Path, namespace: str,
) -> None:
    geography = json.loads((bundle / "world_geography.json").read_text("utf-8"))
    identifier = next(key for key in geography if key.startswith(namespace))
    geography[identifier]["point_count"] = 0
    rewrite_artifact(bundle, "world_geography.json", geography)
    rows = json.loads((bundle / "world_sites.json").read_text("utf-8"))
    for row in rows:
        if row["id"] == identifier:
            row["geography"]["point_count"] = 0
    rewrite_artifact(bundle, "world_sites.json", rows)
    with pytest.raises(catalogue.CatalogueError, match="at least one source point"):
        catalogue.load_catalogue(load_curated_corpus(), bundle)


@pytest.mark.parametrize("change", ["sources", "source-uri", "scope"])
def test_coordinate_fallback_preserves_the_independent_source_chain_and_scope(
    bundle: Path, change: str
) -> None:
    rows = json.loads((bundle / "world_sites.json").read_text("utf-8"))
    item = next(row for row in rows if row["id"] == "whc:1567")
    geography = json.loads((bundle / "world_geography.json").read_text("utf-8"))
    if change == "sources":
        item["source_refs"] = item["source_refs"][:1]
    elif change == "source-uri":
        item["source_uri"] = "https://whc.unesco.org/en/list/868/"
    else:
        item["geography"]["note"] = "A whole-property center."
        geography[item["id"]]["note"] = item["geography"]["note"]
        rewrite_artifact(bundle, "world_geography.json", geography)
    rewrite_artifact(bundle, "world_sites.json", rows)
    with pytest.raises(catalogue.CatalogueError):
        catalogue.load_catalogue(load_curated_corpus(), bundle)


def test_new_normalized_records_are_reproducible_independent_of_upstream_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [record("1"), record("2"), record("3")]
    rows[2]["category"] = "Natural"
    monkeypatch.setattr(
        catalogue,
        "EXPECTED_COUNTS",
        {
            "source": 3,
            "eligible": 2,
            "curated": 1,
            "added": 1,
            "excluded_natural": 1,
            "total": 601,
        },
    )
    monkeypatch.setattr(catalogue, "_load_sources", lambda _: (copy.deepcopy(rows), {}))
    for name in ("first", "second"):
        destination = tmp_path / name
        destination.mkdir()
        (destination / "global_manifest.json").write_text(
            json.dumps({"records": [{"id": "wd:Q1", "authority_id": "1"}]}), "utf-8"
        )
        catalogue.rebuild_catalogue(tmp_path, destination)
        rows.reverse()
    for filename in (*catalogue.ARTIFACTS, "catalogue_manifest.json"):
        assert (tmp_path / "first" / filename).read_bytes() == (
            tmp_path / "second" / filename
        ).read_bytes()
