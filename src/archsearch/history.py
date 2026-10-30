"""Pinned Cliopatria preparation and read-only historical boundary frames."""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import os
import sqlite3
import tempfile
import threading
import zipfile
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

VERSION = "v0.2.1"
SOURCE_COMMIT = "5f433377139a6eeaeacbdc894b70f8805b72c8b5"
ARCHIVE_SHA256 = "e10a4e429fca708788ff9e7572a95fce801fae55852d217cffabc1c59cd4eed4"
SOURCE_URI = "https://github.com/Seshat-Global-History-Databank/cliopatria"
ARCHIVE_URL = (
    "https://raw.githubusercontent.com/Seshat-Global-History-Databank/cliopatria/"
    f"{SOURCE_COMMIT}/cliopatria.geojson.zip"
)
ARCHIVE_MEMBER = "cliopatria_polities_only_v021.geojson"
EXPECTED_RECORDS = 13797
MIN_YEAR = -3400
MAX_YEAR = 2024
SCHEMA_VERSION = 1
DATABASE_NAME = "cliopatria-v0.2.1.sqlite3"
CACHE_MAX_FRAMES = 4
CACHE_MAX_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024
_PREPARE_LOCK = threading.Lock()
_RESOURCE_ERRORS = (
    OSError,
    ValueError,
    TypeError,
    KeyError,
    OverflowError,
    RecursionError,
    sqlite3.Error,
)


class HistoryUnavailable(RuntimeError):
    """Historical boundaries have not been prepared or failed local validation."""


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _source() -> dict[str, Any]:
    return {
        "name": "Cliopatria",
        "version": VERSION,
        "uri": SOURCE_URI,
        "release_uri": f"{SOURCE_URI}/releases/tag/{VERSION}",
        "commit": SOURCE_COMMIT,
        "archive_url": ARCHIVE_URL,
        "archive_sha256": ARCHIVE_SHA256,
        "member": ARCHIVE_MEMBER,
        "license": "CC BY 4.0",
        "license_uri": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": (
            "James S. Bennett and the Cliopatria contributors; Seshat Global History Databank."
        ),
        "doi": "https://doi.org/10.1038/s41597-025-04516-9",
        "limitations": (
            "疆域为来源对历史政体的一种重建，时间步长与空间尺度不一；"
            "名称、年代、控制范围和边界可能存在争议，不代表逐年精确实测疆界。"
        ),
    }


def _normalization() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "selection": "Type == POLITY; RELATION records are excluded.",
        "years": "BCE negative, CE positive, no selectable year 0; closed inclusive intervals.",
        "source_to_year_zero": "Original ToYear=0 is preserved; effective query end is -1.",
        "geometry": (
            "Original Polygon/MultiPolygon coordinates retained without simplification or repair; "
            "finite WGS84 coordinates, ring length and closure checked. Degenerate rings are "
            "retained and counted; geometric topology is not certified."
        ),
        "composites": "Nonempty original Components marks properties.composite=true.",
        "identity": (
            "SHA256 of version and canonical original feature; "
            "frame identity uses sorted active IDs."
        ),
        "site_association": (
            "Boundary frames do not establish the date or political membership of a Pleiades site."
        ),
    }


def validate_year(year: int) -> int:
    if type(year) is not int or year == 0 or not MIN_YEAR <= year <= MAX_YEAR:
        raise ValueError(f"年份必须是 {MIN_YEAR} 至 -1 或 1 至 {MAX_YEAR} 的整数。")
    return year


def _ordinal(year: int) -> int:
    return year if year < 0 else year - 1


def _year(ordinal: int) -> int:
    return ordinal if ordinal < 0 else ordinal + 1


def _geometry(geometry: Any) -> int:
    """Validate structure without editing coordinates; count degenerate source rings."""
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("历史疆域必须为 Polygon 或 MultiPolygon。")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("历史疆域坐标不能为空。")
    polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    degenerate = 0
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError("历史疆域 polygon 必须有外环。")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError("历史疆域环至少需要四个坐标。")
            positions = []
            for point in ring:
                if (
                    not isinstance(point, list)
                    or len(point) < 2
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(value)
                        for value in point
                    )
                ):
                    raise ValueError("历史疆域包含无效坐标。")
                if not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90:
                    raise ValueError("历史疆域坐标超出 WGS84 范围。")
                positions.append(tuple(point))
            if positions[0] != positions[-1]:
                raise ValueError("历史疆域环未闭合。")
            if len(set(positions)) < 3:
                degenerate += 1
    return degenerate


