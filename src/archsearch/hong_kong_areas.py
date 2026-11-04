"""Compile original Hong Kong provider polygons offline with independent source pins."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from archsearch import hong_kong_data as hong_kong
from archsearch.coverage import SpatialSource
from archsearch.registered_areas import POLYGON_LABEL, AreaSourceGroup, RegisteredArea
from archsearch.supplement_data import SourceArtifact

DATA_DIR = Path(__file__).with_name("data")
AREAS_FILE = "hong_kong_areas.json"
AREAS_VERSION: Literal["hong-kong-polygons-v1"] = "hong-kong-polygons-v1"
AREA_SHA256 = "45e6be8c0884096dae69aa612fd64819ee995c8120f5fb0ef3f360d61b9b5c51"
SOURCE_REVIEW_SHA256 = "c4db9409b0c9ad76976ea0dec1b8950da6d9c944d7839eb1ffd449ce0d1440bc"
SOURCE_ROSTER_SHA256 = "0bf80d28eb24a3c23397519db82429ca58af83c036125473362de140a1de6f14"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_SIDECAR_BYTES = 8 * 1024 * 1024
MAX_SITES_BYTES = 8 * 1024 * 1024
SOURCE_NAME = (
    "Government of the Hong Kong Special Administrative Region / "
    "Common Spatial Data Infrastructure (CSDI) Portal / Antiquities and Monuments Office "
    "— source monument polygons"
)
NOTE = (
    "这是CSDI来源古迹多边形，不承诺法定保护边界、发掘轮廓或测量精度。"
    "原坐标系为香港1980（EPSG:2326），WGS84经纬度由提供者输出；"
    "保留全部来源环、顺序与数值，不合并或推断内外环，不计算质心或代表点。"
    "2026年10月新增的两项整体在1月空间版本未提供几何，成功空数组不表示数据损坏。"
)
PREPARE = (
    "请运行 uv run --no-sync python -m archsearch.hong_kong_areas --rebuild "
    "--source-cache <已核原始来源缓存> 修复香港来源多边形。"
)
PROCESSING = (
    "Unmodified provider outSR4326 Esri rings from the independently reviewed release. "
    "No local reprojection, centroid, representative point, merge or topology/hole inference."
)


class HongKongAreasError(RuntimeError):
    """A source polygon, whole-object binding or independently pinned sidecar differs."""


class AreaCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reviewed_sites: StrictInt = Field(ge=0)
    source_features: StrictInt = Field(ge=1)
    source_rings: StrictInt = Field(ge=1)
    source_coordinates: StrictInt = Field(ge=4)
    adopted_sites_with_geometry: StrictInt = Field(ge=0)
    adopted_features: StrictInt = Field(ge=0)
    adopted_rings: StrictInt = Field(ge=0)
    adopted_coordinates: StrictInt = Field(ge=0)


class AreaPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    version: Literal["hong-kong-polygons-v1"]
    source_spec_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source_roster_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    label: Literal["来源古迹多边形"]
    note: StrictStr
    processing: StrictStr
    site_ids: list[StrictStr]
    counts: AreaCounts
    sites: dict[str, list[dict[str, Any]]]


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise HongKongAreasError("香港多边形文件超过固定容量限制。")
    return raw


def _roster_hash(spec: hong_kong.HongKongSpec) -> str:
    return _hash(_bytes(hong_kong._source_roster(spec)))


def _counts(spec: hong_kong.HongKongSpec) -> AreaCounts:
    adopted = [binding for record in spec.records for binding in record.whole.source_features]
    return AreaCounts(
        reviewed_sites=len(spec.records),
        source_features=len(spec.source_feature_roster),
        source_rings=sum(row.ring_count for row in spec.source_feature_roster),
        source_coordinates=sum(row.coordinate_records for row in spec.source_feature_roster),
        adopted_sites_with_geometry=sum(bool(row.whole.source_features) for row in spec.records),
        adopted_features=len(adopted),
        adopted_rings=sum(row.ring_count for row in adopted),
        adopted_coordinates=sum(row.coordinate_records for row in adopted),
    )


def _validate_page_query(artifact: SourceArtifact, index: int) -> tuple[int, int]:
    parsed = urlsplit(artifact.uri)
    query = parse_qs(parsed.query, keep_blank_values=True)
    allowed = {
        "where",
        "outFields",
        "orderByFields",
        "resultOffset",
        "resultRecordCount",
        "returnGeometry",
        "outSR",
        "returnZ",
        "returnM",
        "f",
    }
    if (
        parsed.scheme != "https"
        or parsed.netloc != "portal.csdi.gov.hk"
        or parsed.path != urlsplit(hong_kong.QUERY_URI).path
        or parsed.fragment
        or set(query) != allowed
        or any(len(values) != 1 for values in query.values())
        or query.get("where") != ["1=1"]
        or query.get("outFields") != ["*"]
        or query.get("orderByFields") != ["OBJECTID"]
        or query.get("returnGeometry") != ["true"]
        or query.get("outSR") != ["4326"]
        or query.get("returnZ") != ["false"]
        or query.get("returnM") != ["false"]
        or query.get("f") != ["json"]
        or not re.fullmatch(r"0|[1-9]\d*", query.get("resultOffset", [""])[0])
        or not re.fullmatch(r"[1-9]\d*", query.get("resultRecordCount", [""])[0])
    ):
        raise HongKongAreasError("香港几何来源查询、分页或提供者坐标输出条件不符。")
    offset = int(query["resultOffset"][0])
    limit = int(query["resultRecordCount"][0])
    if offset != index * limit:
        raise HongKongAreasError("香港几何原始分页偏移不连续。")
    return offset, limit


def _source_features(
    spec: hong_kong.HongKongSpec,
    source_cache: Path,
) -> dict[int, dict[str, Any]]:
    hong_kong._validate_spec(spec)
    roster = spec.source_feature_roster
    ids = [row.source_row.object_id for row in roster]
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        raise HongKongAreasError("香港原始要素清单的身份或顺序不符。")
    pages: dict[int, tuple[SourceArtifact, list[hong_kong.HongKongFeatureBinding]]] = {}
    for binding in roster:
        if binding.page_index in pages and pages[binding.page_index][0] != binding.artifact:
            raise HongKongAreasError("香港同一原始页具有冲突来源。")
        pages.setdefault(binding.page_index, (binding.artifact, []))[1].append(binding)
    if sorted(pages) != list(range(len(pages))):
        raise HongKongAreasError("香港原始页序列缺失或未从零开始。")
    root = Path(source_cache).resolve()
    verified: dict[int, dict[str, Any]] = {}
    filenames: set[str] = set()
    total = len(roster)
    expected_offset = 0
    field_names = [
        field.alias or name for name, field in hong_kong.CsdiSourceRow.model_fields.items()
    ]
    for page_index, (artifact, bindings) in sorted(pages.items()):
        offset, limit = _validate_page_query(artifact, page_index)
        if offset != expected_offset or artifact.filename in filenames:
            raise HongKongAreasError("香港原始页重复或偏移不完整。")
        filenames.add(artifact.filename)
        path = (root / artifact.filename).resolve()
        if not path.is_relative_to(root):
            raise HongKongAreasError("香港原始页路径越过已指定的来源缓存。")
        raw = _read_bounded(path, MAX_SOURCE_BYTES)
        if _hash(raw) != artifact.sha256:
            raise HongKongAreasError("香港原始几何页与独立审查SHA不符。")
        page = json.loads(raw)
        reference = page.get("spatialReference") if isinstance(page, dict) else None
        if (
            not isinstance(page, dict)
            or "error" in page
            or page.get("geometryType") != "esriGeometryPolygon"
            or not isinstance(reference, dict)
            or reference.get("wkid") != 4326
            or set(reference) - {"wkid", "latestWkid"}
            or any(type(value) is not int or value != 4326 for value in reference.values())
            or page.get("exceededTransferLimit", False) is not (offset + limit < total)
        ):
            raise HongKongAreasError("香港原始页的实际坐标系、几何类型或分页状态不符。")
        features = page.get("features")
        expected_length = min(limit, total - offset)
        if (
            not isinstance(features, list)
            or len(features) != expected_length
            or len(bindings) != expected_length
            or [row.feature_index for row in bindings] != list(range(expected_length))
        ):
            raise HongKongAreasError("香港原始页的要素缺失、重排或未全部审核。")
        if "fields" in page and (
            not isinstance(page["fields"], list)
            or any(not isinstance(field, dict) for field in page["fields"])
            or [field.get("name") for field in page["fields"] if isinstance(field, dict)]
            != field_names
        ):
            raise HongKongAreasError("香港原始属性字段序列不符。")
        for binding, feature in zip(bindings, features, strict=True):
            if (
                not isinstance(feature, dict)
                or set(feature) != {"attributes", "geometry"}
                or not isinstance(feature["attributes"], dict)
                or list(feature["attributes"]) != field_names
                or feature["attributes"]
                != binding.source_row.model_dump(mode="json", by_alias=True)
                or hong_kong.feature_hash(feature) != binding.feature_sha256
            ):
                raise HongKongAreasError("香港几何要素的原属性或完整要素SHA不符。")
            geometry = feature["geometry"]
            if not isinstance(geometry, dict) or set(geometry) != {"rings"}:
                raise HongKongAreasError("香港来源几何必须保留原始XY环，不能添加点或拓扑。")
            RegisteredArea.validate_rings(geometry["rings"])
            if (
                len(geometry["rings"]) != binding.ring_count
                or sum(len(ring) for ring in geometry["rings"]) != binding.coordinate_records
            ):
                raise HongKongAreasError("香港原始环或顶点数量不符。")
            verified[binding.source_row.object_id] = feature
        expected_offset += expected_length
    if expected_offset != total or set(verified) != set(ids):
        raise HongKongAreasError("香港完整来源要素清单未被逐项验证。")
    return verified


def verify_hong_kong_area_cache(
    spec: hong_kong.HongKongSpec,
    source_cache: Path,
) -> dict[str, int]:
    """Verify all source rows, including held/existing/component decisions, without networking."""
    try:
        _source_features(spec, source_cache)
        return _counts(spec).model_dump()
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        RecursionError,
        hong_kong.HongKongError,
    ) as error:
        raise HongKongAreasError(f"无法核对香港原始多边形：{error}") from error


def _spatial_source(binding: hong_kong.HongKongFeatureBinding) -> SpatialSource:
    return SpatialSource(
        name=SOURCE_NAME,
        uri=binding.artifact.uri,
        version=hong_kong.LAYER_NAME,
        sha256=binding.artifact.sha256,
        license=hong_kong.CSDI_LICENSE,
        license_uri=hong_kong.TERMS_URI,
    )


def compile_hong_kong_areas(
    spec: hong_kong.HongKongSpec,
    source_cache: Path,
    *,
    review_sha256: str | None = None,
) -> dict[str, Any]:
    """Compile only included reviewed wholes while preserving every original source ring."""
    try:
        verified = _source_features(spec, source_cache)
        review_hash = review_sha256 or _hash(_bytes(spec.model_dump(mode="json", by_alias=True)))
        if re.fullmatch(r"[0-9a-f]{64}", review_hash) is None:
            raise HongKongAreasError("香港多边形需要完整的已审合同SHA。")
        sites: dict[str, list[dict[str, Any]]] = {}
        for record in sorted(spec.records, key=lambda row: row.whole.project_id):
            whole = record.whole
            compiled = []
            for index, binding in enumerate(
                sorted(whole.source_features, key=lambda row: row.source_row.object_id)
            ):
                feature = verified[binding.source_row.object_id]
                rings = feature["geometry"]["rings"]
                area = RegisteredArea(
                    id=f"{whole.project_id}:OBJECTID:{binding.source_row.object_id}",
                    source_index=index,
                    provider_object_id=binding.source_row.object_id,
                    title=binding.source_row.name or whole.title_en,
                    source=_spatial_source(binding),
                    rings=rings,
                ).model_dump(mode="json")
                area["rings"] = rings
                compiled.append(area)
            if compiled:
                sites[whole.project_id] = compiled
        payload = AreaPayload(
            schema_version=1,
            version=AREAS_VERSION,
            source_spec_sha256=review_hash,
            source_review_sha256=spec.independent_report_sha256,
            source_roster_sha256=_roster_hash(spec),
            label=POLYGON_LABEL,
            note=NOTE,
            processing=PROCESSING,
            site_ids=sorted(row.whole.project_id for row in spec.records),
            counts=_counts(spec),
            sites=sites,
        )
        return payload.model_dump(mode="json")
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        RecursionError,
        hong_kong.HongKongError,
    ) as error:
        raise HongKongAreasError(f"无法编译香港来源多边形：{error}") from error


def _require_pins(spec: hong_kong.HongKongSpec) -> None:
    if any(
        re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in (AREA_SHA256, SOURCE_REVIEW_SHA256, SOURCE_ROSTER_SHA256)
    ):
        raise HongKongAreasError("香港来源多边形独立校验尚未配置。")
    if (
        SOURCE_REVIEW_SHA256 != spec.independent_report_sha256
        or SOURCE_ROSTER_SHA256 != _roster_hash(spec)
    ):
        raise HongKongAreasError("香港来源多边形的独立来源审批或原始事实校验不符。")


def _validate_payload(
    value: AreaPayload,
    spec: hong_kong.HongKongSpec,
) -> dict[str, list[RegisteredArea]]:
    ids = sorted(row.whole.project_id for row in spec.records)
    expected_sites = {
        row.whole.project_id: row for row in spec.records if row.whole.source_features
    }
    if (
        value.source_spec_sha256 != hong_kong.SPEC_SHA256
        or value.source_review_sha256 != SOURCE_REVIEW_SHA256
        or value.source_roster_sha256 != SOURCE_ROSTER_SHA256
        or value.note != NOTE
        or value.processing != PROCESSING
        or value.site_ids != ids
        or set(value.sites) != set(expected_sites)
        or value.counts != _counts(spec)
    ):
        raise HongKongAreasError("香港多边形派生文件的版本、身份、来源或数量不符。")
    result = {}
    for site_id, record in expected_sites.items():
        bindings = sorted(record.whole.source_features, key=lambda row: row.source_row.object_id)
        rows = value.sites[site_id]
        if len(rows) != len(bindings):
            raise HongKongAreasError("香港整体的来源多边形要素数量不符。")
        areas = []
        for index, (row, binding) in enumerate(zip(rows, bindings, strict=True)):
            area = RegisteredArea.model_validate(row)
            raw_feature = {
                "attributes": binding.source_row.model_dump(mode="json", by_alias=True),
                "geometry": {"rings": row["rings"]},
            }
            if (
                area.id != f"{site_id}:OBJECTID:{binding.source_row.object_id}"
                or area.provider_object_id != binding.source_row.object_id
                or area.source_index != index
                or area.title != (binding.source_row.name or record.whole.title_en)
                or area.source != _spatial_source(binding)
                or len(area.rings) != binding.ring_count
                or sum(len(ring) for ring in area.rings) != binding.coordinate_records
                or hong_kong.feature_hash(raw_feature) != binding.feature_sha256
            ):
                raise HongKongAreasError("香港多边形的原环、顺序、来源或逐要素校验不符。")
            areas.append(area)
        result[site_id] = areas
    return result


def rebuild_hong_kong_areas(
    source_cache: Path,
    data_dir: Path = DATA_DIR,
) -> dict[str, int]:
    """Atomically publish an independently pinned sidecar from verified offline source pages."""
    try:
        directory = Path(data_dir)
        spec = hong_kong._spec(directory)
        _require_pins(spec)
        value = compile_hong_kong_areas(spec, source_cache, review_sha256=hong_kong.SPEC_SHA256)
        raw = _bytes(value)
        if _hash(raw) != AREA_SHA256:
            raise HongKongAreasError("香港来源多边形编译结果与独立SHA不符。")
        _validate_payload(AreaPayload.model_validate(value), spec)
        destination = directory / AREAS_FILE
        temporary = destination.with_name(destination.name + "." + uuid4().hex + ".tmp")
        try:
            temporary.write_bytes(raw)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return _counts(spec).model_dump()
    except HongKongAreasError:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        RecursionError,
        hong_kong.HongKongError,
    ) as error:
        raise HongKongAreasError(f"无法重建香港来源多边形：{error}") from error


def _known_site_ids(directory: Path) -> frozenset[str]:
    """Recover only independently pinned Site identities if the review file itself is damaged."""
    try:
        raw = _read_bounded(directory / hong_kong.SITES_FILE, MAX_SITES_BYTES)
        if _hash(raw) != hong_kong.SITES_SHA256:
            return frozenset()
        values = json.loads(raw)
        if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
            return frozenset()
        ids = [row.get("id") for row in values]
        if len(ids) != len(set(ids)) or any(
            not isinstance(value, str)
            or re.fullmatch(r"auth:hk-amo:monuments-[1-9]\d*", value) is None
            for value in ids
        ):
            return frozenset()
        return frozenset(ids)
    except (OSError, ValueError, TypeError, RecursionError):
        return frozenset()


def load_hong_kong_area_group(data_dir: Path = DATA_DIR) -> AreaSourceGroup | None:
    """Load only fixed local contracts and the compact sidecar; one failure stays in this source."""
    directory = Path(data_dir)
    if not (directory / hong_kong.MANIFEST_FILE).exists():
        return None
    site_ids = _known_site_ids(directory)
    try:
        spec = hong_kong._spec(directory)
        site_ids = frozenset(row.whole.project_id for row in spec.records)
        _require_pins(spec)
        raw = _read_bounded(directory / AREAS_FILE, MAX_SIDECAR_BYTES)
        if _hash(raw) != AREA_SHA256:
            raise HongKongAreasError("香港来源多边形派生文件与独立SHA不符。")
        value = AreaPayload.model_validate_json(raw)
        features = _validate_payload(value, spec)
        return AreaSourceGroup(AREAS_VERSION, POLYGON_LABEL, NOTE, site_ids, features)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        RecursionError,
        hong_kong.HongKongError,
        HongKongAreasError,
    ) as error:
        return AreaSourceGroup(
            AREAS_VERSION,
            POLYGON_LABEL,
            NOTE,
            site_ids,
            {},
            ready=False,
            reason=f"香港来源多边形不可用：{error} {PREPARE}",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", required=True)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--source-cache", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(rebuild_hong_kong_areas(args.source_cache, args.data_dir)))
    except HongKongAreasError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
