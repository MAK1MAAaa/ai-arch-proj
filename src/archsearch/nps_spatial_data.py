"""Expose approved NPS provider points without converting registered areas to centres."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from archsearch import nps_data
from archsearch.spatial_data import SourceLocation, SpatialDataError, WorldLocations
from archsearch.supplement_data import SourceArtifact

DATA_DIR = Path(__file__).with_name("data")
LOCATIONS_FILE = "nps_pacific_locations.json"
LOCATIONS_VERSION = "nps-pacific-locations-v1"
LOCATIONS_SHA256 = "1ae88886c8671ed2dbfcbb09e47c64cedfb729126f68c9078d8101a4d4c9e933"
SERVICE_PATH = "/arcgis/rest/services/cultural_resources/nrhp_locations/MapServer/0/query"


class NpsSpatialError(SpatialDataError):
    """The approved point sequence or its derived sidecar differs from the frozen facts."""


class _ProviderPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_index: StrictInt = Field(ge=0)
    coordinate: tuple[float, float]
    name: str = Field(min_length=1)
    ref: str
    provider_layer: StrictInt = Field(ge=0, le=0)
    provider_source_index: StrictInt = Field(ge=0)
    provider_object_id: StrictInt = Field(gt=0)
    provider_feature_id: str
    resource_id: str = Field(min_length=1)
    geometry_id: str = Field(min_length=1)
    geometry_type: Literal["esriGeometryPoint"]
    source_uri: str
    source_file: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    spatial_reference: dict[str, StrictInt]
    file_feature_index: StrictInt = Field(ge=0)
    provider_attributes: dict[str, Any]

    @field_validator("coordinate", mode="before")
    @classmethod
    def validate_coordinate(cls, value: Any) -> Any:
        if (not isinstance(value, (list, tuple)) or len(value) != 2
                or any(isinstance(item, bool) or not isinstance(item, (int, float))
                       or not math.isfinite(item) for item in value)
                or not -180 <= value[0] <= 180 or not -90 <= value[1] <= 90):
            raise ValueError("NPS source point requires finite longitude/latitude values")
        return value


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source() -> dict[str, str]:
    return {
        "dataset_id": "nps-pacific-reviewed-points",
        "name": "NPS Pacific reviewed location contract (derived)",
        "uri": "https://github.com/MAK1MAAaa/ai-arch-proj/blob/main/"
               "src/archsearch/data/nps_pacific_review.json",
        "version": nps_data.COHORT_VERSION,
        "license": "NPS government structured metadata; other source rights retained",
        "license_uri": "https://www.nps.gov/aboutus/disclaimer.htm",
        "sha256": nps_data.SPEC_SHA256,
    }


def _point(record: nps_data.NpsRecord, value: Any, index: int,
           originals: dict[str, dict[str, Any]]) -> _ProviderPoint:
    point = _ProviderPoint.model_validate(value)
    reference = record.site.id.removeprefix("auth:nps-nris:")
    source = SourceArtifact(filename=point.source_file, sha256=point.source_sha256,
                            uri=point.source_uri)
    uri = urlsplit(point.source_uri)
    query = parse_qs(uri.query)
    attributes = point.provider_attributes
    original = originals.get(point.provider_feature_id)
    state = attributes.get("State")
    country = nps_data.STATE_COUNTRIES.get(state, "") if isinstance(state, str) else ""
    if (
        record.location_disclosure != "public" or point.source_index != index
        or point.ref != reference or original is None
        or point.provider_source_index != original.get("source_index")
        or point.file_feature_index != index
        or point.provider_feature_id != f"0:{point.provider_object_id}"
        or source not in record.source_files
        or uri.scheme != "https" or uri.netloc != "mapservices.nps.gov"
        or uri.path != SERVICE_PATH or query.get("where") != [f"NRIS_Refnum='{reference}'"]
        or query.get("outSR") != ["4326"] or query.get("returnGeometry") != ["true"]
        or query.get("orderByFields") != ["OBJECTID ASC"]
        or point.spatial_reference.get("wkid") != 4326
        or any(value != 4326 for value in point.spatial_reference.values())
        or attributes.get("NRIS_Refnum") != reference
        or attributes.get("PROPERTY_ID") != reference
        or type(attributes.get("OBJECTID")) is not int
        or attributes.get("OBJECTID") != point.provider_object_id
        or attributes.get("GEOM_ID") != point.geometry_id
        or attributes.get("CR_ID") != point.resource_id
        or attributes.get("RESNAME") != point.name
        or attributes.get("STATUS") != "Listed"
        or country not in (record.site.geography.countries if record.site.geography else [])
    ):
        raise NpsSpatialError("NPS point identity, origin, disclosure or original sequence differs")
    if any(attributes[key] != item for key, item in original.items() if key in attributes):
        raise NpsSpatialError("NPS geometry attributes differ from the original metadata snapshot")
    return point


def _originals(record: nps_data.NpsRecord, decision: nps_data.NpsDecision,
               ) -> dict[str, dict[str, Any]]:
    values = record.provenance.get("source_records")
    if not isinstance(values, list):
        raise NpsSpatialError("NPS records require the frozen original attribute sequence")
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        if (not isinstance(value, dict) or type(value.get("source_layer")) is not int
                or value["source_layer"] not in {0, 1}
                or type(value.get("OBJECTID")) is not int or value["OBJECTID"] <= 0
                or type(value.get("source_index")) is not int or value["source_index"] < 0):
            raise NpsSpatialError("NPS original layer, feature and index must remain explicit")
        key = f"{value['source_layer']}:{value['OBJECTID']}"
        if key in result:
            raise NpsSpatialError("NPS original metadata duplicates a feature identity")
        result[key] = value
    if set(result) != set(decision.source_feature_ids):
        raise NpsSpatialError("NPS original metadata does not cover the full decision feature set")
    return result


def location_payload(spec: nps_data.NpsSpec) -> dict[str, Any]:
    """Derive display records from reviewed points, keeping provider order and both wells."""
    decisions = {row.target_id: row for row in spec.decisions if row.disposition == "include"}
    rows: list[dict[str, Any]] = []
    for record in sorted(spec.records, key=lambda item: item.site.id):
        values = record.provenance.get("source_locations")
        if not isinstance(values, list):
            raise NpsSpatialError("NPS reviewed records require an explicit source point sequence")
        originals = _originals(record, decisions[record.site.id])
        points = [_point(record, value, index, originals)
                  for index, value in enumerate(values)]
        expected = {key for key in originals if key.startswith("0:")}
        if record.location_disclosure != "public":
            expected = set()
        if {point.provider_feature_id for point in points} != expected:
            raise NpsSpatialError("NPS point sequence does not cover all approved source features")
        if (not points) != (record.site.repr_point is None):
            raise NpsSpatialError("NPS point availability differs from the reviewed representative")
        if not points:
            continue
        if record.site.repr_point != points[0].coordinate:
            raise NpsSpatialError("NPS initial representative must retain the fixed first source")
        keys = [(point.provider_layer, point.provider_object_id) for point in points]
        if len(set(keys)) != len(keys) or keys != sorted(keys):
            raise NpsSpatialError("NPS provider points changed order or duplicated a feature")
        if len({(point.source_file, point.source_uri, point.source_sha256)
                for point in points}) != 1:
            raise NpsSpatialError("NPS point sequence must preserve its single-ref source file")
        rows.append({
            "id": record.site.id,
            "records": [{
                "source_index": point.source_index, "coordinate": list(point.coordinate),
                "name": point.name,
                "ref": (f"NRIS:{point.ref}; layer:{point.provider_layer}; "
                        f"OBJECTID:{point.provider_object_id}; GEOM_ID:{point.geometry_id}; "
                        f"provider_source_index:{point.provider_source_index}"),
            } for point in points],
        })
    return {
        "schema_version": 1, "version": LOCATIONS_VERSION,
        "review_sha256": nps_data.SPEC_SHA256, "source": _source(), "sites": rows,
        "processing": (
            "Reviewed new records only. Keep provider points and zero-based original order; "
            "refs compose the original NRIS/layer/OBJECTID/GEOM_ID/provider index. "
            "The source SHA identifies the derived reviewed contract, not one raw export. "
            "No polygon centre, precise excavation fix, current survival or political inference."
        ),
    }


def rebuild_nps_locations(data_dir: Path = DATA_DIR) -> dict[str, int]:
    """Compile the bundled reviewed location contract without network access."""
    try:
        directory = Path(data_dir)
        payload = _bytes(location_payload(nps_data._spec(directory)))
        if _hash(payload) != LOCATIONS_SHA256:
            raise NpsSpatialError("NPS location sidecar differs from its independent pin")
        (directory / LOCATIONS_FILE).write_bytes(payload)
        value = json.loads(payload)
        return {"records": len(value["sites"]),
                "points": sum(len(row["records"]) for row in value["sites"])}
    except (OSError, ValueError, KeyError, TypeError, nps_data.NpsError) as error:
        raise NpsSpatialError(f"cannot rebuild NPS source points: {error}") from error


def load_nps_locations(data_dir: Path = DATA_DIR) -> WorldLocations:
    """Load the exact derived point snapshot; core search needs no spatial sidecar."""
    try:
        directory = Path(data_dir)
        expected = _bytes(location_payload(nps_data._spec(directory)))
        if _hash(expected) != LOCATIONS_SHA256:
            raise NpsSpatialError("NPS source points differ from the independent pin")
        value = json.loads(expected)
        payload = (directory / LOCATIONS_FILE).read_bytes() if value["sites"] else expected
        if payload != expected:
            raise NpsSpatialError("NPS source points differ from the reviewed contract")
        records = {row["id"]: tuple(SourceLocation(
            item["source_index"], tuple(item["coordinate"]), item["name"], item["ref"],
        ) for item in row["records"]) for row in value["sites"]}
        return WorldLocations(
            version=LOCATIONS_VERSION, records=MappingProxyType(records),
            points=MappingProxyType({key: tuple(item.coordinate for item in entries)
                                     for key, entries in records.items()}),
            source=MappingProxyType(value["source"]),
            counts=MappingProxyType({"source_points": sum(map(len, records.values()))}),
        )
    except (OSError, ValueError, KeyError, TypeError, nps_data.NpsError) as error:
        raise NpsSpatialError(f"cannot load NPS source points: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild approved NPS provider points offline")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--rebuild", action="store_true", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(rebuild_nps_locations(args.data_dir)))
    except NpsSpatialError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
