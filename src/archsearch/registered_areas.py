"""Preserve public modern register rings without creating representative coordinates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from archsearch.coverage import SpatialSource
from archsearch.supplement_data import SourceArtifact

DATA_DIR = Path(__file__).with_name("data")
AREAS_FILE = "registered_areas.json"
AREAS_VERSION = "registered-areas-v1"
AREAS_SHA256 = "2ffa50621c5a1b685770c252e284ca78e58b0e4753a84574ac1e97c9af759ece"
LABEL: Literal["现代遗产登记范围"] = "现代遗产登记范围"
MAX_SOURCE_BYTES = 5 * 1024 * 1024
SERVICE_PATH = (
    "/gispubmap/rest/services/ogc_services/National_Heritage_List/FeatureServer/0/query"
)
PREPARE = "请运行 uv run --no-sync python -m archsearch.registered_areas --rebuild 修复登记范围。"
NOTE = (
    "这是来源发布的现代遗产登记范围，不是古代遗址轮廓、历史疆域或访客开放范围。"
    "保留来源全部环与原始经纬度；没有计算代表点、质心或推断历史政治归属。"
    "原始地理基准为GDA94；WGS84转换由提供者执行。来源可能概化边界，"
    "本项目未验证逐处边界的测量精度或完整拓扑。"
)


class RegisteredAreasError(RuntimeError):
    """An immutable approved register geometry or its local sidecar differs."""


class RegisteredArea(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    source_index: StrictInt = Field(ge=0)
    provider_object_id: StrictInt = Field(gt=0)
    title: str = Field(min_length=1)
    source: SpatialSource
    geometry_type: Literal["esriGeometryPolygon"] = "esriGeometryPolygon"
    rings: list[list[tuple[float, float]]] = Field(min_length=1)

    @field_validator("rings", mode="before")
    @classmethod
    def validate_rings(cls, rings: Any) -> Any:
        if not isinstance(rings, list) or not rings:
            raise ValueError("registered geometry requires the original nonempty rings")
        for ring in rings:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("registered source rings must be closed and untruncated")
            for point in ring:
                if not isinstance(point, list | tuple) or len(point) != 2 or any(
                    type(value) not in {int, float} or not math.isfinite(value) for value in point
                ) or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
                    raise ValueError("registered vertices require finite WGS84 longitude/latitude")
            if len({tuple(point) for point in ring}) < 3:
                raise ValueError("registered source ring collapses to fewer than three positions")
        return rings


class RegisteredAreasResponse(BaseModel):
    site_id: str
    corpus_version: str
    ready: bool
    reason: str | None = None
    version: str | None = None
    label: Literal["现代遗产登记范围"] = LABEL
    note: str = NOTE
    features: list[RegisteredArea] = Field(default_factory=list)


class RegisteredAreasStatus(BaseModel):
    ready: bool
    reason: str | None = None
    version: str | None = None
    label: Literal["现代遗产登记范围"] = LABEL
    sites: int = 0
    features: int = 0
    rings: int = 0
    coordinate_records: int = 0


class AreaInput(BaseModel):
    """The minimal independently reviewed identity-to-raw-geometry compilation contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    site_id: str
    title: str
    place_id: StrictInt = Field(gt=0)
    artifact: SourceArtifact
    source_rows: list[dict[str, Any]] = Field(min_length=1)
    feature_ids: list[StrictInt] = Field(min_length=1)
    ring_count: StrictInt = Field(gt=0)
    coordinate_records: StrictInt = Field(gt=0)


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_origin(record: AreaInput) -> None:
    uri = urlsplit(record.artifact.uri)
    query = parse_qs(uri.query)
    if (
        uri.scheme != "https" or uri.netloc != "gis.environment.gov.au"
        or uri.path != SERVICE_PATH
        or query.get("where") != [f"PLACE_ID={record.place_id}"]
        or query.get("outFields") != ["*"] or query.get("returnGeometry") != ["true"]
        or query.get("outSR") != ["4326"] or query.get("orderByFields") != ["OBJECTID ASC"]
    ):
        raise RegisteredAreasError("registered geometry origin or query scope differs")


