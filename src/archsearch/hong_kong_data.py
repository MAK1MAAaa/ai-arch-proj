"""Compile reviewed Hong Kong monument facts offline; never derive points or phases."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
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
COHORT_VERSION = "hong-kong-monuments-v1"
CORPUS_VERSION = "global-v14"
BASE_COUNT = 2976
SPEC_FILE = "hong_kong_review.json"
SITES_FILE = "hong_kong_sites.json"
MANIFEST_FILE = "hong_kong_manifest.json"
DATASET_ID = "devb_wb_rcd_1639040299687_46105"
LAYER_NAME = "DM_20260130_150858"
METADATA_URI = f"https://portal.csdi.gov.hk/csdi-webpage/metadata/{DATASET_ID}/html"
TERMS_URI = "https://portal.csdi.gov.hk/csdi-webpage/doc/TNC"
QUERY_URI = (
    f"https://portal.csdi.gov.hk/server/rest/services/common/{DATASET_ID}/FeatureServer/0/query"
)
CSDI_LICENSE = "CSDI Portal Terms and Conditions of Use"
COUNTRY_LABEL = "Hong Kong"
UN_M49_URI = "https://unstats.un.org/unsd/methodology/m49/overview"
UN_M49_SHA256 = "b9048114f6e7f2abda83bf03d4263c9d7cd1bd7230e3d0461025ee7839a7a1fb"
SELECTION = "All independently qualified official whole objects; no fixed addition quota."
# Closed until independent source/scope/dedup review and compiled artifacts are pinned.
CANDIDATES_SHA256 = "dd9a27eb20797eed244b0a77d5f527e6ed22b96c48ff001e559bbdfb7d76cae6"
HANDOFF_SHA256 = "e7c3056ba120c5f5c9a5ebe010fb59309b6ab5e5b3a7b8ee93fdb779438fcb8f"
INDEPENDENT_REVIEW_SHA256 = "c4db9409b0c9ad76976ea0dec1b8950da6d9c944d7839eb1ffd449ce0d1440bc"
SOURCE_ROSTER_SHA256 = "0bf80d28eb24a3c23397519db82429ca58af83c036125473362de140a1de6f14"
SOURCE_FACTS_SHA256 = "aef451de987e1e550a106fbb49aea99362095bddc3a295e48f188d27a357bd0a"
SPEC_SHA256 = "b0bcbe915c46bf611aab9b35b76c4365eb398a1032cf7705aa8302448611bf7a"
SITES_SHA256 = "060b987147f589ebd5fc3f5e0dd24bb3624ec5fb21608baeede7ac79d20ddfa2"
DirectoryArea = Literal["hong-kong-island", "kowloon", "new-territories", "outlying-islands"]


class HongKongError(RuntimeError):
    """An independent source approval, unchanged base or compiled contract differs."""


class SourceEvidence(BaseModel):
    """A short factual source reference bound to its original cached response."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source: SourceReference
    artifact: SourceArtifact

    @model_validator(mode="after")
    def validate_binding(self) -> SourceEvidence:
        if self.source.uri != self.artifact.uri or not self.source.excerpt.strip():
            raise ValueError("source facts need a nonempty excerpt and the same original URI")
        return self


