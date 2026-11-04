"""Pinned UNESCO source location records, separate from canonical site representatives."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from archsearch import catalogue_data as catalogue

DATA_DIR = Path(__file__).with_name("data")
SPATIAL_VERSION = "world-locations-v1"
BASE_CORPUS_VERSION = "global-v4"
LOCATIONS_FILENAME = "world_locations.json"
MANIFEST_FILENAME = "world_locations_manifest.json"
GEOGRAPHY_SHA256 = "dda2e717e20259ca1ea4dc0450de6a455e521ea2d5c00ac516ea2bedef20bad2"
IDENTITY_SHA256 = "9d4441a03ed66c10049d84e0f2a6f4ee5e4100ce4221218d613d6b94daca046a"
# These independent pins prevent a changed sidecar from signing its own new manifest.
LOCATIONS_SHA256 = "7acf15d3e1a2a008aed0f768a7c7d8189809a405e2657789ce5b6046d1239414"
EXPECTED_COUNTS = {
    "source_records": 1273,
    "eligible_sites": 1033,
    "located_sites": 1031,
    "empty_sites": 2,
    "source_points": 5632,
    "distinct_coordinates": 5327,
    "duplicate_coordinate_occurrences": 305,
    "sites_with_duplicate_coordinates": 11,
    "within_site_duplicate_ref_occurrences": 3,
    "empty_names": 2,
    "outside_web_mercator": 0,
    "zero_coordinates": 0,
}
PROCESSING = {
    "coordinates": (
        "Keep all source geometry positions in original order, including repeated coordinates; "
        "WGS84 [longitude, latitude], without averaging, clipping or deduplication."
    ),
    "labels": (
        "Source components_list name/ref are copied verbatim only after each coordinate and "
        "its order match the geometry. Labels and refs do not establish independently verified "
        "archaeological sites. A ref is not necessarily unique."
    ),
    "identity": (
        "Canonical site ID + zero-based source_index; no identity derived from coordinates."
    ),
    "scope": (
        "Source location records only; not excavation coordinates, property boundaries, "
        "historical political attribution, or new independent site records."
    ),
    "representatives": (
        "Original canonical representatives, texts and chronology remain unchanged. "
        "No Wikidata fallback is inserted into an empty DataHub location sequence."
    ),
}
PREPARATION_HINT = (
    "Run python -m archsearch.spatial_data --rebuild "
    "(add --download only to fetch the pinned source cache)."
)
Point = tuple[float, float]


class SpatialDataError(RuntimeError):
    """A source location sidecar or its pinned source contract is unavailable or invalid."""


@dataclass(frozen=True)
class SourceLocation:
    source_index: int
    coordinate: Point
    name: str
    ref: str


@dataclass(frozen=True)
class SourceGroup:
    version: str
    source: Mapping[str, str]
    site_ids: tuple[str, ...]


@dataclass(frozen=True)
class WorldLocations:
    version: str
    points: Mapping[str, tuple[Point, ...]]
    records: Mapping[str, tuple[SourceLocation, ...]]
    source: Mapping[str, str]
    counts: Mapping[str, int]
    source_groups: tuple[SourceGroup, ...] = ()


def merge_world_locations(primary: WorldLocations, additional: WorldLocations) -> WorldLocations:
    """Combine distinct reviewed identities without relabelling or replacing either source."""
    if set(primary.points) & set(additional.points):
        raise SpatialDataError("source location datasets cannot overwrite the same site identity")
    groups: list[SourceGroup] = []
    points: dict[str, tuple[Point, ...]] = {}
    records: dict[str, tuple[SourceLocation, ...]] = {}
    dataset_ids: set[str] = set()
    for locations in (primary, additional):
        if set(locations.records) != set(locations.points):
            raise SpatialDataError("source location identity and record sequences differ")
        current_groups = locations.source_groups or (SourceGroup(
            version=locations.version, source=locations.source,
            site_ids=tuple(sorted(locations.points)),
        ),)
        grouped: set[str] = set()
        for group in current_groups:
            dataset_id = group.source.get("dataset_id")
            if not dataset_id or dataset_id in dataset_ids:
                raise SpatialDataError("source dataset identity is missing or duplicated")
            if (not group.version or len(group.site_ids) != len(set(group.site_ids))
                    or grouped.intersection(group.site_ids)):
                raise SpatialDataError("source groups duplicate a site identity or lack a version")
            dataset_ids.add(dataset_id)
            grouped.update(group.site_ids)
            groups.append(SourceGroup(group.version, MappingProxyType(dict(group.source)),
                                      tuple(group.site_ids)))
        if grouped != set(locations.points):
            raise SpatialDataError("source groups do not cover their exact location identities")
        for site_id, positions in locations.points.items():
            entries = locations.records[site_id]
            if len(positions) != len(entries):
                raise SpatialDataError("source point and label counts differ")
            for index, (position, entry) in enumerate(zip(positions, entries, strict=True)):
                lon, lat = position
                if (isinstance(lon, bool) or isinstance(lat, bool)
                        or not math.isfinite(lon) or not math.isfinite(lat)
                        or not -180 <= lon <= 180 or not -90 <= lat <= 90
                        or entry.source_index != index or entry.coordinate != position):
                    raise SpatialDataError("source location order or coordinates differ")
            points[site_id] = tuple(positions)
            records[site_id] = tuple(entries)
    combined_version = "+".join(group.version for group in groups)
    if len(combined_version) > 128:
        raise SpatialDataError("combined source location version exceeds the supported length")
    return WorldLocations(
        version=combined_version, points=MappingProxyType(points),
        records=MappingProxyType(records),
        source=primary.source,
        counts=MappingProxyType({"source_points": sum(map(len, points.values()))}),
        source_groups=tuple(groups),
    )


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source() -> dict[str, str]:
    return {
        "dataset_id": catalogue.DATASET_ID,
        "uri": catalogue.SOURCE_URI,
        "api_uri": catalogue.RECORDS_URI,
        "metadata_uri": catalogue.METADATA_URI,
        "modified": catalogue.SOURCE_MODIFIED,
        "records_sha256": catalogue.RECORDS_SHA256,
        "metadata_sha256": catalogue.METADATA_SHA256,
        "license": catalogue.LICENSE,
        "license_uri": catalogue.LICENSE_URI,
        "attribution": "UNESCO",
        "accessed": "2026-11-04",
    }


def _identity(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[1-9]\d*", value) is None:
        raise SpatialDataError("source authority ID must be a positive decimal string")
    return value


def _points(geometry_type: Any, values: Any) -> list[Point]:
    if geometry_type is None:
        if values != []:
            raise SpatialDataError("missing source geometry must have an empty location sequence")
        return []
    if geometry_type not in {"Point", "MultiPoint"}:
        raise SpatialDataError("source geometry type differs from Point/MultiPoint")
    if not isinstance(values, list):
        raise SpatialDataError("source location coordinates must be an array")
    if geometry_type == "Point" and len(values) != 1:
        raise SpatialDataError("Point geometry requires exactly one location")
    coordinates = values[0] if geometry_type == "Point" else values
    try:
        return catalogue.source_points(
            {"coordinates": {"type": "Feature", "geometry": {
                "type": geometry_type, "coordinates": coordinates,
            }}}
        )
    except catalogue.CatalogueError as error:
        raise SpatialDataError(str(error)) from error


def normalize_locations(
    rows: list[dict[str, Any]], authority_to_site: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Preserve source sequence and labels after proving the geometry/component alignment."""
    result: dict[str, dict[str, Any]] = {}
    all_ids: set[str] = set()
    for row in rows:
        authority_id = _identity(row.get("id_no"))
        if authority_id in all_ids:
            raise SpatialDataError("source authority IDs are duplicated")
        all_ids.add(authority_id)
        category = row.get("category")
        if category not in {"Cultural", "Mixed", "Natural"}:
            raise SpatialDataError("unknown source category")
        if category == "Natural":
            continue
        if authority_id not in authority_to_site:
            raise SpatialDataError("source authority has no canonical site identity")
        site_id = authority_to_site[authority_id]
        if site_id in result:
            raise SpatialDataError("canonical site identity is duplicated")
        feature = row.get("coordinates")
        try:
            points = catalogue.source_points(row)
        except catalogue.CatalogueError as error:
            raise SpatialDataError(str(error)) from error
        geometry_type = feature["geometry"]["type"] if feature is not None else None
        components_value = row.get("components_list")
        if not isinstance(components_value, str):
            raise SpatialDataError("source components_list must be a JSON-encoded array")
        try:
            components = json.loads(components_value)
        except (ValueError, TypeError) as error:
            raise SpatialDataError("source components_list is not valid JSON") from error
        count = row.get("components_count")
        if (
            not isinstance(components, list) or isinstance(count, bool)
            or not isinstance(count, int) or count != len(points) or len(components) != len(points)
        ):
            raise SpatialDataError("source geometry and component counts differ")
        records = []
        for index, (point, component) in enumerate(zip(points, components, strict=True)):
            if (
                not isinstance(component, dict)
                or set(component) != {"name", "ref", "longitude", "latitude"}
                or not isinstance(component["name"], str)
                or not isinstance(component["ref"], str)
            ):
                raise SpatialDataError("source component label schema differs")
            component_point = _points("Point", [[component["longitude"], component["latitude"]]])[0]
            if component_point != point:
                raise SpatialDataError("source component and geometry coordinate order differs")
            records.append({
                "source_index": index, "coordinate": list(point),
                "name": component["name"], "ref": component["ref"],
            })
        result[site_id] = {
            "authority_id": authority_id, "geometry_type": geometry_type, "points": records,
        }
    if {value["authority_id"] for value in result.values()} != set(authority_to_site):
        raise SpatialDataError("source cultural/mixed authority coverage is incomplete")
    return result