def _record(feature: Any) -> tuple[str, int, int, str, int, bool, bool]:
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise ValueError("历史疆域必须为 GeoJSON Feature。")
    properties = feature.get("properties")
    if not isinstance(properties, dict) or properties.get("Type") != "POLITY":
        raise ValueError("历史疆域记录类型不是 POLITY。")
    if not isinstance(properties.get("Name"), str) or not properties["Name"].strip():
        raise ValueError("历史政体名称不能为空。")
    start = validate_year(properties["FromYear"])
    raw_end = properties["ToYear"]
    if type(raw_end) is not int:
        raise ValueError("历史政体终止年份必须是整数。")
    end = validate_year(-1 if raw_end == 0 else raw_end)
    if start > end:
        raise ValueError("历史政体起止年份倒置。")
    components = properties.get("Components")
    if components is not None and not isinstance(components, str):
        raise ValueError("原始 Components 必须为字符串或 null。")
    composite = bool(components and components.strip())
    if "composite" in properties:
        raise ValueError("来源属性与保留的 composite 字段冲突。")
    degenerates = _geometry(feature.get("geometry"))
    identifier = f"cliopatria-{VERSION}-{_hash({'version': VERSION, 'record': feature})}"
    normalized = dict(feature)
    normalized["id"] = identifier
    normalized["properties"] = properties | {"composite": composite}
    return identifier, start, end, _canonical(normalized), degenerates, composite, raw_end == 0


def _frames(records: list[tuple[str, int, int, str]]) -> list[tuple[int, int, str]]:
    first, stop = _ordinal(MIN_YEAR), _ordinal(MAX_YEAR) + 1
    events: dict[int, tuple[set[str], set[str]]] = {first: (set(), set()), stop: (set(), set())}
    for identifier, start, end, _ in records:
        events.setdefault(_ordinal(start), (set(), set()))[0].add(identifier)
        events.setdefault(_ordinal(end) + 1, (set(), set()))[1].add(identifier)
    positions = sorted(events)
    active: set[str] = set()
    frames: list[tuple[int, int, str]] = []
    for index, position in enumerate(positions[:-1]):
        added, removed = events[position]
        active.difference_update(removed)
        active.update(added)
        frame_id = "cliopatria-frame-" + _hash(
            {
                "version": VERSION,
                "archive_sha256": ARCHIVE_SHA256,
                "normalization": SCHEMA_VERSION,
                "active_ids": sorted(active),
            }
        )
        start, end = _year(position), _year(positions[index + 1] - 1)
        if frames and frames[-1][2] == frame_id:
            frames[-1] = (frames[-1][0], end, frame_id)
        else:
            frames.append((start, end, frame_id))
    return frames


def _read_archive(archive: Path) -> tuple[list[tuple[str, int, int, str]], dict[str, int]]:
    with zipfile.ZipFile(archive) as bundle:
        member = bundle.getinfo(ARCHIVE_MEMBER)
        if member.is_dir() or member.file_size > MAX_MEMBER_BYTES or member.flag_bits & 1:
            raise ValueError("历史归档成员无效或超过大小限制。")
        with bundle.open(member) as stream:
            payload = json.load(stream)
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("历史数据不是 FeatureCollection。")
    features = payload.get("features")
    if not isinstance(features, list) or len(features) != EXPECTED_RECORDS:
        raise ValueError("历史来源记录数与固定版本不匹配。")
    counts = {
        "source_records": len(features),
        "polity_records": 0,
        "features": 0,
        "excluded_relation_records": 0,
        "duplicate_records": 0,
        "composite_features": 0,
        "source_to_year_zero": 0,
        "degenerate_rings": 0,
    }
    unique: dict[str, tuple[str, int, int, str]] = {}
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if isinstance(properties, dict) and properties.get("Type") == "RELATION":
            counts["excluded_relation_records"] += 1
            continue
        identifier, start, end, data, degenerate, composite, zero = _record(feature)
        counts["polity_records"] += 1
        if identifier in unique:
            counts["duplicate_records"] += 1
            continue
        unique[identifier] = (identifier, start, end, data)
        counts["degenerate_rings"] += degenerate
        counts["composite_features"] += int(composite)
        counts["source_to_year_zero"] += int(zero)
    counts["features"] = len(unique)
    return sorted(unique.values()), counts