def compile_source_areas(
    records: list[AreaInput], cache_dir: Path, review_sha256: str,
) -> dict[str, Any]:
    """Verify exact original feature groups and preserve Esri rings without topology conversion."""
    if len(review_sha256) != 64 or any(char not in "0123456789abcdef" for char in review_sha256):
        raise RegisteredAreasError("registered areas require a complete reviewed contract hash")
    root = Path(cache_dir).resolve()
    sites: dict[str, list[dict[str, Any]]] = {}
    for record in sorted(records, key=lambda row: row.site_id):
        _validate_origin(record)
        if record.site_id in sites:
            raise RegisteredAreasError("duplicate reviewed area identity")
        artifact = record.artifact
        path = (root / artifact.filename).resolve()
        if not path.is_relative_to(root) or path.stat().st_size > MAX_SOURCE_BYTES:
            raise RegisteredAreasError("registered source path or size differs from its contract")
        raw = path.read_bytes()
        if _hash(raw) != artifact.sha256:
            raise RegisteredAreasError("registered source bytes differ from the reviewed snapshot")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RegisteredAreasError("registered source requires an ArcGIS response object")
        reference = value.get("spatialReference")
        if (value.get("geometryType") != "esriGeometryPolygon"
                or not isinstance(reference, dict) or reference.get("wkid") != 4326
                or any(item != 4326 for item in reference.values())
                or value.get("exceededTransferLimit") or "error" in value):
            raise RegisteredAreasError("registered source CRS, geometry or completeness differs")
        features = value.get("features")
        if not isinstance(features, list) or len(features) != len(record.source_rows):
            raise RegisteredAreasError("registered source feature group is incomplete")
        ids = [row.get("OBJECTID") for row in record.source_rows]
        if (ids != record.feature_ids or len(set(ids)) != len(ids)
                or any(type(item) is not int for item in ids) or ids != sorted(ids)):
            raise RegisteredAreasError("reviewed original feature identities or order differs")
        source = SpatialSource(
            name="Australian National Heritage List public registered range",
            uri=artifact.uri, version="australia-nhl-v1", sha256=artifact.sha256,
            license="CC BY 3.0 AU", license_uri="https://creativecommons.org/licenses/by/3.0/au/",
        )
        compiled: list[RegisteredArea] = []
        for index, (feature, original) in enumerate(zip(features, record.source_rows, strict=True)):
            if (not isinstance(feature, dict) or feature.get("attributes") != original
                    or original.get("PLACE_ID") != record.place_id):
                raise RegisteredAreasError("geometry attributes differ from reviewed source facts")
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict) or set(geometry) != {"rings"}:
                raise RegisteredAreasError("geometry requires explicit original XY rings")
            compiled.append(RegisteredArea(
                id=f"{record.site_id}:OBJECTID:{record.feature_ids[index]}",
                source_index=index, provider_object_id=record.feature_ids[index],
                title=record.title, source=source, rings=geometry["rings"],
            ))
        if (sum(len(area.rings) for area in compiled) != record.ring_count
                or sum(len(ring) for area in compiled for ring in area.rings)
                != record.coordinate_records):
            raise RegisteredAreasError("registered source rings or vertices were omitted")
        sites[record.site_id] = [area.model_dump(mode="json") for area in compiled]
    return {
        "schema_version": 1, "version": AREAS_VERSION, "review_sha256": review_sha256,
        "label": LABEL, "note": NOTE, "sites": sites,
        "processing": (
            "Unmodified provider WGS84 Esri rings. "
            "No centroid, representative or GeoJSON topology inference."
        ),
    }


def australia_inputs(data_dir: Path) -> tuple[list[AreaInput], str]:
    from archsearch import australia_data

    try:
        spec = australia_data._spec(data_dir)
    except australia_data.AustraliaError as error:
        raise RegisteredAreasError(str(error)) from error
    records: list[AreaInput] = []
    for record in spec.records:
        area = record.registered_range
        records.append(AreaInput(
            site_id=record.site.id, title=record.site.title,
            place_id=record.source_features[0].place_id,
            artifact=area.artifact,
            source_rows=[row.model_dump(mode="json", by_alias=True) for row in area.source_rows],
            feature_ids=area.feature_ids, ring_count=area.ring_count,
            coordinate_records=area.coordinate_records,
        ))
    return records, australia_data.SPEC_SHA256