def _parse_locations(value: Any) -> tuple[dict[str, tuple[SourceLocation, ...]], dict[str, str]]:
    if not isinstance(value, dict):
        raise SpatialDataError("source locations must be keyed by canonical site ID")
    parsed: dict[str, tuple[SourceLocation, ...]] = {}
    identities: dict[str, str] = {}
    for site_id, row in value.items():
        if (
            not isinstance(site_id, str)
            or re.fullmatch(r"(?:whc:[1-9]\d*|wd:Q[1-9]\d*)", site_id) is None
            or not isinstance(row, dict)
            or set(row) != {"authority_id", "geometry_type", "points"}
            or not isinstance(row["points"], list)
        ):
            raise SpatialDataError("source location site schema differs")
        identities[site_id] = _identity(row["authority_id"])
        entries = []
        coordinates = []
        for index, record in enumerate(row["points"]):
            if (
                not isinstance(record, dict)
                or set(record) != {"source_index", "coordinate", "name", "ref"}
                or type(record["source_index"]) is not int
                or record["source_index"] != index
                or not isinstance(record["name"], str)
                or not isinstance(record["ref"], str)
            ):
                raise SpatialDataError("source location record sequence or metadata differs")
            coordinates.append(record["coordinate"])
            entries.append(record)
        points = _points(row["geometry_type"], coordinates)
        parsed[site_id] = tuple(
            SourceLocation(index, point, record["name"], record["ref"])
            for index, (point, record) in enumerate(zip(points, entries, strict=True))
        )
    if len(set(identities.values())) != len(identities):
        raise SpatialDataError("source authority identity is duplicated")
    return parsed, identities


