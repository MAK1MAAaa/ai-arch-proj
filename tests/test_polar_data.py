"""Formal Antarctic heritage, unknown locations, pole coordinates and source integrity."""

from __future__ import annotations

import hashlib
import io
import json
import math
import shutil
from pathlib import Path
from typing import Any

import pytest

from archsearch import polar_data as polar
from archsearch.catalogue_data import load_catalogue
from archsearch.corpus import load_curated_corpus
from archsearch.domain import Site


def detail(number: str = "10") -> dict[str, Any]:
    return {
        "number": number,
        "id": 111,
        "type": {"id": 1, "name": "HSM"},
        "isDeDesignated": False,
        "name": "<i>Historic hut</i>",
        "summary": "<p>A hut erected in 1911.</p>",
        "historicalContext": "Used in 1911.<script>untrusted()</script>",
        "physicalFeaturesAndContext": "A source-reported historic hut.",
        "location": {
            "decimal": {"latitude": -70.5, "longitude": 0},
            "dms": {"latitude": "70°30′S", "longitude": "0°0′E"},
        },
        "designations": [{"id": 17, "name": "M 3 (2005)"}],
        "proponents": "Norway",
        "managementPlanReviewers": "Norway",
    }


def test_hsm_number_is_not_the_internal_api_identifier_or_designation_year() -> None:
    site, record = polar.normalize_detail(detail("10"), "a" * 64)
    assert site.id == "ats:hsm:10" and record["hsm_number"] == 10
    assert record["internal_id"] == 111
    assert site.source_uri.endswith("/apa-database/111")
    assert site.description == "A hut erected in 1911."
    assert "untrusted" not in site.details
    assert site.chronology.status == "not_reviewed" and not site.chronology.phases
    assert site.chronology.default_phase_id is None
    assert site.location_precision is None
    assert site.geography is not None
    assert site.geography.countries == [] and site.geography.regions == ["antarctica"]
    assert site.geography.authority_id == site.id
    assert site.source_refs[0].license == "CC BY 4.0"
    assert "2005" in record["measure_refs"][0]["name"]


@pytest.mark.parametrize(
    "changes",
    [
        {"type": {"id": 2, "name": "ASPA"}},
        {"type": {"id": 3, "name": "ASMA"}},
        {"isDeDesignated": True},
        {"number": "bad"},
        {"id": True},
    ],
)
def test_ordinary_protected_areas_and_invalid_formal_identities_are_not_hsm(
    changes: dict[str, Any],
) -> None:
    row = detail()
    row.update(changes)
    with pytest.raises(polar.PolarDataError):
        polar.normalize_detail(row, "a" * 64)


@pytest.mark.parametrize(
    "text,latitude,expected",
    [
        ("62°50'S", True, -62 - 50 / 60),
        ("59°41′W", False, -59 - 41 / 60),
        ("71° 20' 25.0007\" S", True, -71 - 20 / 60 - 25.0007 / 3600),
        ("90°0′0″S", True, -90),
        ("0°0′E", False, 0),
    ],
)
def test_explicit_source_dms_has_correct_hemisphere_and_precision(
    text: str,
    latitude: bool,
    expected: float,
) -> None:
    assert math.isclose(polar.dms_coordinate(text, latitude=latitude), expected)


@pytest.mark.parametrize(
    "text,latitude",
    [
        ("90°1′S", True),
        ("91°S", True),
        ("62°60′S", True),
        ("62°5'60\"S", True),
        ("181°E", False),
        ("62°W", True),
        ("70°N", False),
        ("unknown", True),
    ],
)
def test_invalid_or_ambiguous_dms_is_not_guessed(text: str, latitude: bool) -> None:
    with pytest.raises(polar.PolarDataError):
        polar.dms_coordinate(text, latitude=latitude)


def test_hsm34_uses_original_dms_instead_of_zero_or_a_neighbouring_base_center() -> None:
    row = detail("34")
    row["location"] = {
        "decimal": {"latitude": None, "longitude": None},
        "dms": {"latitude": "62°50'S", "longitude": "59°41'W"},
    }
    site, record = polar.normalize_detail(row, "a" * 64)
    assert site.repr_point == (-59 - 41 / 60, -62 - 50 / 60)
    assert record["coordinate_method"] == "dms_conversion"
    assert site.geography is not None and "不以邻近基地中心补点" in site.geography.note


def test_unknown_wreck_does_not_turn_a_last_sighting_reference_into_a_known_site() -> None:
    row = detail("95")
    row["location"]["decimal"] = {"latitude": -62, "longitude": -70}
    row["physicalFeaturesAndContext"] = (
        "The exact location is unknown, last sighting corresponds to 62ºS70ºW."
    )
    site, record = polar.normalize_detail(row, "a" * 64)
    assert site.repr_point is None
    assert site.geography is not None and site.geography.point_count == 0
    assert "[-70,-62]" in site.geography.note
    assert record["coordinate_method"] == "unknown_last_sighting"
    row["physicalFeaturesAndContext"] = "The wreck has now been located."
    with pytest.raises(polar.PolarDataError, match="semantics changed"):
        polar.normalize_detail(row, "a" * 64)