def download_sources(records: list[AreaInput], cache_dir: Path) -> None:
    """Explicit preparation only: verify fixed public responses before atomic publication."""
    root = cache_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for record in records:
        _validate_origin(record)
        artifact = record.artifact
        target = (root / artifact.filename).resolve()
        if not target.is_relative_to(root):
            raise RegisteredAreasError("registered source path escapes its cache")
        if target.exists():
            if (target.stat().st_size > MAX_SOURCE_BYTES
                    or _hash(target.read_bytes()) != artifact.sha256):
                raise RegisteredAreasError("cached source differs; original not overwritten")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + "." + uuid4().hex + ".part")
        try:
            request = Request(artifact.uri, headers={"User-Agent": "archsearch/0.1"})
            total = 0
            digest = hashlib.sha256()
            with urlopen(request, timeout=60) as response, temporary.open("xb") as output:
                while block := response.read(64 * 1024):
                    total += len(block)
                    if total > MAX_SOURCE_BYTES:
                        raise RegisteredAreasError("source exceeds the reviewed size limit")
                    digest.update(block)
                    output.write(block)
            if digest.hexdigest() != artifact.sha256:
                raise RegisteredAreasError("downloaded source differs from its frozen SHA")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def rebuild_registered_areas(
    cache_dir: Path, data_dir: Path = DATA_DIR,
) -> dict[str, int]:
    try:
        records, review = australia_inputs(data_dir)
        payload = _bytes(compile_source_areas(records, cache_dir, review))
        if _hash(payload) != AREAS_SHA256:
            raise RegisteredAreasError("registered area sidecar differs from its independent pin")
        (data_dir / AREAS_FILE).write_bytes(payload)
        return {"sites": len(records), "features": sum(len(row.feature_ids) for row in records)}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RegisteredAreasError(f"cannot rebuild registered areas: {error}") from error


class RegisteredAreasIndex:
    """Load an optional fixed local outline layer independently from point search."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.features: dict[str, list[RegisteredArea]] = {}
        self.ready = True
        self.reason: str | None = None
        self.version: str | None = None
        if not (data_dir / "australia_manifest.json").exists():
            return
        try:
            payload = (data_dir / AREAS_FILE).read_bytes()
            if _hash(payload) != AREAS_SHA256:
                raise RegisteredAreasError("registered area sidecar differs from its frozen pin")
            records, review = australia_inputs(data_dir)
            value = json.loads(payload)
            if (not isinstance(value, dict) or not isinstance(value.get("sites"), dict)
                    or value.get("schema_version") != 1 or value.get("version") != AREAS_VERSION
                    or value.get("review_sha256") != review or value.get("label") != LABEL
                    or value.get("note") != NOTE
                    or set(value["sites"]) != {record.site_id for record in records}):
                raise RegisteredAreasError("registered area version or identity set differs")
            if any(not isinstance(rows, list) for rows in value["sites"].values()):
                raise RegisteredAreasError("registered area feature groups must remain arrays")
            self.features = {key: [RegisteredArea.model_validate(row) for row in rows]
                             for key, rows in value["sites"].items()}
            for record in records:
                areas = self.features[record.site_id]
                if (len(areas) != len(record.feature_ids)
                        or [area.provider_object_id for area in areas] != record.feature_ids
                        or [area.source_index for area in areas] != list(range(len(areas)))
                        or sum(len(area.rings) for area in areas) != record.ring_count
                        or sum(len(ring) for area in areas for ring in area.rings)
                        != record.coordinate_records
                        or any(area.id != f"{record.site_id}:OBJECTID:{area.provider_object_id}"
                               or area.title != record.title
                               or area.source.uri != record.artifact.uri
                               or area.source.sha256 != record.artifact.sha256 for area in areas)):
                    raise RegisteredAreasError("area feature provenance or counts differ")
            self.version = AREAS_VERSION
        except (OSError, ValueError, KeyError, TypeError, RegisteredAreasError) as error:
            self.features = {}
            self.ready = False
            self.reason = f"现代登记范围不可用：{error} {PREPARE}"

    def response(self, site_id: str, corpus_version: str) -> RegisteredAreasResponse:
        return RegisteredAreasResponse(
            site_id=site_id, corpus_version=corpus_version, ready=self.ready,
            reason=self.reason, version=self.version,
            features=[row.model_copy(deep=True) for row in self.features.get(site_id, [])],
        )

    def status(self, site_ids: set[str] | None = None) -> RegisteredAreasStatus:
        values = [rows for key, rows in self.features.items()
                  if site_ids is None or key in site_ids]
        return RegisteredAreasStatus(
            ready=self.ready, reason=self.reason, version=self.version, sites=len(values),
            features=sum(len(rows) for rows in values),
            rings=sum(len(area.rings) for rows in values for area in rows),
            coordinate_records=sum(len(ring) for rows in values for area in rows
                                   for ring in area.rings),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", required=True)
    parser.add_argument("--download", action="store_true",
                        help="allow fixed source downloads during preparation only")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--source-cache", type=Path,
                        default=Path(".archsearch/downloads/australia-nhl-v1"))
    args = parser.parse_args()
    try:
        if args.download:
            records, _ = australia_inputs(args.data_dir)
            download_sources(records, args.source_cache)
        print(json.dumps(rebuild_registered_areas(args.source_cache, args.data_dir)))
    except (RegisteredAreasError, OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