def _counts(records: Mapping[str, tuple[SourceLocation, ...]]) -> dict[str, int]:
    coordinates = [record.coordinate for values in records.values() for record in values]
    return {
        "source_records": catalogue.EXPECTED_COUNTS["source"],
        "eligible_sites": len(records),
        "located_sites": sum(bool(values) for values in records.values()),
        "empty_sites": sum(not values for values in records.values()),
        "source_points": len(coordinates),
        "distinct_coordinates": len(set(coordinates)),
        "duplicate_coordinate_occurrences": len(coordinates) - len(set(coordinates)),
        "sites_with_duplicate_coordinates": sum(
            len(values) != len({record.coordinate for record in values})
            for values in records.values()
        ),
        "within_site_duplicate_ref_occurrences": sum(
            len(values) - len({record.ref for record in values}) for values in records.values()
        ),
        "empty_names": sum(not record.name for values in records.values() for record in values),
        "outside_web_mercator": sum(abs(point[1]) > 85.0511287798 for point in coordinates),
        "zero_coordinates": sum(point == (0, 0) for point in coordinates),
    }


def _manifest(
    records: Mapping[str, tuple[SourceLocation, ...]], identities: dict[str, str], payload: bytes,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "version": SPATIAL_VERSION,
        "base_corpus_version": BASE_CORPUS_VERSION,
        "source": _source(),
        "counts": _counts(records),
        "identity_bridge": {
            "file": "world_geography.json", "sha256": GEOGRAPHY_SHA256,
            "mapping_sha256": _sha256(_json_bytes(identities)),
        },
        "partition": {
            "authority_ids": sorted(identities.values(), key=int),
            "without_source_location_ids": sorted(
                key for key, values in records.items() if not values
            ),
        },
        "processing": PROCESSING,
        "files": {LOCATIONS_FILENAME: {"sha256": _sha256(payload)}},
    }


