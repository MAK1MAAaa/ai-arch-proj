"""Offline preparation, source preservation, BCE/CE frames and bounded cache integrity."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from archsearch import history
from archsearch.history import HistoryStore, HistoryUnavailable, prepare_history


def feature(name: str, start: int, end: int, **properties: Any) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {
            "Name": name,
            "FromYear": start,
            "ToYear": end,
            "Area": 123.4,
            "Type": "POLITY",
            "Wikipedia": name,
            "Wikidata": "Q123",
            "SeshatID": "example",
            "Components": "",
            "MemberOf": "",
            **properties,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[0.0, 0.0], [2.0, 0.0], [0.0, 2.0], [0.0, 0.0]],
            ],
        },
    }


def sample_features() -> list[dict[str, Any]]:
    return [
        feature("Before CE", -3, 0, extra_source_attribute={"preserve": True}),
        feature("After BCE", 1, 2),
        feature("Composite", -2, 2, Components="Before CE;After BCE"),
        feature("Late", 2, 3),
        feature("Excluded relation", -3, 3, Type="RELATION"),
    ]


def archive(home: Path, features: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> Path:
    path = home / "downloads" / "cliopatria-v0.2.1.geojson.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            history.ARCHIVE_MEMBER,
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": features,
                }
            ),
        )
        bundle.writestr("../must-not-be-extracted.txt", "untrusted archive member")
    monkeypatch.setattr(history, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(history, "EXPECTED_RECORDS", len(features))
    return path


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, HistoryStore]:
    def no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("fixture and serving must not access a network")

    monkeypatch.setattr(history, "urlopen", no_network)
    archive(tmp_path, sample_features(), monkeypatch)
    result = prepare_history(tmp_path)
    assert result["ready"] is True and result["reused"] is False
    return tmp_path, HistoryStore(tmp_path)


def names(collection: dict[str, Any]) -> set[str]:
    return {row["properties"]["Name"] for row in collection["features"]}


def test_unprepared_status_is_safe_read_only_and_offline(tmp_path: Path) -> None:
    home = tmp_path / "not-created"
    store = HistoryStore(home)
    status = store.status()
    assert status["ready"] is False and status["reason"]
    assert status["change_years"] == []
    assert not home.exists()
    with pytest.raises(HistoryUnavailable):
        store.boundaries(117)


@pytest.mark.parametrize("year", [0, -3401, 2025, True, False, 117.0, "117", None])
def test_invalid_year_rejected_before_cache_access(tmp_path: Path, year: Any) -> None:
    with pytest.raises(ValueError, match="年份"):
        HistoryStore(tmp_path).boundaries(year)


def test_closed_intervals_skip_zero_and_preserve_raw_properties(
    prepared: tuple[Path, HistoryStore],
) -> None:
    home, store = prepared
    before, _ = store.boundaries(-1)
    after, _ = store.boundaries(1)
    assert names(before) == {"Before CE", "Composite"}
    assert names(after) == {"After BCE", "Composite"}
    assert names(store.boundaries(2)[0]) == {"After BCE", "Composite", "Late"}
    assert names(store.boundaries(3)[0]) == {"Late"}
    row = next(row for row in before["features"] if row["properties"]["Name"] == "Before CE")
    assert row["properties"]["ToYear"] == 0
    assert row["properties"]["extra_source_attribute"] == {"preserve": True}
    assert row["properties"]["composite"] is False
    assert (
        next(row for row in before["features"] if row["properties"]["Name"] == "Composite")[
            "properties"
        ]["composite"]
        is True
    )
    assert not (home.parent / "must-not-be-extracted.txt").exists()
    assert store.status()["counts"] == {
        "source_records": 5,
        "polity_records": 4,
        "features": 4,
        "excluded_relation_records": 1,
        "duplicate_records": 0,
        "composite_features": 1,
        "source_to_year_zero": 1,
        "degenerate_rings": 0,
    }


def test_frames_follow_global_id_set_not_just_feature_count(
    prepared: tuple[Path, HistoryStore],
) -> None:
    _, store = prepared
    assert store.status()["change_years"] == [-3400, -3, -2, 1, 2, 3, 4]
    first, first_etag = store.boundaries(-2)
    same, same_etag = store.boundaries(-1)
    different, _ = store.boundaries(1)
    assert first["metadata"]["valid_from"] == -2
    assert first["metadata"]["valid_to"] == -1
    assert first["metadata"]["frame_id"] == same["metadata"]["frame_id"]
    assert first_etag != same_etag
    assert first["metadata"]["frame_id"] != different["metadata"]["frame_id"]
    assert len(first["features"]) == len(different["features"])
    assert first["metadata"]["next_change_year"] == 1
    assert first["metadata"]["previous_change_year"] == -3
    assert first_etag.startswith('"') and first_etag.endswith('"')
    assert store.boundaries(-2)[1] == first_etag
    assert store.boundaries(-3400)[0]["metadata"]["valid_from"] == -3400
    assert store.boundaries(2024)[0]["metadata"]["valid_to"] == 2024


def test_empty_frames_have_explicit_range_and_provenance(
    prepared: tuple[Path, HistoryStore],
) -> None:
    _, store = prepared
    result, _ = store.boundaries(117)
    assert result["type"] == "FeatureCollection" and result["features"] == []
    assert result["metadata"]["valid_from"] == 4
    assert result["metadata"]["valid_to"] == 2024
    source = result["metadata"]["source"]
    assert source["version"] == "v0.2.1" and source["license"] == "CC BY 4.0"
    assert source["commit"] == history.SOURCE_COMMIT and source["limitations"]
    assert "not establish" in result["metadata"]["normalization"]["site_association"]


def test_valid_preparation_reuses_database_without_archive_or_network(
    prepared: tuple[Path, HistoryStore],
) -> None:
    home, store = prepared
    path = home / "downloads" / "cliopatria-v0.2.1.geojson.zip"
    path.unlink()
    before = store.path.read_bytes()
    status = prepare_history(home)
    assert status["reused"] is True
    assert store.path.read_bytes() == before


def test_returned_values_do_not_mutate_cached_frames(prepared: tuple[Path, HistoryStore]) -> None:
    _, store = prepared
    result, etag = store.boundaries(-2)
    result["features"][0]["geometry"]["coordinates"][0][0][0] = 99
    result["metadata"]["source"]["name"] = "changed"
    status = store.status()
    status["change_years"].clear()
    second, second_etag = store.boundaries(-2)
    assert second_etag == etag
    assert second["features"][0]["geometry"]["coordinates"][0][0][0] == 0
    assert second["metadata"]["source"]["name"] == "Cliopatria"
    assert store.status()["change_years"]


def test_frame_cache_has_entry_and_byte_limits(
    prepared: tuple[Path, HistoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store = prepared
    monkeypatch.setattr(history, "CACHE_MAX_FRAMES", 2)
    for year in (-3, -2, 1, 2, 3, 117):
        store.boundaries(year)
        assert len(store._cache) <= 2
        assert store._cache_bytes <= history.CACHE_MAX_BYTES
    store._cache.clear()
    store._cache_bytes = 0
    monkeypatch.setattr(history, "CACHE_MAX_BYTES", 1)
    assert names(store.boundaries(-3)[0]) == {"Before CE"}
    assert not store._cache and store._cache_bytes == 0


def test_changed_or_deleted_database_invalidates_existing_cache(
    prepared: tuple[Path, HistoryStore],
) -> None:
    _, store = prepared
    store.boundaries(-2)
    with closing(sqlite3.connect(store.path)) as connection, connection:
        connection.execute(
            "UPDATE features SET feature_json='{}' WHERE id=(SELECT min(id) FROM features)"
        )
    stat = store.path.stat()
    os.utime(store.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert store.status()["ready"] is False
    assert not store._cache
    with pytest.raises(HistoryUnavailable, match="校验"):
        store.boundaries(-2)
    store.path.unlink()
    assert store.status()["ready"] is False


def test_corrupt_database_is_reported_without_application_failure(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    store.path.parent.mkdir()
    store.path.write_bytes(b"not a sqlite database")
    assert store.status()["ready"] is False
    with pytest.raises(HistoryUnavailable):
        store.boundaries(117)


def test_stable_identity_uses_canonical_source_not_array_order() -> None:
    first = feature("Example", -10, 10)
    reordered = dict(reversed(list(first.items())))
    reordered["properties"] = dict(reversed(list(first["properties"].items())))
    assert history._record(first)[0] == history._record(reordered)[0]
    changed = copy.deepcopy(first)
    changed["properties"]["MemberOf"] = "Changed"
    assert history._record(first)[0] != history._record(changed)[0]


@pytest.mark.parametrize("problem", ["open", "short", "nonfinite", "range", "bool", "type"])
def test_invalid_geometry_fails_preparation_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    value = feature("Invalid", -1, 1)
    ring = value["geometry"]["coordinates"][0]
    if problem == "open":
        ring[-1] = [1, 1]
    elif problem == "short":
        value["geometry"]["coordinates"][0] = ring[:3]
    elif problem == "nonfinite":
        ring[1][0] = float("inf")
    elif problem == "range":
        ring[1][0] = 181
    elif problem == "bool":
        ring[1][0] = True
    else:
        value["geometry"]["type"] = "LineString"
    archive(tmp_path, [value], monkeypatch)
    with pytest.raises(HistoryUnavailable):
        prepare_history(tmp_path)
    assert not HistoryStore(tmp_path).path.exists()


def test_degenerate_source_rings_are_retained_and_disclosed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = feature("Degenerate original", -1, 1)
    value["geometry"]["coordinates"] = [[[0, 0], [1, 1], [0, 0], [0, 0]]]
    archive(tmp_path, [value], monkeypatch)
    assert prepare_history(tmp_path)["counts"]["degenerate_rings"] == 1
    result, _ = HistoryStore(tmp_path).boundaries(-1)
    assert result["features"][0]["geometry"] == value["geometry"]
    assert "not certified" in result["metadata"]["normalization"]["geometry"]


def test_duplicate_records_are_deduplicated_without_losing_traceability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = feature("Duplicate", -1, 1)
    archive(tmp_path, [value, copy.deepcopy(value)], monkeypatch)
    status = prepare_history(tmp_path)
    assert status["counts"]["duplicate_records"] == 1
    assert status["feature_count"] == 1


def test_download_hash_failure_preserves_prior_file_and_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "downloads" / "cliopatria-v0.2.1.geojson.zip"
    path.parent.mkdir()
    path.write_bytes(b"old invalid archive")
    monkeypatch.setattr(history, "urlopen", lambda *a, **k: io.BytesIO(b"new invalid archive"))
    with pytest.raises(HistoryUnavailable, match="SHA256"):
        prepare_history(tmp_path)
    assert path.read_bytes() == b"old invalid archive"
    assert not HistoryStore(tmp_path).path.exists()
    assert not list(path.parent.glob("*.part"))


def test_failed_rebuild_preserves_previous_published_database(
    prepared: tuple[Path, HistoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, store = prepared
    before = store.path.read_bytes()
    bad = feature("Bad dates", 2, 1)
    path = archive(home, [bad], monkeypatch)
    with pytest.raises(ValueError, match="倒置"):
        history._build(path, store.path)
    assert store.path.read_bytes() == before
    assert set(store.path.parent.glob("cliopatria-*.sqlite3")) == {store.path}


def test_validation_failure_after_build_does_not_replace_published_database(
    prepared: tuple[Path, HistoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, store = prepared
    before = store.path.read_bytes()

    def fail_validation(path: Path) -> Any:
        assert path != store.path and path.exists()
        raise ValueError("simulated post-build validation failure")

    monkeypatch.setattr(history, "_validate_database", fail_validation)
    with pytest.raises(ValueError, match="post-build"):
        history._build(home / "downloads" / "cliopatria-v0.2.1.geojson.zip", store.path)
    assert store.path.read_bytes() == before
    assert set(store.path.parent.glob("cliopatria-*.sqlite3")) == {store.path}


def test_successful_download_verifies_archive_and_reuses_it_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = archive(tmp_path / "source", sample_features(), monkeypatch).read_bytes()
    calls = []

    def download(request: Any, timeout: int) -> io.BytesIO:
        calls.append(request.full_url)
        assert timeout == 120
        return io.BytesIO(source)

    monkeypatch.setattr(history, "urlopen", download)
    home = tmp_path / "destination"
    assert prepare_history(home)["ready"] is True
    assert calls == [history.ARCHIVE_URL]
    assert prepare_history(home)["reused"] is True
    assert len(calls) == 1


def test_corrupt_cache_can_be_repaired_without_network(
    prepared: tuple[Path, HistoryStore],
) -> None:
    home, store = prepared
    store.path.write_bytes(b"corrupt database")
    assert store.status()["ready"] is False
    assert prepare_history(home)["ready"] is True
    assert names(store.boundaries(-3)[0]) == {"Before CE"}


def test_multipolygon_holes_and_coordinate_order_are_not_rewritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = feature("Multipolygon", -1, 1)
    value["geometry"] = {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [[-180, -90], [180, -90], [180, 90], [-180, -90]],
                [[1, 1], [1, 2], [2, 1], [1, 1]],
            ]
        ],
    }
    archive(tmp_path, [value], monkeypatch)
    prepare_history(tmp_path)
    assert HistoryStore(tmp_path).boundaries(1)[0]["features"][0]["geometry"] == value["geometry"]
