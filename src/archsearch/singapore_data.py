"""Compile independently reviewed NHB source facts and reference points entirely offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from archsearch.domain import Geography, Site, SourceReference
from archsearch.supplement_data import (
    CoordinateEvidence,
    IdentityReview,
    SourceArtifact,
    SupplementRecord,
    base_contract,
)

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "singapore-monuments-v1"
CORPUS_VERSION = "global-v15"
BASE_COUNT = 3116
DATASET_ID = "d_b29c230ec6b609e29ed42f71ca9a8767"
DATASET_URI = f"https://data.gov.sg/datasets/{DATASET_ID}/view"
GEOJSON_URI = f"https://s3.ap-southeast-1.amazonaws.com/blobs.data.gov.sg/{DATASET_ID}.geojson"
LICENCE_URI = "https://data.gov.sg/open-data-licence"
LICENCE = "Singapore Open Data Licence version 1.0"
ROOTS_PREFIX = "https://www.roots.gov.sg/places/places-landing/Places/national-monuments/"
UN_M49_URI = "https://unstats.un.org/unsd/methodology/m49/overview"
UN_M49_SHA256 = "b9048114f6e7f2abda83bf03d4263c9d7cd1bd7230e3d0461025ee7839a7a1fb"
ROSTER_FILE = "singapore_source_roster.json"
SPEC_FILE = "singapore_review.json"
SITES_FILE = "singapore_sites.json"
MANIFEST_FILE = "singapore_manifest.json"
MAX_ROSTER_BYTES = 2 * 1024 * 1024
MAX_REVIEW_BYTES = 4 * 1024 * 1024
MAX_SITES_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
SELECTION = "Complete frozen source feature decisions; independently qualified whole objects only."
# Source approvals and derived files are deliberately closed until independently pinned.
RAW_SOURCE_SHA256 = "a9566c0c0ae061e1ea429bd5e6221a02cb443f6ce0a63d5089647af25624a4d6"
METADATA_SHA256 = "fcabd626e5247346b8e9fab201567dd6dbf1de7d1e6c40e8e6be07ff0af2debc"
LICENCE_SHA256 = "fc719fc67465450f00d43b6628c78d2a177f375db7d1a284e4f0d2bd2a61f6b9"
CANDIDATES_SHA256 = "a5df221505d282b06afdf8542e571eb320fc42602ec15d7522e1bb1fa23e4c5d"
HANDOFF_SHA256 = "73736d5a83c8e329a12220686131ad670dfe41cde1cbf3a6363eef0e847a71d6"
INDEPENDENT_REVIEW_SHA256 = "29ff3c024564de3e52918c846584c744f1a5e91f102bca9ff8d68d4429009c64"
SOURCE_FACTS_SHA256 = "a0c8571137ad37f6a6d97d7619f03d70840a36fc4801779f231909cfad8473f1"
SOURCE_ROSTER_SHA256 = "7426a4f008df2724df9d7d2c25ffe321f1f6149df65e97e1978b93a1a00003f8"
SPEC_SHA256 = "c5200f2306653ad11a5779af41ceaad9ea24a11122a5b8f1131bc88ec785f79a"
SITES_SHA256 = "dd684ddcbed0941b5a3cc4406c74d9f6d112e4455d9f3fc40cfa58b857731d43"
Number = StrictFloat | StrictInt


class SingaporeError(RuntimeError):
    """A source approval, original feature, unchanged base or compiled contract differs."""


class SourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: SourceReference
    artifact: SourceArtifact

    @model_validator(mode="after")
    def validate_binding(self) -> SourceEvidence:
        if self.source.uri != self.artifact.uri or not self.source.excerpt.strip():
            raise ValueError("source facts require a short excerpt bound to the same original URI")
        return self


def project_id(business_uri: str) -> str:
    """A project identity for an original business URI, never a statutory or provider OID."""
    return "auth:sg-nhb:roots-" + hashlib.sha256(business_uri.encode("utf-8")).hexdigest()


class SingaporeSourceRow(BaseModel):
    """All 16 original dataset properties, preserving aliases, nullable values and raw clocks."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    object_id: StrictInt = Field(alias="OBJECTID", gt=0)
    address_block: StrictStr | None = Field(alias="ADDRESSBLOCKHOUSENUMBER")
    address_building: StrictStr | None = Field(alias="ADDRESSBUILDINGNAME")
    address_postal_code: StrictStr | None = Field(alias="ADDRESSPOSTALCODE")
    address_street: StrictStr | None = Field(alias="ADDRESSSTREETNAME")
    address_type: StrictStr | None = Field(alias="ADDRESSTYPE")
    hyperlink: StrictStr = Field(alias="HYPERLINK")
    land_x: Number = Field(alias="LANDXADDRESSPOINT")
    land_y: Number = Field(alias="LANDYADDRESSPOINT")
    name: StrictStr = Field(alias="NAME", min_length=1)
    photo_uri: StrictStr | None = Field(alias="PHOTOURL")
    address_floor: StrictStr | None = Field(alias="ADDRESSFLOORNUMBER")
    provider_crc: StrictStr = Field(alias="INC_CRC", pattern=r"^[0-9A-Fa-f]{16}$")
    feature_updated_raw: StrictStr = Field(alias="FMEL_UPD_D", pattern=r"^[0-9]{14}$")
    address_unit: StrictStr | None = Field(alias="ADDRESSUNITNUMBER")
    description: StrictStr = Field(alias="DESCRIPTION", max_length=425)

    @field_validator("land_x", "land_y")
    @classmethod
    def finite_native_metadata(cls, value: float | int) -> float | int:
        if not math.isfinite(value):
            raise ValueError("original projected address fields must remain finite")
        return value

    @field_validator("hyperlink")
    @classmethod
    def official_business_uri(cls, value: str) -> str:
        if (
            not value.startswith(ROOTS_PREFIX)
            or re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", value[len(ROOTS_PREFIX) :]) is None
        ):
            raise ValueError("business identity requires its exact public Roots monument URI")
        return value

    @field_validator("feature_updated_raw")
    @classmethod
    def valid_raw_clock(cls, value: str) -> str:
        if datetime.strptime(value, "%Y%m%d%H%M%S").strftime("%Y%m%d%H%M%S") != value:
            raise ValueError("FMEL update metadata must retain its original clock")
        return value

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the original monument name cannot be blank")
        return value


class ProviderPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["Point"]
    coordinates: tuple[Number, Number]

    @model_validator(mode="after")
    def validate_coordinates(self) -> ProviderPoint:
        longitude, latitude = self.coordinates
        if (
            not math.isfinite(longitude)
            or not math.isfinite(latitude)
            or not -180 <= longitude <= 180
            or not -90 <= latitude <= 90
        ):
            raise ValueError("provider GeoJSON requires finite longitude/latitude WGS84 values")
        return self


class SingaporeFeature(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_index: StrictInt = Field(ge=0)
    source_row: SingaporeSourceRow
    geometry: ProviderPoint
    feature_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    def original_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": self.geometry.model_dump(mode="json"),
            "properties": self.source_row.model_dump(mode="json", by_alias=True),
        }

    @model_validator(mode="after")
    def validate_original_hash(self) -> SingaporeFeature:
        if feature_hash(self.original_feature()) != self.feature_sha256:
            raise ValueError("normalized feature differs from its complete original feature hash")
        return self


class SingaporeSourceRoster(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    dataset_id: Literal["d_b29c230ec6b609e29ed42f71ca9a8767"]
    collection_name: Literal["MONUMENTS"]
    source_artifact: SourceArtifact
    features: list[SingaporeFeature] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_inventory(self) -> SingaporeSourceRoster:
        ids = [row.source_row.object_id for row in self.features]
        uris = [row.source_row.hyperlink for row in self.features]
        if (
            self.source_artifact.uri != GEOJSON_URI
            or [row.source_index for row in self.features] != list(range(len(ids)))
            or len(ids) != len(set(ids))
            or len(uris) != len(set(uris))
        ):
            raise ValueError(
                "source roster must retain every ordered original feature identity once"
            )
        return self


class PointDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    adoption: Literal["provider_reference", "not_adopted"]
    role: Literal["provider_point_used_as_reference_no_centre_or_precision_claim"]
    reason: StrictStr = Field(min_length=1)
    evidence: list[SourceEvidence] = Field(min_length=1)


class SingaporeWhole(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_object_id: StrictInt = Field(gt=0)
    title: StrictStr = Field(min_length=1)
    business_uri: StrictStr
    primary_source_uri: StrictStr | None = None
    scope_kind: Literal["whole_place", "composite_whole", "specified_parts"]
    supported_scope_literal: StrictStr = Field(min_length=1)
    scope_evidence: list[SourceEvidence] = Field(min_length=1)
    point: PointDecision

    @property
    def project_id(self) -> str:
        return project_id(self.business_uri)

    @field_validator("primary_source_uri")
    @classmethod
    def safe_current_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname
            not in {
                "www.roots.gov.sg",
                "roots.gov.sg",
                "www.ura.gov.sg",
                "ura.gov.sg",
                "www.nhb.gov.sg",
                "nhb.gov.sg",
            }
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "current primary source requires a safe stable official whole-object URI"
            )
        return value


class SingaporeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    whole: SingaporeWhole
    disposition: Literal["include", "existing", "component", "hold"]
    target_id: StrictStr | None
    reason: StrictStr = Field(min_length=1)
    evidence: list[SourceEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_target(self) -> SingaporeDecision:
        if not self.reason.strip():
            raise ValueError("source decisions require a reason")
        if self.disposition == "hold":
            if self.target_id is not None:
                raise ValueError("held objects cannot acquire a public target")
        elif not self.target_id or not self.target_id.strip():
            raise ValueError("accepted objects require an independently checked target")
        if self.disposition == "include" and self.target_id != self.whole.project_id:
            raise ValueError("included IDs must preserve the exact original business URI hash")
        if self.whole.primary_source_uri is not None and not any(
            item.source.uri == self.whole.primary_source_uri
            for item in [*self.evidence, *self.whole.scope_evidence]
        ):
            raise ValueError("current primary URI requires its own retained whole-object evidence")
        return self


class SingaporeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_object_id: StrictInt = Field(gt=0)
    independent_review: IdentityReview
    evidence: list[SourceEvidence] = Field(min_length=1)
    provenance: dict[str, Any]


class DatasetMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_feature_count: StrictInt = Field(gt=0)
    published_coverage_literal: StrictStr = Field(min_length=1)
    catalogue_last_updated_literal: StrictStr = Field(min_length=1)
    update_frequency_literal: StrictStr = Field(min_length=1)
    evidence: SourceEvidence
    provider_declared_crs: None
    coordinate_interpretation: Literal[
        "GeoJSON_default_WGS84_longitude_latitude_not_explicit_provider_precision"
    ]
    coordinate_evidence: list[SourceEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_uri(self) -> DatasetMetadata:
        if self.evidence.source.uri != DATASET_URI:
            raise ValueError("dataset clocks need their own exact catalogue source")
        return self


class LicenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Literal["Singapore Open Data Licence version 1.0"]
    evidence: SourceEvidence
    attribution: StrictStr = Field(min_length=1)
    accessed: StrictStr = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    scope: Literal["published_dataset_fields_and_reference_points_not_linked_pages_or_images"]

    @model_validator(mode="after")
    def validate_source(self) -> LicenceReview:
        if (
            self.evidence.source.uri != LICENCE_URI
            or DATASET_URI not in self.attribution
            or LICENCE_URI not in self.attribution
        ):
            raise ValueError("licence acknowledgement needs dataset, access date and licence links")
        datetime.strptime(self.accessed, "%Y-%m-%d")
        if self.accessed not in self.attribution:
            raise ValueError("licence acknowledgement must retain its access date")
        return self


class CountryAssociation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: Literal["SG"]
    region: Literal["asia-pacific"]
    source_m49_cells: list[StrictStr] = Field(min_length=15, max_length=15)
    region_role: Literal["project_catalogue_grouping_from_m49_asia_south_eastern_asia"]
    evidence: list[SourceEvidence] = Field(min_length=1)
    role: Literal["modern_source_catalogue_association_not_point_inferred_sovereignty"]

    @model_validator(mode="after")
    def validate_source_association(self) -> CountryAssociation:
        if self.source_m49_cells != [
            "001",
            "World",
            "142",
            "Asia",
            "035",
            "South-eastern Asia",
            "",
            "",
            "Singapore",
            "702",
            "SG",
            "SGP",
            "",
            "",
            "x",
        ] or not any(
            item.source.uri.rstrip("/") == UN_M49_URI and item.artifact.sha256 == UN_M49_SHA256
            for item in self.evidence
        ):
            raise ValueError(
                "SG code/region needs its original active M49 row, not inferred coordinates"
            )
        return self


class SingaporeReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cohort_version: Literal["singapore-monuments-v1"]
    corpus_version: Literal["global-v15"]
    base_count: Literal[3116]
    base_ids_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    candidates_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    handoff_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    independent_report_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    selection: Literal[
        "Complete frozen source feature decisions; independently qualified whole objects only."
    ]
    metadata: DatasetMetadata
    licence: LicenceReview
    country: CountryAssociation
    decisions: list[SingaporeDecision] = Field(min_length=1)
    records: list[SingaporeRecord]


class SingaporeSpec(BaseModel):
    """Validated join of compact reviewed facts and a separate immutable original-row roster."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    roster: SingaporeSourceRoster
    review: SingaporeReview


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def feature_hash(feature: dict[str, Any]) -> str:
    return _hash(
        json.dumps(feature, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )


def _source_facts(spec: SingaporeSpec) -> dict[str, Any]:
    return {
        "roster": spec.roster.model_dump(mode="json", by_alias=True),
        "review": spec.review.model_dump(
            mode="json",
            by_alias=True,
            exclude={
                "candidates_sha256",
                "handoff_sha256",
                "independent_report_sha256",
            },
        ),
    }


def _read_bounded(root: Path, filename: str, limit: int) -> bytes:
    directory = root.resolve()
    path = (directory / filename).resolve()
    if not path.is_relative_to(directory):
        raise SingaporeError("local source or compiled path escapes its chosen directory")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise SingaporeError(f"local Singapore file exceeds its bounded contract: {filename}")
    return raw


def _require_pins() -> None:
    for pin in (
        RAW_SOURCE_SHA256,
        METADATA_SHA256,
        LICENCE_SHA256,
        CANDIDATES_SHA256,
        HANDOFF_SHA256,
        INDEPENDENT_REVIEW_SHA256,
        SOURCE_FACTS_SHA256,
        SOURCE_ROSTER_SHA256,
        SPEC_SHA256,
        SITES_SHA256,
    ):
        if re.fullmatch(r"[0-9a-f]{64}", pin) is None:
            raise SingaporeError(
                "Singapore independent source approval and compiled pins are not configured"
            )


def _evidence(spec: SingaporeSpec) -> list[SourceEvidence]:
    result = [
        spec.review.metadata.evidence,
        *spec.review.metadata.coordinate_evidence,
        spec.review.licence.evidence,
        *spec.review.country.evidence,
    ]
    for decision in spec.review.decisions:
        result.extend(
            [*decision.evidence, *decision.whole.scope_evidence, *decision.whole.point.evidence]
        )
    result.extend(item for record in spec.review.records for item in record.evidence)
    return result


def _artifacts(spec: SingaporeSpec) -> dict[str, SourceArtifact]:
    result: dict[str, SourceArtifact] = {}
    for artifact in [spec.roster.source_artifact, *(item.artifact for item in _evidence(spec))]:
        if artifact.filename in result and result[artifact.filename] != artifact:
            raise SingaporeError("one cache filename has conflicting original source contracts")
        result[artifact.filename] = artifact
    return result


def _validate_spec(spec: SingaporeSpec) -> None:
    features = {row.source_row.object_id: row for row in spec.roster.features}
    decisions = {row.whole.source_object_id: row for row in spec.review.decisions}
    records = {row.source_object_id: row for row in spec.review.records}
    if (
        spec.review.metadata.source_feature_count != len(features)
        or len(decisions) != len(spec.review.decisions)
        or set(decisions) != set(features)
    ):
        raise SingaporeError(
            "complete decisions must account for every original source feature once"
        )
    included = {key for key, row in decisions.items() if row.disposition == "include"}
    if len(records) != len(spec.review.records) or set(records) != included:
        raise SingaporeError("included decisions and approved records must match one-to-one")
    for identifier, decision in decisions.items():
        row = features[identifier].source_row
        if decision.whole.title != row.name or decision.whole.business_uri != row.hyperlink:
            raise SingaporeError("reviewed whole cannot replace its original name or business URI")
    targets = [row.target_id for row in decisions.values() if row.disposition == "include"]
    if len(targets) != len(set(targets)):
        raise SingaporeError("newly included whole identities must be unique")
    _artifacts(spec)


def _spec(directory: Path) -> SingaporeSpec:
    _require_pins()
    raw_roster = _read_bounded(directory, ROSTER_FILE, MAX_ROSTER_BYTES)
    raw_review = _read_bounded(directory, SPEC_FILE, MAX_REVIEW_BYTES)
    if _hash(raw_roster) != SOURCE_ROSTER_SHA256 or _hash(raw_review) != SPEC_SHA256:
        raise SingaporeError(
            "Singapore normalized roster or review differs from its independent pin"
        )
    spec = SingaporeSpec(
        roster=SingaporeSourceRoster.model_validate_json(raw_roster),
        review=SingaporeReview.model_validate_json(raw_review),
    )
    review = spec.review
    if (
        spec.roster.source_artifact.sha256 != RAW_SOURCE_SHA256
        or review.metadata.evidence.artifact.sha256 != METADATA_SHA256
        or review.licence.evidence.artifact.sha256 != LICENCE_SHA256
        or review.candidates_sha256 != CANDIDATES_SHA256
        or review.handoff_sha256 != HANDOFF_SHA256
        or review.independent_report_sha256 != INDEPENDENT_REVIEW_SHA256
    ):
        raise SingaporeError(
            "Singapore original data/metadata/licence/independent review binding differs"
        )
    if _hash(_bytes(_source_facts(spec))) != SOURCE_FACTS_SHA256:
        raise SingaporeError(
            "Singapore complete approved source facts differ from their independent pin"
        )
    _validate_spec(spec)
    return spec


def _ordered(spec: SingaporeSpec) -> list[SingaporeRecord]:
    by_id = {row.source_row.object_id: row.source_row for row in spec.roster.features}
    return sorted(
        spec.review.records,
        key=lambda record: (
            _hash(
                (
                    COHORT_VERSION + ":" + project_id(by_id[record.source_object_id].hyperlink)
                ).encode()
            ),
            project_id(by_id[record.source_object_id].hyperlink),
        ),
    )


def source_details(row: SingaporeSourceRow, metadata: DatasetMetadata) -> str:
    address = {
        field: row.model_dump(by_alias=True)[field]
        for field in (
            "ADDRESSBLOCKHOUSENUMBER",
            "ADDRESSBUILDINGNAME",
            "ADDRESSPOSTALCODE",
            "ADDRESSSTREETNAME",
            "ADDRESSTYPE",
            "ADDRESSFLOORNUMBER",
            "ADDRESSUNITNUMBER",
        )
    }
    return (
        "Source catalogue association: Singapore (SG).\n"
        "Original source address fields: " + json.dumps(address, ensure_ascii=False) + "\n"
        f"Published coverage: {metadata.published_coverage_literal}; "
        f"catalogue updated: {metadata.catalogue_last_updated_literal}; "
        f"FMEL_UPD_D (original, timezone unspecified): {row.feature_updated_raw}.\n"
        "These are independent source administrative clocks, not construction/use phases.\n"
        "来源Point作为公开参考位置；项目未将其视为整体中心，提供者未给计算方法或精度。"
    )


def compile_singapore(spec: SingaporeSpec) -> list[Site]:
    """Project reviewed dataset fields only; approval remains the pinned loader's responsibility."""
    _validate_spec(spec)
    features = {row.source_row.object_id: row for row in spec.roster.features}
    decisions = {row.whole.source_object_id: row for row in spec.review.decisions}
    result = []
    for record in _ordered(spec):
        feature = features[record.source_object_id]
        row = feature.source_row
        decision = decisions[row.object_id]
        adopted = decision.whole.point.adoption == "provider_reference"
        point = feature.geometry.coordinates if adopted else None
        evidence = [
            spec.review.metadata.evidence,
            *decision.whole.scope_evidence,
            *spec.review.country.evidence,
        ]
        references = list(dict.fromkeys(item.source.model_dump_json() for item in evidence))
        source_refs = [SourceReference.model_validate_json(value) for value in references]
        if decision.whole.primary_source_uri is not None and not any(
            item.uri == decision.whole.primary_source_uri for item in source_refs
        ):
            primary = next(
                item.source
                for item in decision.evidence
                if item.source.uri == decision.whole.primary_source_uri
            )
            source_refs.append(primary.model_copy(update={"excerpt": ""}))
        source_refs.append(
            SourceReference(
                id=f"source:sg-nhb:{row.object_id}",
                title="Monuments (GEOJSON), original dataset fields",
                uri=DATASET_URI,
                publisher="National Heritage Board, Singapore",
                license=LICENCE,
                accessed=spec.review.licence.accessed,
                excerpt="National Monuments",
                revision="sha256:" + spec.roster.source_artifact.sha256,
            )
        )
        site = Site(
            id=decision.whole.project_id,
            title=row.name,
            description=row.description,
            description_zh="",
            details=source_details(row, spec.review.metadata)
            + "\n来源已核整体范围："
            + decision.whole.supported_scope_literal
            + (
                f"\nOriginal dataset business URI: {row.hyperlink}\n"
                f"Independently checked current source URI: {decision.whole.primary_source_uri}"
                if decision.whole.primary_source_uri is not None
                else ""
            ),
            names=[],
            types=["historic-site"],
            periods=[],
            repr_point=point,
            location_precision=None,
            source_uri=decision.whole.primary_source_uri or row.hyperlink,
            contributors=["National Heritage Board, Singapore"],
            period_evidence=[],
            source_kind="supplement",
            source_refs=source_refs,
            geography=Geography(
                authority_id="supplement:" + decision.whole.project_id,
                countries=["SG"],
                regions=["asia-pacific"],
                source=spec.review.country.evidence[0].source,
                point_count=1 if adopted else 0,
                note=(
                    "现代来源目录关联；项目URI身份非法定编号，来源参考点不推断政治归属。"
                    + (
                        "采用原GeoJSON Point作为参考位置；项目未计算或视其为整体中心；"
                        "提供者未给计算方法或精度。"
                        if adopted
                        else "未采用来源Point作为代表点。"
                    )
                    + decision.whole.point.reason
                ),
            ),
        )
        artifacts = {item.artifact.filename: item.artifact for item in evidence}
        artifacts[spec.roster.source_artifact.filename] = spec.roster.source_artifact
        SupplementRecord(
            site=site,
            country_label="Singapore",
            coordinate=CoordinateEvidence(
                method="authority" if adopted else "unknown",
                point=point,
                source_uri=DATASET_URI if adopted else None,
                note=decision.whole.point.reason,
            ),
            independent_review=record.independent_review,
            source_files=list(artifacts.values()),
            provenance=record.provenance,
        )
        result.append(site)
    return result


def _manifest(spec: SingaporeSpec, payload: bytes) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "cohort_version": COHORT_VERSION,
        "corpus_version": CORPUS_VERSION,
        "base": {
            key: value for key, value in spec.review.model_dump().items() if key.startswith("base_")
        },
        "selection": spec.review.selection,
        "independent_source_review": {
            "candidates_sha256": CANDIDATES_SHA256,
            "handoff_sha256": HANDOFF_SHA256,
            "report_sha256": INDEPENDENT_REVIEW_SHA256,
            "source_facts_sha256": SOURCE_FACTS_SHA256,
            "source_roster_sha256": SOURCE_ROSTER_SHA256,
        },
        "files": {
            ROSTER_FILE: {"sha256": SOURCE_ROSTER_SHA256},
            SPEC_FILE: {"sha256": SPEC_SHA256},
            SITES_FILE: {"sha256": _hash(payload)},
        },
        "counts": {
            "base": BASE_COUNT,
            "source_features": len(spec.roster.features),
            "added": len(spec.review.records),
            "total": BASE_COUNT + len(spec.review.records),
            "decisions": dict(
                sorted(Counter(row.disposition for row in spec.review.decisions).items())
            ),
            "adopted_reference_points": sum(
                row.whole.point.adoption == "provider_reference" and row.disposition == "include"
                for row in spec.review.decisions
            ),
            "new_historical_phases": 0,
        },
        "metadata": spec.review.metadata.model_dump(mode="json"),
        "source_feature_clocks": [
            {
                "object_id": row.source_row.object_id,
                "FMEL_UPD_D": row.source_row.feature_updated_raw,
            }
            for row in spec.roster.features
        ],
        "licence": spec.review.licence.model_dump(mode="json"),
        "country": spec.review.country.model_dump(mode="json"),
        "decisions": [row.model_dump(mode="json") for row in spec.review.decisions],
        "records": [row.model_dump(mode="json") for row in _ordered(spec)],
        "source_artifacts": [
            item.model_dump(mode="json") for _, item in sorted(_artifacts(spec).items())
        ],
        "semantics": "Dataset descriptions are original licensed fields, not linked webpage prose. "
        "Provider GeoJSON points retain unknown calculation method and precision; "
        "the project neither computes nor treats them as whole centres. "
        "No local reprojection, address conversion, photos or historical phases.",
    }


def _validate_base(base: list[Site], spec: SingaporeSpec) -> set[str]:
    expected = {
        key: value for key, value in spec.review.model_dump().items() if key.startswith("base_")
    }
    if base_contract(base) != expected:
        raise SingaporeError("Singapore base differs from the unchanged3116 field/order contract")
    base_ids = {site.id for site in base}
    if len(base_ids) != BASE_COUNT or any(
        row.target_id not in base_ids
        for row in spec.review.decisions
        if row.disposition in {"existing", "component"}
    ):
        raise SingaporeError("Singapore existing/component target is absent or base IDs duplicate")
    return base_ids


def rebuild_singapore(
    data_dir: Path = DATA_DIR,
    *,
    base: list[Site] | None = None,
) -> dict[str, Any]:
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        if base is not None:
            _validate_base(base, spec)
        payload = _bytes([site.model_dump(mode="json") for site in compile_singapore(spec)])
        if _hash(payload) != SITES_SHA256:
            raise SingaporeError("compiled Singapore sites differ from their independent pin")
        manifest = _manifest(spec, payload)
        (directory / SITES_FILE).write_bytes(payload)
        (directory / MANIFEST_FILE).write_bytes(_bytes(manifest))
        return manifest
    except SingaporeError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise SingaporeError(f"cannot rebuild frozen Singapore facts: {error}") from error


def load_singapore(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        base_ids = _validate_base(base, spec)
        additions = compile_singapore(spec)
        if base_ids & {site.id for site in additions}:
            raise SingaporeError("Singapore additions duplicate an existing identity")
        payload = _read_bounded(directory, SITES_FILE, MAX_SITES_BYTES)
        if (
            payload != _bytes([site.model_dump(mode="json") for site in additions])
            or _hash(payload) != SITES_SHA256
        ):
            raise SingaporeError("Singapore sites differ from independently approved facts")
        manifest = json.loads(_read_bounded(directory, MANIFEST_FILE, MAX_MANIFEST_BYTES))
        if _bytes(manifest) != _bytes(_manifest(spec, payload)):
            raise SingaporeError("Singapore manifest differs from its frozen contract")
        return base + additions
    except SingaporeError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise SingaporeError(f"cannot load frozen Singapore facts: {error}") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Check optional original snapshots and all original features; never fetch a source."""
    try:
        spec = _spec(Path(data_dir))
        root = Path(cache_dir)
        artifacts = _artifacts(spec)
        for filename, artifact in artifacts.items():
            if _hash(_read_bounded(root, filename, MAX_SOURCE_BYTES)) != artifact.sha256:
                raise SingaporeError(f"Singapore source snapshot differs: {filename}")
        source = json.loads(
            _read_bounded(root, spec.roster.source_artifact.filename, MAX_SOURCE_BYTES)
        )
        if (
            not isinstance(source, dict)
            or set(source) != {"type", "name", "features"}
            or source["type"] != "FeatureCollection"
            or source["name"] != "MONUMENTS"
            or not isinstance(source["features"], list)
            or len(source["features"]) != len(spec.roster.features)
        ):
            raise SingaporeError("Singapore original FeatureCollection is incomplete or differs")
        fields = [field.alias or name for name, field in SingaporeSourceRow.model_fields.items()]
        for original, feature in zip(source["features"], spec.roster.features, strict=True):
            if (
                original != feature.original_feature()
                or feature_hash(original) != feature.feature_sha256
                or list(original["properties"]) != fields
            ):
                raise SingaporeError(
                    "Singapore original properties/point/order/feature hash differs"
                )
        return len(artifacts)
    except SingaporeError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise SingaporeError(f"cannot verify Singapore source snapshots: {error}") from error


def main() -> None:
    from archsearch.corpus import CorpusError, load_pre_singapore_corpus

    parser = argparse.ArgumentParser(description=__doc__)
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
                            args.verify_source_cache, args.data_dir
                        )
                    }
                )
            )
        if args.rebuild:
            base = load_pre_singapore_corpus(args.data_dir)
            print(json.dumps(rebuild_singapore(args.data_dir, base=base)["counts"]))
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild and/or --verify-source-cache")
    except (SingaporeError, CorpusError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