def _pinned_json(path: Path, expected: str) -> Any:
    payload = path.read_bytes()
    if _sha256(payload) != expected:
        raise SpatialDataError(f"pinned spatial source checksum differs: {path.name}")
    return json.loads(payload)


def rebuild_world_locations(cache_dir: Path, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Build the two deterministic sidecars from the already downloaded pinned source only."""
    try:
        rows = _pinned_json(Path(cache_dir) / "records.json", catalogue.RECORDS_SHA256)
        metadata = _pinned_json(Path(cache_dir) / "metadata.json", catalogue.METADATA_SHA256)
        defaults = metadata["metas"]["default"]
        if (
            metadata["dataset_id"] != catalogue.DATASET_ID
            or defaults["license"] != catalogue.LICENSE
            or defaults["license_url"] != catalogue.LICENSE_URI
            or defaults["modified"] != catalogue.SOURCE_MODIFIED
            or defaults["records_count"] != catalogue.EXPECTED_COUNTS["source"]
            or not isinstance(rows, list) or len(rows) != catalogue.EXPECTED_COUNTS["source"]
        ):
            raise SpatialDataError("source dataset license, version or record count differs")
        geography = _pinned_json(Path(data_dir) / "world_geography.json", GEOGRAPHY_SHA256)
        identities = {key: row["authority_id"] for key, row in geography.items()}
        if _sha256(_json_bytes(identities)) != IDENTITY_SHA256:
            raise SpatialDataError("canonical authority identity bridge differs")
        inverse = {authority: key for key, authority in identities.items()}
        normalized = normalize_locations(rows, inverse)
        records, actual_identities = _parse_locations(normalized)
        if any(
            geography[key]["point_count"] != max(1, len(values))
            for key, values in records.items()
        ):
            raise SpatialDataError("source locations differ from the existing point-count contract")
        payload = _json_bytes(normalized)
        manifest = _manifest(records, actual_identities, payload)
        if manifest["counts"] != EXPECTED_COUNTS:
            raise SpatialDataError("source location counts differ from the pinned contract")
        if _sha256(payload) != LOCATIONS_SHA256:
            raise SpatialDataError(
                "derived source location payload differs from its independent pin"
            )
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        (Path(data_dir) / LOCATIONS_FILENAME).write_bytes(payload)
        (Path(data_dir) / MANIFEST_FILENAME).write_bytes(_json_bytes(manifest))
        return manifest
    except SpatialDataError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise SpatialDataError(
            f"cannot rebuild source locations: {error}. {PREPARATION_HINT}"
        ) from error


def load_world_locations(data_dir: Path = DATA_DIR) -> WorldLocations:
    """Validate only the local sidecars and return immutable coordinates and source labels."""
    try:
        directory = Path(data_dir)
        payload = (directory / LOCATIONS_FILENAME).read_bytes()
        if _sha256(payload) != LOCATIONS_SHA256:
            raise SpatialDataError("source location checksum differs from the independent pin")
        records, identities = _parse_locations(json.loads(payload))
        if _sha256(_json_bytes(identities)) != IDENTITY_SHA256:
            raise SpatialDataError("source location canonical identity bridge differs")
        if _counts(records) != EXPECTED_COUNTS:
            raise SpatialDataError("source location counts differ from the pinned contract")
        actual = json.loads((directory / MANIFEST_FILENAME).read_bytes())
        expected = _manifest(records, identities, payload)
        if _json_bytes(actual) != _json_bytes(expected):
            raise SpatialDataError("source location schema, source or processing contract differs")
        return WorldLocations(
            version=SPATIAL_VERSION,
            points=MappingProxyType({
                key: tuple(record.coordinate for record in values)
                for key, values in records.items()
            }),
            records=MappingProxyType(records), source=MappingProxyType(_source()),
            counts=MappingProxyType(dict(EXPECTED_COUNTS)),
        )
    except (OSError, ValueError, KeyError, TypeError, SpatialDataError) as error:
        raise SpatialDataError(
            f"source locations unavailable: {error}. {PREPARATION_HINT}"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument(
        "--source-cache", type=Path, default=Path(".archsearch/downloads/unesco-datahub-v1"),
    )
    args = parser.parse_args()
    if args.download:
        catalogue.download_sources(args.source_cache)
    if args.rebuild:
        counts = rebuild_world_locations(args.source_cache, args.data_dir)["counts"]
    else:
        counts = dict(load_world_locations(args.data_dir).counts)
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