class CsdiSourceRow(BaseModel):
    """All 19 original attributes; provider OIDs and file refs are release feature identities."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    file_ref: StrictStr | None = Field(alias="FILE_REF")
    name: StrictStr | None = Field(alias="NAME")
    name_tc: StrictStr | None = Field(alias="NAME_TC")
    address: StrictStr | None = Field(alias="ADDRESS")
    address_tc: StrictStr | None = Field(alias="ADDRESS_TC")
    district: StrictStr | None = Field(alias="DISTRICT")
    data_owner: StrictStr | None = Field(alias="DATA_OWNER")
    district_tc: StrictStr | None = Field(alias="DISTRIC_TC")
    declaration_year: StrictInt | None = Field(alias="DEC_YEAR")
    declaration_year_tc: StrictInt | None = Field(alias="DEC_YE_TC")
    file_ref_tc: StrictStr | None = Field(alias="FILEREF_TC")
    detail: StrictStr | None = Field(alias="DETAIL")
    detail_tc: StrictStr | None = Field(alias="DETAIL_TC")
    dataset: StrictStr | None = Field(alias="DATASET")
    dataset_tc: StrictStr | None = Field(alias="DATASET_TC")
    image_uri: StrictStr | None = Field(alias="URL_IMAGE")
    object_id: StrictInt = Field(alias="OBJECTID", gt=0)
    shape_length: StrictFloat | StrictInt | None = Field(alias="Shape__Length")
    shape_area: StrictFloat | StrictInt | None = Field(alias="Shape__Area")

    @field_validator("shape_length", "shape_area")
    @classmethod
    def finite_measure(cls, value: float | int | None) -> float | int | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("source numeric metadata must remain finite")
        return value


class HongKongFeatureBinding(BaseModel):
    """Exact provider row/page binding; actual WGS84 rings stay in the original source cache."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_row_id: StrictStr
    source_row: CsdiSourceRow
    artifact: SourceArtifact
    page_index: StrictInt = Field(ge=0)
    feature_index: StrictInt = Field(ge=0)
    feature_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source_crs: Literal[2326]
    spatial_reference: Literal[4326]
    geometry_type: Literal["esriGeometryPolygon"]
    ring_count: StrictInt = Field(gt=0)
    coordinate_records: StrictInt = Field(ge=4)

    @model_validator(mode="after")
    def validate_release_binding(self) -> HongKongFeatureBinding:
        parsed = urlsplit(self.artifact.uri)
        query = parse_qs(parsed.query)
        if (
            self.source_row_id
            != f"{DATASET_ID}/{LAYER_NAME}/{self.source_row.object_id}/{self.source_row.file_ref}"
            or parsed.scheme != "https"
            or parsed.hostname != "portal.csdi.gov.hk"
            or parsed.path != urlsplit(QUERY_URI).path
            or query.get("outSR") != ["4326"]
            or query.get("returnGeometry") != ["true"]
            or query.get("outFields") != ["*"]
            or self.coordinate_records < 4 * self.ring_count
        ):
            raise ValueError(
                "feature binding requires original release identity and provider4326 page"
            )
        return self


class ComponentRelation(BaseModel):
    """A separately evidenced whole/component relationship for one original feature."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    feature_id: StrictInt = Field(gt=0)
    relation: Literal["same_whole", "component_of_whole"]
    evidence: list[SourceEvidence] = Field(min_length=1)


class HongKongWhole(BaseModel):
    """Official whole identity with a verified business-page project ID, never a legal ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    official_list_number: StrictInt = Field(gt=0)
    business_reference: StrictInt = Field(gt=0)
    title_en: StrictStr = Field(min_length=1)
    title_tc: StrictStr = Field(min_length=1)
    business_uri: StrictStr
    business_uri_tc: StrictStr
    directory_area: DirectoryArea
    source_features: list[HongKongFeatureBinding]
    scope_evidence: list[SourceEvidence] = Field(min_length=1)
    scope_relations: list[ComponentRelation]

    @property
    def project_id(self) -> str:
        return f"auth:hk-amo:monuments-{self.business_reference}"

    @model_validator(mode="after")
    def validate_whole(self) -> HongKongWhole:
        for language, uri in (("en", self.business_uri), ("tc", self.business_uri_tc)):
            parsed = urlsplit(uri)
            match = re.fullmatch(
                rf"/{language}/historic-buildings/monuments/{self.directory_area}/"
                r"monuments_([0-9]+)/index\.html",
                parsed.path,
            )
            if (
                parsed.scheme != "https"
                or parsed.hostname != "www.amo.gov.hk"
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or match is None
                or int(match[1]) != self.business_reference
            ):
                raise ValueError(
                    "whole identity must bind the independently checked AMO business page"
                )
        ids = [feature.source_row.object_id for feature in self.source_features]
        relations = [relation.feature_id for relation in self.scope_relations]
        if (
            not self.title_en.strip()
            or not self.title_tc.strip()
            or len(ids) != len(set(ids))
            or len(relations) != len(set(relations))
            or set(ids) != set(relations)
        ):
            raise ValueError(
                "every attached feature needs exactly one reviewed whole/component relation"
            )
        return self


class HongKongDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    whole: HongKongWhole
    disposition: Literal["include", "existing", "component", "hold"]
    target_id: StrictStr | None
    reason: StrictStr = Field(min_length=1)
    evidence: list[SourceEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_target(self) -> HongKongDecision:
        if not self.reason.strip():
            raise ValueError("source decisions require an explicit reason")
        if self.disposition == "hold":
            if self.target_id is not None:
                raise ValueError("held facts cannot gain a public target identity")
        elif not self.target_id:
            raise ValueError("accepted facts require an independently reviewed target identity")
        if self.disposition == "include" and self.target_id != self.whole.project_id:
            raise ValueError(
                "included project identity must preserve the verified business-page identity"
            )
        return self


class HeldFeature(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    feature: HongKongFeatureBinding
    reason: StrictStr = Field(min_length=1)
    evidence: list[SourceEvidence] = Field(min_length=1)


class HongKongRecord(BaseModel):
    """Approved source facts only; deterministic compilation supplies the public Site."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    whole: HongKongWhole
    independent_review: IdentityReview
    evidence: list[SourceEvidence] = Field(min_length=1)
    provenance: dict[str, Any]


class DatasetMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset_id: Literal["devb_wb_rcd_1639040299687_46105"]
    layer_id: Literal[0]
    layer_name: Literal["DM_20260130_150858"]
    source_crs: Literal[2326]
    provider_output_crs: Literal[4326]
    release_date: Literal["2026-01-30"]
    evidence: SourceEvidence

    @model_validator(mode="after")
    def validate_uri(self) -> DatasetMetadata:
        if self.evidence.source.uri != METADATA_URI:
            raise ValueError("dataset metadata must retain its exact original dataset page")
        return self


class RightsReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    csdi_license: Literal["CSDI Portal Terms and Conditions of Use"]
    csdi_terms: SourceEvidence
    amo_rights: SourceEvidence
    reuse_scope: Literal["short_structured_facts_only_no_photos_or_source_prose"]

    @model_validator(mode="after")
    def validate_rights(self) -> RightsReview:
        if (
            self.csdi_terms.source.uri != TERMS_URI
            or self.csdi_terms.source.license not in {None, CSDI_LICENSE}
            or self.amo_rights.source.license in {"CC0", "CC BY 4.0", "CC BY-SA 4.0"}
        ):
            raise ValueError(
                "custom CSDI terms do not grant a CC licence to AMO webpage expression"
            )
        return self


class CountryAssociation(BaseModel):
    """A modern source country-or-area catalogue label, independent of sovereignty or history."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    code: Literal["HK"]
    label: Literal["Hong Kong"]
    region: Literal["asia-pacific"]
    source_code_literal: Literal["HK"]
    source_label_literal: Literal["China, Hong Kong Special Administrative Region"]
    source_m49_cells: list[StrictStr] = Field(
        min_length=15,
        max_length=15,
        description="Original active table cells only; exclude HTML comments.",
    )
    region_role: Literal["project_catalogue_grouping_from_m49_asia_eastern_asia"] = (
        "project_catalogue_grouping_from_m49_asia_eastern_asia"
    )
    evidence: list[SourceEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_labels(self) -> CountryAssociation:
        active_cells = [
            "001",
            "World",
            "142",
            "Asia",
            "030",
            "Eastern Asia",
            "",
            "",
            self.source_label_literal,
            "344",
            "HK",
            "HKG",
            "",
            "",
            "",
        ]
        if (
            self.source_m49_cells != active_cells
            or not any(
                item.source.uri.rstrip("/") == UN_M49_URI
                and item.artifact.sha256 == UN_M49_SHA256
                and self.source_label_literal in item.source.excerpt
                for item in self.evidence
            )
            or not any(
                item.source.uri == METADATA_URI and "Hong Kong" in item.source.excerpt
                for item in self.evidence
            )
        ):
            raise ValueError(
                "HK code needs the frozen M49 row and separate source Hong Kong literal"
            )
        return self


class HongKongSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cohort_version: Literal["hong-kong-monuments-v1"]
    corpus_version: Literal["global-v14"]
    base_count: Literal[2976]
    base_ids_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    candidates_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    handoff_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    independent_report_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    selection: Literal[
        "All independently qualified official whole objects; no fixed addition quota."
    ]
    metadata: DatasetMetadata
    rights: RightsReview
    countries: list[CountryAssociation] = Field(min_length=1, max_length=1)
    source_feature_roster: list[HongKongFeatureBinding] = Field(min_length=1)
    source_artifacts: list[SourceArtifact] = Field(min_length=1)
    decisions: list[HongKongDecision] = Field(min_length=1)
    held_features: list[HeldFeature] = Field(default_factory=list)
    records: list[HongKongRecord]


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def feature_hash(feature: dict[str, Any]) -> str:
    """Use the collector's canonical hash of the complete original feature."""
    return _hash(
        json.dumps(feature, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )


def _require_pins() -> None:
    for pin in (
        CANDIDATES_SHA256,
        HANDOFF_SHA256,
        INDEPENDENT_REVIEW_SHA256,
        SOURCE_ROSTER_SHA256,
        SOURCE_FACTS_SHA256,
        SPEC_SHA256,
        SITES_SHA256,
    ):
        if re.fullmatch(r"[0-9a-f]{64}", pin) is None:
            raise HongKongError(
                "Hong Kong independent source approval and compiled pins are not configured"
            )


def _source_roster(spec: HongKongSpec) -> list[dict[str, Any]]:
    return [
        row.model_dump(mode="json", by_alias=True)
        for row in sorted(spec.source_feature_roster, key=lambda row: row.source_row.object_id)
    ]


def _source_facts(spec: HongKongSpec) -> dict[str, Any]:
    """Bind all independently approved facts without self-referential receipt hash fields."""
    return spec.model_dump(
        mode="json",
        by_alias=True,
        exclude={"candidates_sha256", "handoff_sha256", "independent_report_sha256"},
    )


def _evidence(spec: HongKongSpec) -> list[SourceEvidence]:
    result = [spec.metadata.evidence, spec.rights.csdi_terms, spec.rights.amo_rights]
    result.extend(evidence for country in spec.countries for evidence in country.evidence)
    for decision in spec.decisions:
        result.extend(decision.evidence)
        result.extend(decision.whole.scope_evidence)
        result.extend(
            evidence
            for relation in decision.whole.scope_relations
            for evidence in relation.evidence
        )
    result.extend(evidence for record in spec.records for evidence in record.evidence)
    result.extend(evidence for held in spec.held_features for evidence in held.evidence)
    return result


def _artifacts(spec: HongKongSpec) -> dict[str, SourceArtifact]:
    result: dict[str, SourceArtifact] = {}
    artifacts = [
        *spec.source_artifacts,
        *(row.artifact for row in spec.source_feature_roster),
        *(evidence.artifact for evidence in _evidence(spec)),
    ]
    for artifact in artifacts:
        if artifact.filename in result and result[artifact.filename] != artifact:
            raise HongKongError(
                "one source cache filename has conflicting original source contracts"
            )
        result[artifact.filename] = artifact
    return result


def _validate_spec(spec: HongKongSpec) -> None:
    roster = {row.source_row.object_id: row for row in spec.source_feature_roster}
    if len(roster) != len(spec.source_feature_roster):
        raise HongKongError("original source feature roster contains duplicate provider OIDs")
    references = [decision.whole.business_reference for decision in spec.decisions]
    assigned = [row for decision in spec.decisions for row in decision.whole.source_features]
    assigned.extend(held.feature for held in spec.held_features)
    assigned_ids = [row.source_row.object_id for row in assigned]
    if (
        len(references) != len(set(references))
        or len(assigned_ids) != len(set(assigned_ids))
        or set(assigned_ids) != set(roster)
        or any(row != roster.get(row.source_row.object_id) for row in assigned)
    ):
        raise HongKongError(
            "whole/held decisions must account for every unchanged original feature once"
        )
    records = {record.whole.project_id: record for record in spec.records}
    included = {
        decision.target_id: decision
        for decision in spec.decisions
        if decision.disposition == "include"
    }
    if len(records) != len(spec.records) or set(records) != set(included):
        raise HongKongError("included decisions and approved whole records must match one-to-one")
    for identifier, record in records.items():
        if record.whole != included[identifier].whole:
            raise HongKongError(
                "approved record changed its independently reviewed whole or source rows"
            )
    _artifacts(spec)


def _spec(directory: Path) -> HongKongSpec:
    _require_pins()
    payload = (directory / SPEC_FILE).read_bytes()
    if _hash(payload) != SPEC_SHA256:
        raise HongKongError("Hong Kong review differs from its independent pin")
    spec = HongKongSpec.model_validate_json(payload)
    if (
        spec.candidates_sha256 != CANDIDATES_SHA256
        or spec.handoff_sha256 != HANDOFF_SHA256
        or spec.independent_report_sha256 != INDEPENDENT_REVIEW_SHA256
        or _hash(_bytes(_source_roster(spec))) != SOURCE_ROSTER_SHA256
    ):
        raise HongKongError("Hong Kong candidate/handoff/review/source-roster binding differs")
    if _hash(_bytes(_source_facts(spec))) != SOURCE_FACTS_SHA256:
        raise HongKongError(
            "Hong Kong complete approved source facts differ from their independent pin"
        )
    _validate_spec(spec)
    return spec


def _ordered(spec: HongKongSpec) -> list[HongKongRecord]:
    return sorted(
        spec.records,
        key=lambda record: (
            _hash((COHORT_VERSION + ":" + record.whole.project_id).encode()),
            record.whole.project_id,
        ),
    )


def source_details(whole: HongKongWhole) -> str:
    """Keep original names/address and declaration metadata searchable, without historical prose."""
    facts = [
        f"官方整体名称（繁體中文）：{whole.title_tc}",
        "Source country-or-area association: Hong Kong (HK).",
    ]
    for binding in whole.source_features:
        row = binding.source_row
        values = {
            "NAME": row.name,
            "NAME_TC": row.name_tc,
            "ADDRESS": row.address,
            "ADDRESS_TC": row.address_tc,
            "DISTRICT": row.district,
            "DISTRIC_TC": row.district_tc,
            "FILE_REF": row.file_ref,
            "DEC_YEAR": row.declaration_year,
            "DEC_YE_TC": row.declaration_year_tc,
        }
        label = "来源要素事实（不增加遗址条目数）"
        facts.append(label + "：" + json.dumps(values, ensure_ascii=False, separators=(",", ":")))
    facts.append("DEC_YEAR／DEC_YE_TC为现代法定古蹟宣布年份元数据，不是建造、使用或毁弃年代。")
    return "\n".join(facts)


def compile_hong_kong(spec: HongKongSpec) -> list[Site]:
    """Pure factual projection; source approval is enforced separately by the pinned loader."""
    _validate_spec(spec)
    country = spec.countries[0]
    result: list[Site] = []
    for record in _ordered(spec):
        whole = record.whole
        evidence = [*record.evidence, *whole.scope_evidence, *country.evidence]
        references: list[SourceReference] = []
        for item in evidence:
            if item.source not in references:
                references.append(item.source)
        for binding in whole.source_features:
            reference = SourceReference(
                id=f"hk-csdi:feature:{binding.source_row.object_id}",
                title="Declared Monuments with Images: factual attributes and provider polygons",
                uri=binding.artifact.uri,
                publisher="Antiquities and Monuments Office, Hong Kong",
                license=CSDI_LICENSE,
                revision=LAYER_NAME,
                excerpt="",
            )
            if reference not in references:
                references.append(reference)
        names = [whole.title_tc]
        site = Site(
            id=whole.project_id,
            title=whole.title_en,
            description="",
            description_zh="",
            details=source_details(whole),
            names=names,
            types=["historic-site"],
            periods=[],
            repr_point=None,
            location_precision=None,
            source_uri=whole.business_uri,
            contributors=["Antiquities and Monuments Office, Hong Kong"],
            period_evidence=[],
            source_kind="supplement",
            source_refs=references,
            geography=Geography(
                authority_id="supplement:" + whole.project_id,
                countries=[country.code],
                regions=[country.region],
                source=country.evidence[0].source,
                point_count=0,
                note=(
                    "现代来源目录地区关联；Hong Kong为项目短显示名，HK代码据UN M49原行；"
                    "asia-pacific为依据M49亚洲／东亚的项目资料分组；"
                    "官方业务页项目标识不是法律永久编号；没有来源代表点。"
                ),
            ),
        )
        artifacts = {item.artifact.filename: item.artifact for item in evidence}
        artifacts.update(
            {
                item.artifact.filename: item.artifact
                for relation in whole.scope_relations
                for item in relation.evidence
            }
        )
        artifacts.update(
            {binding.artifact.filename: binding.artifact for binding in whole.source_features}
        )
        SupplementRecord(
            site=site,
            country_label=country.label,
            coordinate=CoordinateEvidence(
                method="unknown",
                point=None,
                source_uri=None,
                note="No source-defined representative point; provider polygons remain separate.",
            ),
            independent_review=record.independent_review,
            source_files=list(artifacts.values()),
            provenance=record.provenance,
        )
        result.append(site)
    return result


def _manifest(spec: HongKongSpec, payload: bytes) -> dict[str, Any]:
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
            "source_facts_sha256": SOURCE_FACTS_SHA256,
            "scope": "Source facts, identity, scope, rights and dedup; chronology unreviewed.",
        },
        "files": {SPEC_FILE: {"sha256": SPEC_SHA256}, SITES_FILE: {"sha256": _hash(payload)}},
        "counts": {
            "base": BASE_COUNT,
            "added": len(records),
            "total": BASE_COUNT + len(records),
            "official_whole_decisions": len(spec.decisions),
            "source_features": len(spec.source_feature_roster),
            "decisions": dict(sorted(Counter(row.disposition for row in spec.decisions).items())),
            "held_features": len(spec.held_features),
            "source_polygon_sites": sum(bool(row.whole.source_features) for row in records),
            "source_polygon_features": sum(len(row.whole.source_features) for row in records),
            "adopted_representative_points": 0,
            "new_historical_phases": 0,
        },
        "countries": [country.model_dump(mode="json") for country in spec.countries],
        "metadata": spec.metadata.model_dump(mode="json"),
        "rights": spec.rights.model_dump(mode="json"),
        "decisions": [row.model_dump(mode="json", by_alias=True) for row in spec.decisions],
        "held_features": [row.model_dump(mode="json", by_alias=True) for row in spec.held_features],
        "records": [
            {
                "id": row.whole.project_id,
                "whole": row.whole.model_dump(mode="json", by_alias=True),
                "identity_review": row.independent_review.model_dump(mode="json"),
                "provenance": row.provenance,
            }
            for row in records
        ],
        "source_artifacts": [
            artifact.model_dump(mode="json") for _, artifact in sorted(_artifacts(spec).items())
        ],
        "range_semantics": (
            "Original public provider polygons; no ancient boundary, excavation extent, "
            "inferred point, historical polity or asserted precise legal extent."
        ),
        "chronology": (
            "Source declaration/publication years remain administrative metadata, "
            "never historical phases."
        ),
        "licenses": (
            "CSDI custom Terms and Conditions apply to the CSDI release. AMO names and short facts "
            "retain their separate webpage rights; no source prose or images are reproduced."
        ),
    }


def rebuild_hong_kong(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Compile externally pinned whole facts offline, without acquiring or converting geometry."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        payload = _bytes([site.model_dump(mode="json") for site in compile_hong_kong(spec)])
        if _hash(payload) != SITES_SHA256:
            raise HongKongError("compiled Hong Kong sites differ from their independent pin")
        manifest = _manifest(spec, payload)
        (directory / SITES_FILE).write_bytes(payload)
        (directory / MANIFEST_FILE).write_bytes(_bytes(manifest))
        return manifest
    except HongKongError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise HongKongError(f"cannot rebuild frozen Hong Kong facts: {error}") from error


def load_hong_kong(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Append qualified whole identities, preserving every original field and source ordering."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        expected = {
            key: value for key, value in spec.model_dump().items() if key.startswith("base_")
        }
        if base_contract(base) != expected:
            raise HongKongError("Hong Kong base differs from the complete unchanged2976 contract")
        base_ids = {site.id for site in base}
        if len(base_ids) != BASE_COUNT or any(
            row.target_id not in base_ids
            for row in spec.decisions
            if row.disposition in {"existing", "component"}
        ):
            raise HongKongError(
                "existing/component target is absent or original base IDs duplicate"
            )
        additions = compile_hong_kong(spec)
        if base_ids & {site.id for site in additions}:
            raise HongKongError("Hong Kong additions duplicate an existing identity")
        payload = (directory / SITES_FILE).read_bytes()
        if (
            payload != _bytes([site.model_dump(mode="json") for site in additions])
            or _hash(payload) != SITES_SHA256
        ):
            raise HongKongError(
                "Hong Kong sites differ from the independently reviewed specification"
            )
        if _bytes(json.loads((directory / MANIFEST_FILE).read_bytes())) != _bytes(
            _manifest(spec, payload)
        ):
            raise HongKongError("Hong Kong manifest differs from its frozen contract")
        return base + additions
    except HongKongError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise HongKongError(f"cannot load frozen Hong Kong facts: {error}") from error


def new_country_labels(data_dir: Path = DATA_DIR) -> MappingProxyType[str, str]:
    try:
        spec = _spec(Path(data_dir))
        return MappingProxyType({country.code: country.label for country in spec.countries})
    except HongKongError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise HongKongError(f"cannot load Hong Kong country-or-area label: {error}") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Verify original bytes plus every row/page/ring receipt, without any networking."""
    try:
        spec = _spec(Path(data_dir))
        root = Path(cache_dir).resolve()
        artifacts = _artifacts(spec)
        pages: dict[str, Any] = {}
        for filename, artifact in artifacts.items():
            path = (root / filename).resolve()
            if not path.is_relative_to(root):
                raise HongKongError(f"source snapshot escapes the cache: {filename}")
            payload = path.read_bytes()
            if _hash(payload) != artifact.sha256:
                raise HongKongError(f"Hong Kong source snapshot differs: {filename}")
            if any(row.artifact.filename == filename for row in spec.source_feature_roster):
                pages[filename] = json.loads(payload)
        seen_positions: set[tuple[str, int]] = set()
        for binding in spec.source_feature_roster:
            page = pages[binding.artifact.filename]
            position = (binding.artifact.filename, binding.feature_index)
            feature = page["features"][binding.feature_index]
            rings = feature["geometry"]["rings"]
            if (
                position in seen_positions
                or page.get("geometryType") != "esriGeometryPolygon"
                or page.get("spatialReference", {}).get("wkid") != 4326
                or page.get("spatialReference", {}).get("latestWkid", 4326) != 4326
                or feature["attributes"]
                != binding.source_row.model_dump(mode="json", by_alias=True)
                or feature_hash(feature) != binding.feature_sha256
                or len(rings) != binding.ring_count
                or sum(len(ring) for ring in rings) != binding.coordinate_records
            ):
                raise HongKongError("original feature/page/provider4326 binding differs")
            seen_positions.add(position)
        if sum(len(page["features"]) for page in pages.values()) != len(seen_positions):
            raise HongKongError(
                "complete cached provider pages contain an unaccounted source feature"
            )
        return len(artifacts)
    except HongKongError:
        raise
    except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
        raise HongKongError(f"cannot verify Hong Kong source snapshots: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile independently reviewed Hong Kong facts offline"
    )
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
            print(json.dumps(rebuild_hong_kong(args.data_dir)["counts"]))
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild and/or --verify-source-cache")
    except HongKongError as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
