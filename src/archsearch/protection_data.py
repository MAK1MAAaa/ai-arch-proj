"""Compile independently reviewed Hague cultural properties and source locations offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from archsearch.domain import Site
from archsearch.spatial_data import SourceLocation, WorldLocations
from archsearch.supplement_data import SourceArtifact, SupplementRecord, base_contract

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "protection-supplement-v1"
LOCATIONS_VERSION = "protection-locations-v1"
CORPUS_VERSION = "global-v8"
BASE_COUNT = 1700
SOURCE_COUNT = 175
SOURCE_SHA256 = "a2322c5882a894c900fac40472a30ca71f52f5b024246c3a76dfdb8d1aba9771"
METADATA_SHA256 = "7bf3383804b3906095846c735536c502017e09dd4d4506b9afd979dcf9e72f41"
SOURCE_IDENTITIES_SHA256 = "674ae7d84c34fee1ccd3aee5f87a5fc38f863615bcf90c598dd12d2304c90f7f"
SOURCE_MODIFIED = "2026-10-31T03:13:18+00:00"
SPEC_FILE = "protection_review.json"
SITES_FILE = "protection_sites.json"
LOCATIONS_FILE = "protection_locations.json"
MANIFEST_FILE = "protection_manifest.json"
SPEC_SHA256 = "d758e31a6c6ccda66cdc9d7a5181835f5a2bb44ea403f0aeb5f573dfd162d511"
SITES_SHA256 = "b1e3e6e86189609f352c75ad3fd34d9084010411f8a83c78ddb504a9ead05e98"
LOCATIONS_SHA256 = "68d63415fd12fe8b16af66aec683c18f5082af7483b384282594a02c0d1186fa"
EXPECTED_REVIEW_REPORTS = {
    "identity": "5b6ecf576a67db544caae12e015987bdfb003cbb0180dd6ca20ea3679a9447be",
    "scope": "5bc41c05e6a81ea88b9a86c5a74d156b3e65e2a516dbf58af6024406900d8f18",
    "payload": "4c71a53b33b093f7031189b5fe7fb2e2972d37b8beb0b456a5e0626e6acdcc1d",
}
_UUID = r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$"
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class ProtectionError(RuntimeError):
    """Source, review, derivative or unchanged-base evidence is inconsistent."""


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def component_coordinate(text: str) -> tuple[float, float]:
    """The source component string is latitude,longitude, unlike the main point object."""
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 2 or any(_DECIMAL.fullmatch(part) is None for part in parts):
        raise ValueError("component requires two decimal latitude,longitude values")
    latitude, longitude = map(float, parts)
    if not (math.isfinite(longitude) and math.isfinite(latitude)
            and -180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError("component lies outside finite WGS84 bounds")
    return longitude, latitude


class LocationReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_index: int = Field(ge=0, strict=True)
    component_id: int | None = Field(strict=True)
    name_en: str
    name_fr: str
    original_coordinate: str | None
    coordinate: tuple[float, float] | None
    map_eligible: bool = Field(strict=True)
    reason: str = Field(min_length=1)

    @field_validator("coordinate", mode="before")
    @classmethod
    def reject_coordinate_coercion(cls, value: Any) -> Any:
        if value is not None and (
            not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(item) not in {int, float} for item in value)
        ):
            raise ValueError("source coordinates require two numeric values without coercion")
        return value

    @model_validator(mode="after")
    def validate_source_coordinate(self) -> LocationReview:
        if self.original_coordinate is not None:
            if self.coordinate != component_coordinate(self.original_coordinate):
                raise ValueError("component must preserve source latitude,longitude conversion")
        if self.map_eligible and self.coordinate is None:
            raise ValueError("an eligible location must have a verified public point")
        if self.coordinate is not None:
            lon, lat = self.coordinate
            if not (math.isfinite(lon) and math.isfinite(lat)
                    and -180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError("location requires a finite WGS84 point")
        return self


class ProtectionRecord(SupplementRecord):
    source_id: int = Field(gt=0, strict=True)
    source_uuid: str = Field(pattern=_UUID)
    locations: list[LocationReview] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scope(self) -> ProtectionRecord:
        site = self.site
        if (
            site.id != f"auth:unesco-chp:{self.source_id}"
            or site.location_precision is not None or self.coordinate.method != "authority"
            or site.geography is None or site.geography.authority_id != "supplement:" + site.id
            or site.geography.point_count != int(site.repr_point is not None)
        ):
            raise ValueError("protected property must preserve its authority identity and point")
        if any(value is not None for value in (
            self.coordinate.statement_id, self.coordinate.globe, self.coordinate.precision,
            self.coordinate.rank,
        )):
            raise ValueError("authority source does not supply Wikidata rank or measured precision")
        if [item.source_index for item in self.locations] != list(range(len(self.locations))):
            raise ValueError("reviewed source location order must remain complete")
        if not any(item.map_eligible for item in self.locations):
            raise ValueError("admitted properties require at least one approved public location")
        original = self.provenance.get("source_record")
        if not isinstance(original, dict):
            raise ValueError("property must retain the reviewed original source record")
        point = original.get("coordinates")
        if not isinstance(point, dict):
            raise ValueError("admitted property requires a public source representative")
        raw_point = (point.get("lon"), point.get("lat"))
        if any(type(value) not in {int, float} for value in raw_point):
            raise ValueError("source main coordinates require numeric longitude/latitude values")
        if (
            type(original.get("site_id")) is not int
            or original.get("site_id") != self.source_id
            or original.get("uuid") != self.source_uuid
            or site.title != original.get("title_en")
            or site.repr_point != raw_point
            or site.geography.countries != [original.get("iso2")]
            or site.description or site.description_zh
        ):
            raise ValueError("identity, point and missing descriptions must retain source values")
        french = original.get("title_fr")
        expected_names = [french] if isinstance(french, str) and french != site.title else []
        if site.names != expected_names:
            raise ValueError("property aliases must retain only the original distinct French title")
        components = original.get("components")
        if not isinstance(components, list) or original.get("component_count") != len(components):
            raise ValueError("source component array and reported count differ")
        if not components:
            location = self.locations[0]
            if (len(self.locations) != 1 or location.component_id is not None
                    or location.original_coordinate is not None
                    or location.coordinate != raw_point
                    or location.name_en != site.title or location.name_fr != french):
                raise ValueError("single source location must preserve the original main point")
        elif len(components) != len(self.locations):
            raise ValueError("review must retain all source components, including excluded storage")
        else:
            for component, location in zip(components, self.locations, strict=True):
                if not isinstance(component, dict) or (
                    type(component.get("component_id")) is not int
                    or component.get("component_id") != location.component_id
                    or component.get("name_en") != location.name_en
                    or component.get("name_fr") != location.name_fr
                    or component.get("coordinates") != location.original_coordinate
                ):
                    raise ValueError("component labels and original coordinates differ from source")
                if self.source_id == 626 and location.component_id == 627 and location.map_eligible:
                    raise ValueError("Arqa warehouse cannot be mapped as an archaeological site")
        return self


class SourceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: int = Field(gt=0, strict=True)
    source_uuid: str = Field(pattern=_UUID)
    title: str = Field(min_length=1)
    disposition: Literal["include", "existing", "component", "hold"]
    target_id: str | None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_target(self) -> SourceDecision:
        if (self.disposition == "hold") != (self.target_id is None):
            raise ValueError("reviewed identity decisions require an explicit target or hold")
        return self


class ProtectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cohort_version: Literal["protection-supplement-v1"]
    corpus_version: Literal["global-v8"]
    base_count: Literal[1700]
    base_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: Literal["a2322c5882a894c900fac40472a30ca71f52f5b024246c3a76dfdb8d1aba9771"]
    metadata_sha256: Literal["7bf3383804b3906095846c735536c502017e09dd4d4506b9afd979dcf9e72f41"]
    source_modified: Literal["2026-10-31T03:13:18+00:00"]
    review_reports: dict[str, str]
    selection: str = Field(min_length=1)
    decisions: list[SourceDecision] = Field(min_length=175, max_length=175)
    records: list[ProtectionRecord] = Field(min_length=1)


def _spec(directory: Path) -> ProtectionSpec:
    try:
        return _read_spec(directory)
    except ProtectionError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ProtectionError(f"cannot read protection review: {error}") from error


def _read_spec(directory: Path) -> ProtectionSpec:
    payload = (directory / SPEC_FILE).read_bytes()
    if _hash(payload) != SPEC_SHA256:
        raise ProtectionError("protection review differs from its independent pin")
    spec = ProtectionSpec.model_validate_json(payload)
    decisions = {item.source_id: item for item in spec.decisions}
    if (len(decisions) != SOURCE_COUNT
            or len({d.source_uuid for d in spec.decisions}) != SOURCE_COUNT):
        raise ProtectionError("full source audit duplicates or omits authority identities")
    identities = sorted((row.source_id, row.source_uuid, row.title) for row in spec.decisions)
    if _hash(_bytes(identities)) != SOURCE_IDENTITIES_SHA256:
        raise ProtectionError("source audit identities differ from the complete frozen175 roster")
    records = {record.source_id: record for record in spec.records}
    included = {key: row for key, row in decisions.items() if row.disposition == "include"}
    if len(records) != len(spec.records) or set(records) != set(included):
        raise ProtectionError("admitted identities differ from the complete source audit")
    for source_id, record in records.items():
        decision = included[source_id]
        if (decision.target_id != record.site.id or decision.source_uuid != record.source_uuid
                or decision.title != record.site.title):
            raise ProtectionError("admitted identity differs from independent source review")
    if spec.review_reports != EXPECTED_REVIEW_REPORTS or any(
        re.fullmatch(r"[0-9a-f]{64}", value) is None for value in spec.review_reports.values()
    ):
        raise ProtectionError("independent review reports differ from their external pins")
    artifacts: dict[str, SourceArtifact] = {}
    for record in spec.records:
        for artifact in record.source_files:
            if artifact.filename in artifacts and artifacts[artifact.filename] != artifact:
                raise ProtectionError("conflicting source filename contracts")
            artifacts[artifact.filename] = artifact
    return spec


def _ordered(spec: ProtectionSpec) -> list[ProtectionRecord]:
    return sorted(spec.records, key=lambda record: (
        _hash((COHORT_VERSION + ":" + record.site.id).encode()), record.site.id,
    ))


def _locations(spec: ProtectionSpec) -> dict[str, Any]:
    return {
        "version": LOCATIONS_VERSION, "source_sha256": SOURCE_SHA256,
        "records": {record.site.id: [item.model_dump(mode="json") for item in record.locations]
                    for record in _ordered(spec)},
    }


def _manifest(spec: ProtectionSpec, sites: bytes, locations: bytes) -> dict[str, Any]:
    return {
        "schema_version": 1, "cohort_version": COHORT_VERSION, "corpus_version": CORPUS_VERSION,
        "base": {key: value for key, value in spec.model_dump().items() if key.startswith("base_")},
        "source": {"dataset_id": "chp001", "uri": "https://data.unesco.org/explore/dataset/chp001/",
                   "modified": SOURCE_MODIFIED, "records_sha256": SOURCE_SHA256,
                   "license": "CC BY-SA 4.0", "license_uri": "https://creativecommons.org/licenses/by-sa/4.0/"},
        "files": {SPEC_FILE: SPEC_SHA256, SITES_FILE: _hash(sites),
                  LOCATIONS_FILE: _hash(locations)},
        "review_reports": spec.review_reports,
        "counts": {"base": BASE_COUNT, "added": len(spec.records),
                   "total": BASE_COUNT + len(spec.records), "source_rows": SOURCE_COUNT,
                   "dispositions": {kind: sum(d.disposition == kind for d in spec.decisions)
                                    for kind in ("include", "existing", "component", "hold")},
                   "locations": sum(len(record.locations) for record in spec.records),
                   "map_eligible_locations": sum(item.map_eligible for record in spec.records
                                                 for item in record.locations)},
        "selection": spec.selection,
        "chronology": "Source identity review only. No protection year becomes a site phase.",
    }


def rebuild_protection(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Compile only independently reviewed facts, without downloading source documents."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        sites = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        locations = _bytes(_locations(spec))
        if _hash(sites) != SITES_SHA256 or _hash(locations) != LOCATIONS_SHA256:
            raise ProtectionError("derived protection data differs from its independent pins")
        manifest = _manifest(spec, sites, locations)
        for name, payload in ((SITES_FILE, sites), (LOCATIONS_FILE, locations),
                              (MANIFEST_FILE, _bytes(manifest))):
            (directory / name).write_bytes(payload)
        return manifest
    except ProtectionError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ProtectionError(f"cannot rebuild protection facts: {error}") from error


def load_protection(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Append the approved properties, preserving every earlier record and search document."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        if base_contract(base) != {"base_count": spec.base_count,
                                   "base_ids_sha256": spec.base_ids_sha256,
                                   "base_sites_sha256": spec.base_sites_sha256}:
            raise ProtectionError("protection base differs from the unchanged1700 contract")
        sites = (directory / SITES_FILE).read_bytes()
        expected = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        if sites != expected or _hash(sites) != SITES_SHA256:
            raise ProtectionError("protection sites differ from their reviewed source facts")
        locations = _bytes(_locations(spec))
        manifest = json.loads((directory / MANIFEST_FILE).read_bytes())
        if _bytes(manifest) != _bytes(_manifest(spec, sites, locations)):
            raise ProtectionError("protection manifest differs from its frozen contract")
        by_id = {site.id: site for site in base}
        additions = [record.site for record in _ordered(spec)]
        if set(by_id).intersection(site.id for site in additions):
            raise ProtectionError("protection supplement duplicates an existing identity")
        if any(d.target_id not in by_id for d in spec.decisions
               if d.disposition in {"existing", "component"}):
            raise ProtectionError("reviewed existing identity is absent from the unchanged base")
        countries = {code for site in base if site.geography for code in site.geography.countries}
        regions = {code for site in base if site.geography for code in site.geography.regions}
        if any(site.geography is None or not set(site.geography.countries) <= countries
               or not set(site.geography.regions) <= regions for site in additions):
            raise ProtectionError("source geography is outside the existing label registry")
        return base + additions
    except ProtectionError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ProtectionError(f"cannot load protection facts: {error}") from error


def load_protection_locations(data_dir: Path = DATA_DIR) -> WorldLocations:
    """Load reviewed cultural locations; preserve excluded storage/ambiguous rows in audit."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        payload = (directory / LOCATIONS_FILE).read_bytes()
        if _hash(payload) != LOCATIONS_SHA256 or payload != _bytes(_locations(spec)):
            raise ProtectionError("protection locations differ from their independent review")
        records = {}
        for record in _ordered(spec):
            kept = [item for item in record.locations if item.map_eligible]
            records[record.site.id] = tuple(SourceLocation(
                index, item.coordinate, item.name_en,
                f"chp001:{record.source_id}; source_index:{item.source_index}; "
                f"component_id:{item.component_id}",
            ) for index, item in enumerate(kept) if item.coordinate is not None)
        return WorldLocations(
            version=LOCATIONS_VERSION,
            points=MappingProxyType({key: tuple(item.coordinate for item in value)
                                     for key, value in records.items()}),
            records=MappingProxyType(records),
            source=MappingProxyType(_manifest(spec, b"", b"")["source"]),
            counts=MappingProxyType({"source_points": sum(map(len, records.values()))}),
        )
    except (OSError, ValueError, KeyError, TypeError, ProtectionError) as error:
        raise ProtectionError(f"cannot load protection source locations: {error}") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Check optional archived evidence bytes without executing source material."""
    spec = _spec(Path(data_dir))
    root = Path(cache_dir).resolve()
    artifacts: dict[str, SourceArtifact] = {}
    for record in spec.records:
        for artifact in record.source_files:
            if artifact.filename in artifacts and artifacts[artifact.filename] != artifact:
                raise ProtectionError("conflicting source filename contracts")
            artifacts[artifact.filename] = artifact
    try:
        for artifact in artifacts.values():
            path = (root / artifact.filename).resolve()
            if not path.is_relative_to(root) or _hash(path.read_bytes()) != artifact.sha256:
                raise ProtectionError(f"source snapshot differs: {artifact.filename}")
        return len(artifacts)
    except (OSError, ValueError, TypeError) as error:
        raise ProtectionError(f"cannot verify protection source snapshots: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild reviewed Hague cultural properties offline",
    )
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--verify-source-cache", type=Path)
    args = parser.parse_args()
    try:
        if args.verify_source_cache is not None:
            print(json.dumps({"verified_source_files": verify_source_cache(
                args.verify_source_cache, args.data_dir,
            )}))
        if args.rebuild:
            print(json.dumps(rebuild_protection(args.data_dir)["counts"]))
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild or --verify-source-cache")
    except ProtectionError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
