"""Compile independently reviewed NHL facts; never infer a point from a range."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from archsearch.domain import Site, SourceReference
from archsearch.supplement_data import SourceArtifact, SupplementRecord, base_contract

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "australia-nhl-v1"
CORPUS_VERSION = "global-v12"
BASE_COUNT = 1940
SPEC_FILE = "australia_review.json"
SITES_FILE = "australia_sites.json"
MANIFEST_FILE = "australia_manifest.json"
SELECTION = "Complete frozen NHL candidate roster; independently reviewed source decisions."
CANDIDATES_SHA256 = "0eb2ab872b5051a7ed8aada4643fa5871233c0f54750b5dd2f5e04517124078c"
HANDOFF_SHA256 = "23dbee635429fd6eb4233684563ac9dc61404fb4dc9a8ef9de203cbf82917ddf"
# Frozen source review and independently checked compiled artifacts.
INDEPENDENT_REVIEW_SHA256 = "b67bd41424df6df95c6dc4fe0a3ec352d1d376cc9ffd2d1877c339dd98477b70"
SOURCE_ROSTER_SHA256 = "7f2cc18ad0e90d4be164436cf8eebf36cbfe91a28f224782c48394488515d9d0"
SPEC_SHA256 = "ecc0205e858b3c7f12d2412f5e04aa2cbdadd5f7d63db644d2a7fd8ee271021b"
SITES_SHA256 = "3af625722fa43a8b9559b2ceb81df8835b0cfd1e4ea5213e5d36687d5f70baae"
UN_M49_SHA256 = "b9048114f6e7f2abda83bf03d4263c9d7cd1bd7230e3d0461025ee7839a7a1fb"
UN_M49_URI = "https://unstats.un.org/unsd/methodology/m49/overview"
COUNTRY_LABELS = MappingProxyType({"AU": "Australia", "NF": "Norfolk Island"})
CountryCode = Literal["AU", "NF"]
SourceState = Literal["ACT", "EXT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"]


class AustraliaError(RuntimeError):
    """A reviewed source, immutable base or compiled contract differs."""


class NhlFeature(BaseModel):
    """An original attribute row; aliases preserve every published source key."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    object_id: StrictInt = Field(alias="OBJECTID", gt=0)
    place_id: StrictInt = Field(alias="PLACE_ID", gt=0)
    file_no: str = Field(alias="FILE_", min_length=1)
    name: str = Field(alias="NAME", min_length=1)
    source_class: Literal["Historic", "Indigenous"] = Field(alias="CLASS")
    status: Literal["Listed place"] = Field(alias="STATUS")
    state: SourceState = Field(alias="STATE")
    source: str | None = Field(alias="SOURCE")
    area_ha: StrictFloat | StrictInt | None = Field(alias="AREA_HA")
    updated: StrictInt | None = Field(alias="UPDATED")
    url: str = Field(alias="URL")
    register_date: StrictInt | None = Field(alias="REGISTER_DATE")
    address: str | None = Field(alias="ADDRESS")
    shape_area: StrictFloat | StrictInt | None = Field(alias="Shape__Area")
    shape_length: StrictFloat | StrictInt | None = Field(alias="Shape__Length")

    @field_validator("file_no", "name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("NHL original identities cannot be blank")
        return value

    @field_validator("area_ha", "shape_area", "shape_length")
    @classmethod
    def finite_measure(cls, value: float | int | None) -> float | int | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("NHL source numeric metadata must remain finite")
        return value

    @field_validator("url")
    @classmethod
    def official_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname
            not in {
                "www.dcceew.gov.au",
                "dcceew.gov.au",
                "minister.dcceew.gov.au",
            }
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("NHL original object URL requires its public official source")
        return value


class RegisteredRange(BaseModel):
    """Public provider registration geometry metadata; no geometry-derived point."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact: SourceArtifact
    role: Literal["modern_public_registered_heritage_range"]
    geometry_type: Literal["esriGeometryPolygon"]
    source_crs: Literal[4283]
    spatial_reference: Literal[4326]
    feature_ids: list[StrictInt] = Field(min_length=1)
    source_rows: list[NhlFeature] = Field(min_length=1)
    feature_count: StrictInt = Field(gt=0)
    ring_count: StrictInt = Field(gt=0)
    coordinate_records: StrictInt = Field(ge=4)
    per_record_generalisation_status: Literal[
        "not_identified_by_provider",
        "provider_generalised",
    ]

    @model_validator(mode="after")
    def validate_range(self) -> RegisteredRange:
        ids = [row.object_id for row in self.source_rows]
        if (
            len(ids) != len(set(ids))
            or self.feature_ids != ids
            or self.feature_count != len(ids)
            or self.ring_count < self.feature_count
            or self.coordinate_records < 4 * self.ring_count
            or len({row.place_id for row in self.source_rows}) != 1
        ):
            raise ValueError("registered range must retain the complete ordered feature group")
        parsed = urlsplit(self.artifact.uri)
        query = parse_qs(parsed.query)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "gis.environment.gov.au"
            or parsed.path
            != "/gispubmap/rest/services/ogc_services/National_Heritage_List/FeatureServer/0/query"
            or query.get("outSR") != ["4326"]
            or query.get("returnGeometry") != ["true"]
            or query.get("where") != [f"PLACE_ID={self.source_rows[0].place_id}"]
        ):
            raise ValueError(
                "registered range requires its explicit public provider outSR4326 query"
            )
        return self


class CountryLabel(BaseModel):
    """An explicitly sourced UN country-or-area label, never a sovereignty inference."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    code: CountryCode
    label: str
    source_code_literal: str
    source_label_literal: str
    source: SourceReference
    artifact: SourceArtifact

    @model_validator(mode="after")
    def validate_label(self) -> CountryLabel:
        if (
            self.label != COUNTRY_LABELS[self.code]
            or self.source_code_literal != self.code
            or self.source_label_literal != self.label
            or self.source.uri.rstrip("/") != UN_M49_URI
            or self.artifact.uri.rstrip("/") != UN_M49_URI
            or self.artifact.sha256 != UN_M49_SHA256
        ):
            raise ValueError("country-or-area labels require the frozen UN M49 code/name source")
        return self


CountryAssociation = CountryLabel


class AustraliaDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    place_id: StrictInt = Field(gt=0)
    source_features: list[NhlFeature] = Field(min_length=1)
    disposition: Literal["include", "existing", "component", "hold"]
    target_id: str | None
    country_code: Literal["AU"] | None
    additional_country_codes: list[CountryCode] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    evidence: list[SourceReference] = Field(min_length=1)
    source_files: list[SourceArtifact] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_decision(self) -> AustraliaDecision:
        if any(row.place_id != self.place_id for row in self.source_features):
            raise ValueError("NHL decision cannot mix different PLACE_ID rows")
        ids = [row.object_id for row in self.source_features]
        if len(ids) != len(set(ids)) or not self.reason.strip():
            raise ValueError("NHL decision requires unique original features and a reason")
        if self.disposition == "hold":
            if (
                self.target_id is not None
                or self.country_code is not None
                or self.additional_country_codes
            ):
                raise ValueError("held NHL objects cannot gain a public target or country mapping")
        elif not self.target_id or not self.target_id.strip() or self.country_code is None:
            raise ValueError(
                "accepted NHL decisions require a target and sourced country association"
            )
        if self.additional_country_codes and (
            self.additional_country_codes != ["NF"]
            or self.country_code != "AU"
            or self.place_id != 106167
            or any(row.state != "EXT" for row in self.source_features)
            or not any(
                ref.uri == self.source_features[0].url and "Norfolk Island" in ref.excerpt
                for ref in self.evidence
            )
            or not any(
                ref.uri.rstrip("/") == UN_M49_URI and "Norfolk Island" in ref.excerpt
                for ref in self.evidence
            )
        ):
            raise ValueError(
                "additional NF association needs Sirius place-level and UN evidence, retaining AU"
            )
        return self


class AustraliaRecord(SupplementRecord):
    source_features: list[NhlFeature] = Field(min_length=1)
    registered_range: RegisteredRange

    @model_validator(mode="after")
    def validate_reviewed_record(self) -> AustraliaRecord:
        """Reuse supplement checks while retaining the explicitly sourced AU/NF association."""
        site = self.site
        if site.geography is None or site.geography.countries not in (["AU"], ["AU", "NF"]):
            raise ValueError(
                "NHL records retain primary AU and at most an additional NF association"
            )
        if site.geography.countries == ["AU", "NF"] and (
            not self.source_features
            or any(row.place_id != 106167 or row.state != "EXT" for row in self.source_features)
        ):
            raise ValueError(
                "only explicitly reviewed Sirius can gain the additional NF association"
            )
        projected = site.model_copy(
            update={
                "geography": site.geography.model_copy(update={"countries": ["AU"]}),
            }
        )
        payload = {name: getattr(self, name) for name in SupplementRecord.model_fields}
        payload["site"] = projected
        SupplementRecord.model_validate(payload)
        return self

    @model_validator(mode="after")
    def validate_polygon_only_record(self) -> AustraliaRecord:
        site = self.site
        if (
            site.description
            or site.description_zh
            or site.names
            or site.repr_point is not None
            or site.location_precision is not None
            or self.coordinate.method != "unknown"
            or any(
                value is not None
                for value in (
                    self.coordinate.source_uri,
                    self.coordinate.statement_id,
                    self.coordinate.globe,
                    self.coordinate.precision,
                    self.coordinate.rank,
                )
            )
        ):
            raise ValueError(
                "this NHL cohort supplies registered ranges, never inferred points or prose"
            )
        if self.source_features != self.registered_range.source_rows:
            raise ValueError("NHL record/range source rows differ or omit a state feature")
        if any(row.name != site.title for row in self.source_features):
            raise ValueError("NHL title must preserve the exact original registered name")
        if (
            site.details != "Source country association: Australia (AU)."
            or self.country_label != "Australia"
        ):
            raise ValueError("NHL search details must contain only the sourced country association")
        if site.geography is None or site.geography.source not in site.source_refs:
            raise ValueError(
                "NHL geographic association requires its own retained source reference"
            )
        if self.registered_range.artifact not in self.source_files or not any(
            ref.uri == self.registered_range.artifact.uri and ref.license == "CC BY 3.0 Australia"
            for ref in site.source_refs
        ):
            raise ValueError(
                "NHL registered range requires its matching source artifact and licence"
            )
        return self


class AustraliaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cohort_version: Literal["australia-nhl-v1"]
    corpus_version: Literal["global-v12"]
    base_count: Literal[1940]
    base_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    handoff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: Literal[
        "Complete frozen NHL candidate roster; independently reviewed source decisions."
    ]
    countries: list[CountryAssociation]
    decisions: list[AustraliaDecision] = Field(min_length=1)
    records: list[AustraliaRecord]


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_pins() -> None:
    for pin in (
        CANDIDATES_SHA256,
        HANDOFF_SHA256,
        INDEPENDENT_REVIEW_SHA256,
        SOURCE_ROSTER_SHA256,
        SPEC_SHA256,
        SITES_SHA256,
    ):
        if len(pin) != 64 or any(character not in "0123456789abcdef" for character in pin):
            raise AustraliaError(
                "NHL independent source approval and compiled pins are not configured"
            )


def _source_roster(spec: AustraliaSpec) -> list[dict[str, Any]]:
    return [
        {
            "place_id": decision.place_id,
            "source_features": [
                row.model_dump(mode="json", by_alias=True) for row in decision.source_features
            ],
        }
        for decision in sorted(spec.decisions, key=lambda row: row.place_id)
    ]


def _artifacts(spec: AustraliaSpec) -> dict[str, SourceArtifact]:
    result: dict[str, SourceArtifact] = {}
    rows: list[AustraliaDecision | AustraliaRecord | CountryLabel] = [
        *spec.decisions,
        *spec.records,
        *spec.countries,
    ]
    for row in rows:
        artifacts = [row.artifact] if isinstance(row, CountryLabel) else row.source_files
        for artifact in artifacts:
            if artifact.filename in result and result[artifact.filename] != artifact:
                raise AustraliaError("one NHL snapshot filename has conflicting source contracts")
            result[artifact.filename] = artifact
    return result


def _spec(directory: Path) -> AustraliaSpec:
    _require_pins()
    payload = (directory / SPEC_FILE).read_bytes()
    if _hash(payload) != SPEC_SHA256:
        raise AustraliaError("NHL review differs from its independent pin")
    spec = AustraliaSpec.model_validate_json(payload)
    if (
        spec.candidates_sha256 != CANDIDATES_SHA256
        or spec.handoff_sha256 != HANDOFF_SHA256
        or spec.independent_report_sha256 != INDEPENDENT_REVIEW_SHA256
    ):
        raise AustraliaError("NHL candidate/handoff/independent source-review binding differs")
    ids = [row.place_id for row in spec.decisions]
    features = [feature.object_id for row in spec.decisions for feature in row.source_features]
    if len(ids) != len(set(ids)) or len(features) != len(set(features)):
        raise AustraliaError("NHL complete decisions duplicate a PLACE_ID or original feature")
    if _hash(_bytes(_source_roster(spec))) != SOURCE_ROSTER_SHA256:
        raise AustraliaError("NHL complete source roster differs from its external pin")
    records = {row.site.id: row for row in spec.records}
    included = [row for row in spec.decisions if row.disposition == "include"]
    targets = [row.target_id for row in included]
    if (
        len(records) != len(spec.records)
        or len(targets) != len(set(targets))
        or set(targets) != set(records)
    ):
        raise AustraliaError("NHL include decisions and approved records must match one-to-one")
    labels = {row.code: row for row in spec.countries}
    used = {
        code
        for row in spec.decisions
        if row.disposition != "hold"
        for code in [row.country_code, *row.additional_country_codes]
    }
    if len(labels) != len(spec.countries) or set(labels) != used:
        raise AustraliaError(
            "NHL country labels must match explicitly accepted source associations"
        )
    for decision in included:
        if decision.target_id != f"auth:au-nhl:{decision.place_id}":
            raise AustraliaError("NHL canonical target must preserve the exact PLACE_ID")
        assert decision.target_id is not None and decision.country_code is not None
        record = records[decision.target_id]
        geography = record.site.geography
        if (
            record.source_features != decision.source_features
            or geography is None
            or geography.countries != [decision.country_code, *decision.additional_country_codes]
            or geography.regions != ["asia-pacific"]
            or record.country_label != labels[decision.country_code].label
        ):
            raise AustraliaError(
                "NHL record source rows or reviewed country/region association differ"
            )
        if decision.additional_country_codes:
            required = [
                source
                for source in decision.evidence
                if "Norfolk Island" in source.excerpt
                and source.uri.rstrip("/")
                in {decision.source_features[0].url.rstrip("/"), UN_M49_URI}
            ]
            if any(
                not any(
                    ref.uri == source.uri and ref.excerpt == source.excerpt
                    for ref in record.site.source_refs
                )
                for source in required
            ):
                raise AustraliaError(
                    "NHL additional NF evidence must remain in public site sources"
                )
    _artifacts(spec)
    return spec


def _ordered(spec: AustraliaSpec) -> list[AustraliaRecord]:
    return sorted(
        spec.records,
        key=lambda record: (
            _hash((COHORT_VERSION + ":" + record.site.id).encode()),
            record.site.id,
        ),
    )


def _manifest(spec: AustraliaSpec, payload: bytes) -> dict[str, Any]:
    records = _ordered(spec)
    return {
        "schema_version": 1,
        "cohort_version": COHORT_VERSION,
        "corpus_version": CORPUS_VERSION,
        "base": {key: value for key, value in spec.model_dump().items() if key.startswith("base_")},
        "selection": spec.selection,
        "independent_source_review": {
            "candidates_sha256": spec.candidates_sha256,
            "handoff_sha256": spec.handoff_sha256,
            "report_sha256": spec.independent_report_sha256,
            "source_roster_sha256": SOURCE_ROSTER_SHA256,
            "scope": "Source identity/rights/range review; no historical phase or expert approval.",
        },
        "files": {SPEC_FILE: {"sha256": SPEC_SHA256}, SITES_FILE: {"sha256": _hash(payload)}},
        "counts": {
            "base": BASE_COUNT,
            "added": len(records),
            "total": BASE_COUNT + len(records),
            "source_business_ids": len(spec.decisions),
            "source_features": sum(len(row.source_features) for row in spec.decisions),
            "decisions": dict(sorted(Counter(row.disposition for row in spec.decisions).items())),
            "registered_ranges": len(records),
            "registered_range_features": sum(row.registered_range.feature_count for row in records),
            "adopted_representative_points": 0,
        },
        "countries": [
            row.model_dump(mode="json") for row in sorted(spec.countries, key=lambda row: row.code)
        ],
        "decisions": [
            row.model_dump(mode="json", by_alias=True)
            for row in sorted(spec.decisions, key=lambda row: row.place_id)
        ],
        "catalogue_associations": [
            {
                "place_id": row.place_id,
                "site_id": row.target_id,
                "country_code": row.country_code,
                "additional_country_codes": row.additional_country_codes,
                "disposition": row.disposition,
                "note": "Association only; original base fields and countries are unchanged.",
            }
            for row in sorted(spec.decisions, key=lambda row: row.place_id)
            if row.disposition in {"existing", "component"}
        ],
        "records": [
            {
                "id": row.site.id,
                "registered_range": row.registered_range.model_dump(mode="json", by_alias=True),
                "coordinate": row.coordinate.model_dump(mode="json"),
                "identity_review": row.independent_review.model_dump(mode="json"),
                "source_files": [artifact.model_dump() for artifact in row.source_files],
                "provenance": row.provenance,
            }
            for row in records
        ],
        "range_semantics": "Public modern heritage registration range; never an ancient boundary, "
        "excavation extent, representative point or historical polity. Confidential places may "
        "be provider-generalised to a250k map sheet; absent flag is not precise geometry.",
        "chronology": "Listing, editing and publication dates never become historical phases.",
        "licenses": "Named NHL public factual attributes/registered ranges: CC BY3.0 Australia. "
        "Retain Department of the Environment2016 notice and attribution; linked prose, images, "
        "third-party testimony and other registers are outside this data licence grant.",
    }


def rebuild_australia(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Compile pinned approved facts offline, without reading or converting geometry."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        payload = _bytes([row.site.model_dump(mode="json") for row in _ordered(spec)])
        if _hash(payload) != SITES_SHA256:
            raise AustraliaError("compiled NHL sites differ from their independent pin")
        manifest = _manifest(spec, payload)
        (directory / SITES_FILE).write_bytes(payload)
        (directory / MANIFEST_FILE).write_bytes(_bytes(manifest))
        return manifest
    except AustraliaError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise AustraliaError(f"cannot rebuild the frozen NHL supplement: {error}") from error


def load_australia(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Append reviewed identities, preserving every field of all1940 original objects."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        expected_base = {
            "base_count": spec.base_count,
            "base_ids_sha256": spec.base_ids_sha256,
            "base_sites_sha256": spec.base_sites_sha256,
        }
        if base_contract(base) != expected_base:
            raise AustraliaError("NHL base differs from the complete unchanged1940 contract")
        base_ids = {site.id for site in base}
        if len(base_ids) != BASE_COUNT or any(
            row.target_id not in base_ids
            for row in spec.decisions
            if row.disposition in {"existing", "component"}
        ):
            raise AustraliaError("NHL existing/component target is absent or base IDs duplicate")
        additions = [row.site for row in _ordered(spec)]
        if base_ids & {site.id for site in additions}:
            raise AustraliaError("NHL additions duplicate an existing identity")
        if any(site.geography and "NF" in site.geography.countries for site in base) and any(
            row.code == "NF" for row in spec.countries
        ):
            raise AustraliaError(
                "NHL new NF label cannot overwrite an existing source country label"
            )
        payload = (directory / SITES_FILE).read_bytes()
        expected = _bytes([site.model_dump(mode="json") for site in additions])
        if payload != expected or _hash(payload) != SITES_SHA256:
            raise AustraliaError("NHL sites differ from the independently reviewed specification")
        if _bytes(json.loads((directory / MANIFEST_FILE).read_bytes())) != _bytes(
            _manifest(spec, payload)
        ):
            raise AustraliaError("NHL manifest differs from its frozen contract")
        return base + additions
    except AustraliaError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise AustraliaError(f"cannot load the frozen NHL supplement: {error}") from error


def new_country_labels(data_dir: Path = DATA_DIR) -> MappingProxyType[str, str]:
    """Expose only a reviewed NF addition; the existing AU label is never overwritten."""
    try:
        spec = _spec(Path(data_dir))
        return MappingProxyType({row.code: row.label for row in spec.countries if row.code != "AU"})
    except AustraliaError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise AustraliaError(f"cannot load reviewed NHL country-or-area labels: {error}") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Validate optional frozen source bytes; do not fetch, parse or execute them."""
    try:
        spec = _spec(Path(data_dir))
        root = Path(cache_dir).resolve()
        artifacts = _artifacts(spec)
        for filename, artifact in artifacts.items():
            path = (root / filename).resolve()
            if not path.is_relative_to(root) or _hash(path.read_bytes()) != artifact.sha256:
                raise AustraliaError(f"NHL source snapshot differs: {filename}")
        return len(artifacts)
    except AustraliaError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise AustraliaError(f"cannot verify NHL source snapshots: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile independently reviewed NHL facts offline")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--verify-source-cache", type=Path)
    args = parser.parse_args()
    try:
        if args.verify_source_cache is not None:
            print(
                json.dumps(
                    {
                        "verified_source_files": verify_source_cache(
                            args.verify_source_cache,
                            args.data_dir,
                        )
                    }
                )
            )
        if args.rebuild:
            print(json.dumps(rebuild_australia(args.data_dir)["counts"]))
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild or --verify-source-cache")
    except AustraliaError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