@pytest.mark.parametrize("latitude", [-90, -85.173278])
def test_pole_and_beyond_mercator_latitudes_are_preserved_without_clamping(latitude: float) -> None:
    row = detail("80")
    row["location"]["decimal"] = {"latitude": latitude, "longitude": 1}
    site, record = polar.normalize_detail(row, "a" * 64)
    assert site.repr_point == (1, latitude) and record["coordinate_method"] == "decimal"
    assert site.geography is not None and "禁止静默夹取" in site.geography.note


def test_missing_location_is_explicitly_nullable_only_for_the_ats_cohort() -> None:
    row = detail()
    row["location"] = {"decimal": {"latitude": None, "longitude": None}, "dms": {}}
    site, record = polar.normalize_detail(row, "a" * 64)
    assert site.repr_point is None and record["coordinate_method"] == "unknown"
    assert site.geography is not None and site.geography.point_count == 0


@pytest.mark.parametrize(
    "position",
    [
        {"latitude": True, "longitude": 1},
        {"latitude": -70, "longitude": None},
        {"latitude": -91, "longitude": 1},
        {"latitude": -70, "longitude": 181},
        {"latitude": float("nan"), "longitude": 1},
    ],
)
def test_invalid_numeric_source_positions_fail_instead_of_becoming_zero(
    position: dict[str, Any],
) -> None:
    row = detail()
    row["location"]["decimal"] = position
    with pytest.raises(polar.PolarDataError):
        polar.normalize_detail(row, "a" * 64)


@pytest.fixture(scope="module")
def base_sites() -> list[Site]:
    return load_catalogue(load_curated_corpus())


def test_bundled_cohort_preserves_previous_records_and_all_active_hsm(
    base_sites: list[Site],
) -> None:
    sites = polar.load_polar(base_sites)
    assert len(sites) == len({site.id for site in sites}) == 1625
    assert all(before is after for before, after in zip(base_sites, sites[:1534], strict=True))
    new = sites[1534:]
    assert len(new) == 91
    assert [site.id for site in new] == [f"ats:hsm:{number}" for number in polar.ACTIVE_NUMBERS]
    assert sum(site.repr_point is None for site in new) == 1
    assert (
        sum(
            site.repr_point is not None and abs(site.repr_point[1]) > polar.MERCATOR_MAX_LATITUDE
            for site in new
        )
        == 3
    )
    assert all(
        site.chronology.status == "not_reviewed" and not site.chronology.phases for site in new
    )


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    for name in ("polar_sites.json", "polar_manifest.json"):
        shutil.copyfile(polar.DATA_DIR / name, tmp_path / name)
    return tmp_path


@pytest.mark.parametrize(
    "change",
    [
        "license",
        "numbers",
        "region",
        "pins",
        "internal-id",
        "source-dms",
        "counts",
    ],
)
def test_manifest_source_identity_and_scope_are_frozen(
    base_sites: list[Site],
    bundle: Path,
    change: str,
) -> None:
    path = bundle / "polar_manifest.json"
    manifest = json.loads(path.read_text("utf-8"))
    if change == "license":
        manifest["source"]["license"] = "CC0"
    elif change == "numbers":
        manifest["partition"]["active_numbers"].append(12)
    elif change == "region":
        manifest["regions"][0]["label"] = "Norway"
    elif change == "pins":
        manifest["source"]["details_sha256_by_hsm_number"]["1"] = "b" * 64
    elif change == "internal-id":
        manifest["records"][0]["internal_id"] = 1
    elif change == "source-dms":
        manifest["records"][0]["source_dms"]["latitude"] = "85°S"
    else:
        manifest["counts"]["located"] = 91
    path.write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(polar.PolarDataError):
        polar.load_polar(base_sites, bundle)


@pytest.mark.parametrize("change", ["source-removed", "site-point-synthesized", "latitude-clamped"])
def test_rehashing_modified_data_does_not_bypass_the_frozen_semantic_contract(
    base_sites: list[Site],
    bundle: Path,
    change: str,
) -> None:
    path = bundle / "polar_sites.json"
    sites = json.loads(path.read_text("utf-8"))
    if change == "source-removed":
        sites[0]["source_refs"] = []
    elif change == "site-point-synthesized":
        next(row for row in sites if row["id"] == "ats:hsm:95")["repr_point"] = [-70, -62]
    else:
        sites[0]["repr_point"][1] = -85.0511287798
    path.write_text(json.dumps(sites), "utf-8")
    manifest_path = bundle / "polar_manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["files"]["polar_sites.json"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(polar.PolarDataError, match="checksum"):
        polar.load_polar(base_sites, bundle)


def test_valid_download_cache_is_reused_without_a_network_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "detail.json"
    path.write_bytes(b"verified")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("valid cache must not contact the network")

    monkeypatch.setattr(polar, "urlopen", forbidden)
    polar._download_file(
        path, "https://example.org/source", hashlib.sha256(b"verified").hexdigest()
    )


def test_changed_download_keeps_the_previous_cache_and_cleans_temporary_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "detail.json"
    path.write_bytes(b"previous cache")
    monkeypatch.setattr(polar, "urlopen", lambda *args, **kwargs: io.BytesIO(b"unexpected"))
    with pytest.raises(polar.PolarDataError, match="source changed"):
        polar._download_file(path, "https://example.org/source", "a" * 64)
    assert path.read_bytes() == b"previous cache"
    assert not list(tmp_path.glob("*.part"))