def _download(home: Path) -> Path:
    directory = home / "downloads"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "cliopatria-v0.2.1.geojson.zip"
    if destination.is_file() and _file_hash(destination) == ARCHIVE_SHA256:
        return destination
    descriptor, name = tempfile.mkstemp(prefix="cliopatria-", suffix=".part", dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            request = Request(ARCHIVE_URL, headers={"User-Agent": "archsearch-mvp/0.1"})
            with urlopen(request, timeout=120) as response:
                size = 0
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    size += len(block)
                    if size > MAX_ARCHIVE_BYTES:
                        raise ValueError("历史归档超过固定下载大小限制。")
                    target.write(block)
        if _file_hash(temporary) != ARCHIVE_SHA256:
            raise ValueError("历史归档 SHA256 与固定版本不匹配。")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
    except sqlite3.Error:
        connection.close()
        raise
    return connection


def _row_digest(rows: Any) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(_canonical(list(row)).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _build(archive: Path, destination: Path) -> None:
    records, counts = _read_archive(archive)
    frames = _frames(records)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": _source(),
        "normalization": _normalization(),
        "counts": counts,
        "content_sha256": _row_digest(records),
        "frames_sha256": _hash(frames),
        "change_years": [frame[0] for frame in frames],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix="cliopatria-", suffix=".sqlite3", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        with closing(sqlite3.connect(temporary)) as connection, connection:
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            connection.execute(
                "CREATE TABLE features(id TEXT PRIMARY KEY,start_year INTEGER NOT NULL,"
                "end_year INTEGER NOT NULL,feature_json TEXT NOT NULL) WITHOUT ROWID"
            )
            connection.execute("CREATE INDEX features_temporal ON features(start_year,end_year)")
            connection.execute(
                "CREATE TABLE frames(start_year INTEGER PRIMARY KEY,end_year INTEGER NOT NULL,"
                "frame_id TEXT NOT NULL)"
            )
            connection.executemany("INSERT INTO features VALUES(?,?,?,?)", records)
            connection.executemany("INSERT INTO frames VALUES(?,?,?)", frames)
            connection.executemany(
                "INSERT INTO metadata VALUES(?,?)",
                [
                    ("manifest", _canonical(manifest)),
                    ("manifest_sha256", _hash(manifest)),
                ],
            )
        _validate_database(temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_database(path: Path) -> tuple[dict[str, Any], list[tuple[int, int, str]]]:
    with closing(_connect(path)) as connection:
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise ValueError("历史缓存 schema 版本不匹配。")
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("历史缓存 SQLite 完整性校验失败。")
        metadata = dict(connection.execute("SELECT key,value FROM metadata"))
        manifest = json.loads(metadata["manifest"])
        if not isinstance(manifest, dict) or _hash(manifest) != metadata["manifest_sha256"]:
            raise ValueError("历史缓存 manifest 校验失败。")
        if (
            manifest["schema_version"] != SCHEMA_VERSION
            or manifest["source"] != _source()
            or manifest["normalization"] != _normalization()
            or manifest["counts"]["source_records"] != EXPECTED_RECORDS
        ):
            raise ValueError("历史缓存不属于固定来源或查询规则版本。")
        rows = connection.execute(
            "SELECT id,start_year,end_year,feature_json FROM features ORDER BY id"
        )
        if _row_digest(rows) != manifest["content_sha256"]:
            raise ValueError("历史疆域记录校验失败。")
        if (
            connection.execute("SELECT count(*) FROM features").fetchone()[0]
            != manifest["counts"]["features"]
        ):
            raise ValueError("历史疆域记录数校验失败。")
        frames = [
            tuple(row)
            for row in connection.execute(
                "SELECT start_year,end_year,frame_id FROM frames ORDER BY start_year"
            )
        ]
        if not frames or _hash(frames) != manifest["frames_sha256"]:
            raise ValueError("历史时间帧校验失败。")
        if frames[0][0] != MIN_YEAR or frames[-1][1] != MAX_YEAR:
            raise ValueError("历史时间帧未完整覆盖允许范围。")
        previous = _ordinal(MIN_YEAR) - 1
        for start, end, frame_id in frames:
            validate_year(start)
            validate_year(end)
            if _ordinal(start) != previous + 1 or start > end or not isinstance(frame_id, str):
                raise ValueError("历史时间帧不连续或无效。")
            previous = _ordinal(end)
        if manifest["change_years"] != [frame[0] for frame in frames]:
            raise ValueError("历史时间断点校验失败。")
    return manifest, frames


def prepare_history(home: Path) -> dict[str, Any]:
    """Explicitly download the pinned archive and atomically publish a verified SQLite cache."""
    home = Path(home)
    with _PREPARE_LOCK:
        store = HistoryStore(home)
        if (status := store.status())["ready"]:
            return status | {"reused": True}
        try:
            archive = _download(home)
            _build(archive, store.path)
        except (*_RESOURCE_ERRORS, zipfile.BadZipFile) as error:
            raise HistoryUnavailable(f"历史疆域准备失败：{error}") from error
        status = store.status()
        if not status["ready"]:
            raise HistoryUnavailable(status["reason"])
        return status | {"reused": False}


class HistoryStore:
    """Thread-safe, bounded frame cache; every access stays local and detects file replacement."""

    def __init__(self, home: Path) -> None:
        self.path = Path(home) / "history" / DATABASE_NAME
        self._lock = threading.RLock()
        self._signature: tuple[int, int, int] | None = None
        self._checked = False
        self._manifest: dict[str, Any] | None = None
        self._frames: list[tuple[int, int, str]] = []
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_bytes = 0
        self._reason = "历史疆域缓存尚未准备，请先准备历史数据。"

    def _stat(self) -> tuple[int, int, int] | None:
        try:
            stat = self.path.stat()
            return stat.st_mtime_ns, stat.st_size, stat.st_ino
        except OSError:
            return None

    def _refresh(self) -> None:
        signature = self._stat()
        if signature == self._signature and self._checked:
            return
        self._manifest = None
        self._frames = []
        self._cache.clear()
        self._cache_bytes = 0
        self._signature = signature
        self._checked = True
        if signature is None:
            self._reason = "历史疆域缓存尚未准备，请先准备历史数据。"
            return
        try:
            manifest, frames = _validate_database(self.path)
            if signature != self._stat():
                raise ValueError("历史疆域缓存正在更新，请稍后重试。")
            self._manifest, self._frames = manifest, frames
            self._reason = ""
        except _RESOURCE_ERRORS as error:
            self._reason = f"历史疆域缓存不可用：{error} 请重新准备历史数据。"

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._refresh()
            return {
                "ready": self._manifest is not None,
                "reason": self._reason or None,
                "version": VERSION,
                "min_year": MIN_YEAR,
                "max_year": MAX_YEAR,
                "change_years": list(self._manifest["change_years"]) if self._manifest else [],
                "feature_count": self._manifest["counts"]["features"] if self._manifest else 0,
                "counts": dict(self._manifest["counts"]) if self._manifest else None,
                "source": _source(),
                "normalization": _normalization(),
            }

    def boundaries(self, year: int) -> tuple[dict[str, Any], str]:
        validate_year(year)
        with self._lock:
            self._refresh()
            if self._manifest is None:
                raise HistoryUnavailable(self._reason)
            index = bisect.bisect_right([frame[0] for frame in self._frames], year) - 1
            start, end, frame_id = self._frames[index]
            try:
                if frame_id not in self._cache:
                    with closing(_connect(self.path)) as connection:
                        rows = connection.execute(
                            "SELECT feature_json FROM features WHERE start_year<=? "
                            "AND end_year>=? ORDER BY id",
                            (year, year),
                        )
                        data = (
                            '{"type":"FeatureCollection","features":['
                            + ",".join(row[0] for row in rows)
                            + "]}"
                        ).encode("utf-8")
                    if self._stat() != self._signature:
                        raise ValueError("历史疆域缓存正在更新，请重试。")
                    if len(data) <= CACHE_MAX_BYTES:
                        self._cache[frame_id] = data
                        self._cache_bytes += len(data)
                        while (
                            len(self._cache) > CACHE_MAX_FRAMES
                            or self._cache_bytes > CACHE_MAX_BYTES
                        ):
                            _, removed = self._cache.popitem(last=False)
                            self._cache_bytes -= len(removed)
                else:
                    data = self._cache[frame_id]
                    self._cache.move_to_end(frame_id)
                collection: dict[str, Any] = json.loads(data)
                if self._stat() != self._signature:
                    raise ValueError("历史疆域缓存正在更新，请重试。")
            except _RESOURCE_ERRORS as error:
                self._manifest = None
                self._cache.clear()
                self._cache_bytes = 0
                self._reason = f"历史疆域查询失败：{error} 请重新准备历史数据。"
                raise HistoryUnavailable(self._reason) from error
            metadata = {
                "year": year,
                "valid_from": start,
                "valid_to": end,
                "frame_id": frame_id,
                "source": _source(),
                "normalization": _normalization(),
                "previous_change_year": self._frames[index - 1][0] if index > 0 else None,
                "next_change_year": self._frames[index + 1][0]
                if index + 1 < len(self._frames)
                else None,
            }
            collection["metadata"] = metadata
            etag = '"' + _hash({"manifest": _hash(self._manifest), "metadata": metadata}) + '"'
            return collection, etag
