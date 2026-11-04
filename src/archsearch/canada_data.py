"""Compile reviewed Canadian designation facts without inferring dates or locations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from archsearch.domain import Site, SourceReference
from archsearch.supplement_data import SourceArtifact, SupplementRecord, base_contract

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "canada-dfhd-v1"
CORPUS_VERSION = "global-v13"
BASE_COUNT = 1999
SOURCE_COUNT = 1014
SPEC_FILE = "canada_review.json"
SITES_FILE = "canada_sites.json"
MANIFEST_FILE = "canada_manifest.json"
SOURCE_RESOURCE_ID = "682d1e12-26dd-4d30-bb40-f04658502bcd"
DESIGNATION_TYPE = "National Historic Site of Canada"
OGL = "Open Government Licence - Canada"
REGION = "europe-north-america"
SELECTION = "Complete frozen DFHD NHS inventory; independently reviewed source decisions."
# Intentionally closed until the final source, scope/dedup and compiled artifacts are pinned.
POOL_SHA256 = "b81c9eab8c8941213664f8d489e4b2a72e1d0bb4975aa02c334fad5556548829"
HANDOFF_SHA256 = "2fe98e5398638d434961a9f3763e0cba1f5622d4289684a680ca532847ea5bab"
SOURCE_CONTRACT_SHA256 = "f6a5a5543aa1ceba17c71eb4a50e5583394bc5821e89ff89aaca2f5dad309530"
FINAL_SOURCE_REVIEW_SHA256 = "fba0902bec6fdaffba4dd85997b50b32d21f24fab95f9a0072be612fb2a25232"
DEDUP_REVIEW_SHA256 = "ca35e13a7d3fc6b796b863e4a0b6c5bdeda9b19d1c314badd67cb86ec52db9de"
POINT_SOURCE_REVIEW_SHA256 = "8a2d065c9bf7a5959050dce12ce52788376dcfeb834df3b14b34dc26df6e1e52"
SCOPE_SOURCE_REVIEW_SHA256 = "ae0f67fa32851b12b694244b6caac2270ad7860589b02670fd8cb338497247d5"
SCOPE_RELATIONS_SHA256 = "e8713f2bed8b12c97c93aa34f445ddf9247ad361724bbaf667763b05321c91ca"
SOURCE_ROSTER_SHA256 = "0eca10ff719a50c6d29ca880237eda8ccb30b494ad6792dba73c359fc7379904"
SPEC_SHA256 = "4cfdd4fb896c2769de3d77daaf481fdb1544fc79d0e6d8db4911d97d8ad8afbc"
SITES_SHA256 = "f0f31d8c14bd1560975da2c7e454befdda3623198916921aa115248056497aaf"
Country = Literal["Canada", "France"]
CountryCode = Literal["CA", "FR"]
Point = tuple[StrictFloat | StrictInt, StrictFloat | StrictInt]
COUNTRY_CODES: dict[str, CountryCode] = {"Canada": "CA", "France": "FR"}
ADMIN_REVIEW_URIS = frozenset(
    {
        "https://www.parks.canada.ca/culture/adpf-dfhd-portal",
        "https://parks.canada.ca/culture/designation/revue-review",
    }
)


class CanadaError(RuntimeError):
    """A source approval, unchanged base or compiled cohort contract differs."""


class DfhdSourceRow(BaseModel):
    """All27 original release fields plus its internal datastore row ID, unchanged."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    datastore_id: StrictInt = Field(alias="_id", gt=0)
    designation_id: StrictStr = Field(
        alias="Directory of Federal Heritage Designations Identifier",
        pattern=r"^[0-9]+$",
    )
    name: StrictStr | None = Field(alias="Designation name")
    other_names: StrictStr | None = Field(alias="Other names")
    designation_type: Literal["National Historic Site of Canada"] = Field(alias="Designation type")
    statute: StrictStr = Field(alias="Designation statute")
    designation_date: StrictStr = Field(alias="Designation date")
    research_report: StrictStr | None = Field(alias="Research report number")
    highlight: StrictStr | None = Field(alias="Highlight")
    description_type: StrictStr | None = Field(alias="Designation description type")
    description: StrictStr | None = Field(alias="Designation description")
    inscription: StrictStr | None = Field(alias="Commemorative inscription")
    inscription_language: StrictStr | None = Field(alias="Language of inscription")
    street_address: StrictStr | None = Field(alias="Street address")
    local_area: StrictStr | None = Field(alias="Local area")
    province_territory: StrictStr = Field(alias="Province or territory", min_length=1)
    country: Country = Field(alias="Country")
    custodian: StrictStr | None = Field(alias="Custodian")
    birth_year: StrictStr | None = Field(alias="Birth year")
    death_year: StrictStr | None = Field(alias="Death year")
    construction_start: StrictStr | None = Field(alias="Construction start date")
    construction_end: StrictStr | None = Field(alias="Construction end date")
    associated_agents: StrictStr | None = Field(
        alias="Associated Persons/Organizations/Architect/Builder"
    )
    railway_station_number: StrictStr | None = Field(alias="Railway Station Number")
    heritage_lighthouse_number: StrictStr | None = Field(alias="Heritage Lighthouse Number")
    fhro_number: StrictStr | None = Field(alias="FHRO Number")
    dfrp_property_number: StrictStr | None = Field(alias="DFRP Property Number")
    cihb_geographic_code: StrictStr | None = Field(alias="CIHB Geographic Code")

    @property
    def country_code(self) -> CountryCode:
        return COUNTRY_CODES[self.country]


class AdministrativeReview(BaseModel):
    """An original administrative notice, never a project import approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_highlight: StrictStr | None
    state: Literal["source_admin_review", "no_source_admin_review_flag"]
    scope: Literal["designation_reasons_or_plaque_review_not_project_approval"]

    @model_validator(mode="after")
    def validate_notice(self) -> AdministrativeReview:
        flagged = "identified for review" in (self.source_highlight or "").casefold()
        if (self.state == "source_admin_review") != flagged:
            raise ValueError("administrative notice must preserve the original Highlight meaning")
        return self


def source_administrative_note(notice: AdministrativeReview) -> str:
    """Keep the original notice visible, independently of project and chronology review."""
    if notice.state != "source_admin_review":
        return ""
    return (
        f"来源行政复核提示（原文）：{notice.source_highlight}\n"
        "项目说明：该提示涉及已有认定的纪念理由或牌文复核，不表示尚未获认定或认定已撤销；"
        "它与本项目资料身份审批及历史断代核验状态相互独立。"
    )


class CountryAssociation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_country: Country
    code: CountryCode
    label: StrictStr
    region: Literal["europe-north-america"]
    source: SourceReference
    artifact: SourceArtifact

    @model_validator(mode="after")
    def validate_association(self) -> CountryAssociation:
        uri = f"https://whc.unesco.org/en/statesparties/{self.code.lower()}/"
        if (
            self.code != COUNTRY_CODES[self.source_country]
            or self.label != self.source_country
            or self.source.uri.rstrip("/") != uri.rstrip("/")
            or self.artifact.uri.rstrip("/") != uri.rstrip("/")
            or not self.source.id.startswith("region:")
            or self.source.excerpt
            != ("Europe and North America, World Heritage Convention Regional Contact")
        ):
            raise ValueError("country/region labels require their own country-specific source")
        return self


class CgnProviderAttributes(BaseModel):
    """Original MapServer attributes for a same-object published reference point."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    object_id: StrictInt = Field(alias="OBJECTID", gt=0)
    cgn_key: StrictStr = Field(alias="CGNDB_ID", pattern=r"^[A-Z]{5}$")
    name: StrictStr = Field(alias="GEONAME")
    language_code: StrictStr = Field(alias="LANG_CODE")
    language: StrictStr = Field(alias="LANGUAGE")
    syllabic: StrictStr | None = Field(alias="SYLLABIC")
    generic: Literal["National Historic Site"] = Field(alias="GENERIC")
    category: StrictStr = Field(alias="CATEGORY")
    concise: Literal["PARK"] = Field(alias="CONCISE")
    feature_id: StrictStr = Field(alias="FEATURE_ID", min_length=1)
    location: StrictStr | None = Field(alias="LOCATION")
    province_territory: StrictStr = Field(alias="PROV_TERR")
    relative_scale: StrictStr | None = Field(alias="REL_SCALE")
    naming_decision: StrictStr | None = Field(alias="DECISION")
    source: StrictStr | None = Field(alias="SOURCE")


class ProviderWikidataIdentityBridge(BaseModel):
    """An exact official-ID/key bridge, not an inferred alternative place name."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    dfhd_id: StrictStr = Field(pattern=r"^[0-9]+$")
    qid: StrictStr = Field(pattern=r"^Q[1-9][0-9]*$")
    revision: StrictInt = Field(gt=0)
    artifact: SourceArtifact
    p2526_statement: dict[str, Any]
    p821_statement: dict[str, Any]

    @model_validator(mode="after")
    def validate_bridge(self) -> ProviderWikidataIdentityBridge:
        entity = urlsplit(self.artifact.uri)
        if (
            entity.scheme != "https"
            or entity.hostname != "www.wikidata.org"
            or entity.path != f"/wiki/Special:EntityData/{self.qid}.json"
            or _claim_value(self.p2526_statement, "P2526") != self.dfhd_id
            or not re.fullmatch(r"[A-Z]{5}", str(_claim_value(self.p821_statement, "P821")))
            or any(
                statement.get("rank") not in {"normal", "preferred"}
                or not _entity_guid(statement.get("id"), self.qid)
                for statement in (self.p2526_statement, self.p821_statement)
            )
        ):
            raise ValueError(
                "provider identity bridge needs exact active original P2526/P821 claims"
            )
        return self


class ProviderPointReceipt(BaseModel):
    """A pinned provider4326 response; native NAD83 positions retain a different role."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["provider_outsr4326"]
    dfhd_id: StrictStr = Field(pattern=r"^[0-9]+$")
    artifact: SourceArtifact
    identity_artifact: SourceArtifact
    provider_attributes: CgnProviderAttributes
    reference_point: Point
    output_crs: Literal[4326]
    map_layer_source_crs: Literal[3978]
    raw_api_position_nad83: Point
    api_geographic_datum: Literal["NAD83"]
    api_geographic_crs: Literal[4269]
    raw_api_accuracy: StrictInt | StrictFloat | None
    accuracy_role: Literal["uninterpreted_source_value_no_precision_claim"]
    official_name_status: Literal["O"]
    generic_code: Literal["538", "539"]
    geometry_role: Literal["provider_geographical_name_reference_point_not_legal_boundary"]
    wikidata_identity_bridge: ProviderWikidataIdentityBridge | None = None

    @model_validator(mode="after")
    def validate_receipt(self) -> ProviderPointReceipt:
        for lon, lat in (self.reference_point, self.raw_api_position_nad83):
            if not all(math.isfinite(v) for v in (lon, lat)) or not (
                -180 <= lon <= 180 and -90 <= lat <= 90
            ):
                raise ValueError("provider reference coordinates require finite lon/lat values")
        if self.dfhd_id in {"52", "66"}:
            raise ValueError("BC raw NAD83 points have no approved provider4326 receipt")
        parsed = urlsplit(self.artifact.uri)
        query = parse_qs(parsed.query)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "maps-cartes.services.geo.ca"
            or not re.fullmatch(
                r"/server_serveur/rest/services/NRCan/canadian_geographical_names_en/MapServer/[0-9]+/query",
                parsed.path,
            )
            or query.get("outSR") != ["4326"]
            or query.get("returnGeometry") != ["true"]
            or query.get("where") != [f"CGNDB_ID='{self.provider_attributes.cgn_key}'"]
        ):
            raise ValueError("point adoption needs its same-key public provider outSR4326 response")
        identity = urlsplit(self.identity_artifact.uri)
        if identity.scheme != "https" or identity.hostname != "geogratis.gc.ca":
            raise ValueError("CGNDB point identity requires its official source artifact")
        if self.wikidata_identity_bridge is not None and (
            self.wikidata_identity_bridge.dfhd_id != self.dfhd_id
            or _claim_value(self.wikidata_identity_bridge.p821_statement, "P821")
            != self.provider_attributes.cgn_key
        ):
            raise ValueError("provider bridge must match this exact DFHD ID and CGNDB key")
        return self


TEMPORAL_QUALIFIERS = frozenset({"P580", "P582", "P585", "P1319", "P1326"})


def _claim_value(statement: dict[str, Any], property_id: str) -> Any:
    snak = statement.get("mainsnak", {})
    if (
        not isinstance(snak, dict)
        or snak.get("property") != property_id
        or snak.get("snaktype") != "value"
    ):
        raise ValueError("selected Wikidata statement needs its original value snak")
    data = snak.get("datavalue")
    datatype, value_type = (
        ("external-id", "string")
        if property_id in {"P2526", "P821"}
        else ("globe-coordinate", "globecoordinate")
    )
    if (
        not isinstance(data, dict)
        or data.get("type") != value_type
        or snak.get("datatype") != datatype
    ):
        raise ValueError("Wikidata original snak/datavalue types differ from their property")
    return data.get("value")


def _earth_value(statement: dict[str, Any]) -> dict[str, Any] | None:
    if statement.get("rank") not in {"normal", "preferred"}:
        return None
    value = _claim_value(statement, "P625")
    if not isinstance(value, dict) or value.get("globe") not in {
        "http://www.wikidata.org/entity/Q2",
        "https://www.wikidata.org/entity/Q2",
    }:
        return None
    lon, lat, precision = value.get("longitude"), value.get("latitude"), value.get("precision")
    if (
        isinstance(lon, bool)
        or isinstance(lat, bool)
        or not isinstance(lon, (float, int))
        or not isinstance(lat, (float, int))
    ):
        raise ValueError("active Earth coordinate statements require numeric original coordinates")
    if not all(math.isfinite(v) for v in (lon, lat)) or not (
        -180 <= lon <= 180 and -90 <= lat <= 90
    ):
        raise ValueError("active Earth coordinate statements require valid original coordinates")
    if precision is not None and (
        isinstance(precision, bool)
        or not isinstance(precision, (float, int))
        or not math.isfinite(precision)
    ):
        raise ValueError("original Wikidata angular precision is invalid, not metre accuracy")
    return value


def _entity_guid(identifier: Any, qid: str) -> bool:
    if not isinstance(identifier, str):
        return False
    prefix, separator, suffix = identifier.partition("$")
    return bool(separator and suffix and prefix.casefold() == qid.casefold())


class WikidataSelectionEvidence(BaseModel):
    """A reviewed public source tied to a reference on the selected original claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    reference_hash: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")
    source: SourceReference
    artifact: SourceArtifact

    @model_validator(mode="after")
    def validate_source(self) -> WikidataSelectionEvidence:
        if self.source.uri != self.artifact.uri:
            raise ValueError("selection source and its pinned snapshot must have the same URI")
        return self


class WikidataPointReceipt(BaseModel):
    """An identity bridge and original Earth claim selected by the stated rank rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["wikidata_earth"]
    dfhd_id: StrictStr = Field(pattern=r"^[0-9]+$")
    qid: StrictStr = Field(pattern=r"^Q[1-9][0-9]*$")
    revision: StrictInt = Field(gt=0)
    artifact: SourceArtifact
    identity_artifact: SourceArtifact
    p2526_statement: dict[str, Any]
    p625_statements: list[dict[str, Any]] = Field(min_length=1)
    selected_statement_id: StrictStr
    selection_rule: Literal[
        "single_active_preferred_earth",
        "single_normal_earth",
        "independently_reviewed_source_reference",
    ]
    selection_evidence: list[WikidataSelectionEvidence] = Field(default_factory=list)
    adoption_reason: StrictStr = Field(min_length=1)
    reference_point: Point
    precision_role: Literal["original_angular_precision_not_metres"]
    precision_status: Literal[
        "valid_original_angular_precision",
        "source_precision_missing",
        "negative_source_precision_not_adopted",
    ]

    @model_validator(mode="after")
    def validate_receipt(self) -> WikidataPointReceipt:
        entity = urlsplit(self.artifact.uri)
        if (
            entity.scheme != "https"
            or entity.hostname != "www.wikidata.org"
            or entity.path != f"/wiki/Special:EntityData/{self.qid}.json"
            or self.p2526_statement.get("rank") not in {"normal", "preferred"}
            or _claim_value(self.p2526_statement, "P2526") != self.dfhd_id
            or not _entity_guid(self.p2526_statement.get("id"), self.qid)
            or not self.adoption_reason.strip()
        ):
            raise ValueError("Wikidata receipt needs the exact active P2526 ID and entity snapshot")
        identities = [s.get("id") for s in self.p625_statements]
        if any(not _entity_guid(identifier, self.qid) for identifier in identities) or len(
            {
                identifier.partition("$")[2]
                for identifier in identities
                if isinstance(identifier, str)
            }
        ) != len(identities):
            raise ValueError("full P625 statements require unique original entity GUIDs")
        active = [
            (s, value) for s in self.p625_statements if (value := _earth_value(s)) is not None
        ]
        if not active or any(
            TEMPORAL_QUALIFIERS.intersection(s.get("qualifiers", {})) for s, _ in active
        ):
            raise ValueError("Earth coordinates with temporal ambiguity require separate review")
        preferred = [(s, v) for s, v in active if s["rank"] == "preferred"]
        if self.selection_rule == "independently_reviewed_source_reference":
            selected = [(s, v) for s, v in active if s["id"] == self.selected_statement_id]
            if preferred or len(active) < 2 or len(selected) != 1 or not self.selection_evidence:
                raise ValueError("source-reference selection needs multiple normal Earth claims")
            references = {
                ref.get("hash") for ref in selected[0][0].get("references", [])
                if isinstance(ref, dict) and isinstance(ref.get("hash"), str)
            }
            if any(e.reference_hash not in references for e in self.selection_evidence):
                raise ValueError("selection evidence must belong to the selected original claim")
        else:
            selected = preferred or active
            rule = "single_active_preferred_earth" if preferred else "single_normal_earth"
            if (
                len(selected) != 1
                or selected[0][0]["id"] != self.selected_statement_id
                or self.selection_rule != rule
                or self.selection_evidence
            ):
                raise ValueError(
                    "Wikidata coordinate selection requires one original eligible statement"
                )
        value = selected[0][1]
        if self.reference_point != (value["longitude"], value["latitude"]):
            raise ValueError("Wikidata point must preserve the selected original Earth value")
        precision = value.get("precision")
        status = (
            "source_precision_missing"
            if precision is None
            else "negative_source_precision_not_adopted"
            if precision < 0
            else "valid_original_angular_precision"
        )
        if self.precision_status != status:
            raise ValueError("Wikidata precision status must describe the selected original value")
        return self

    @property
    def selected_statement(self) -> dict[str, Any]:
        return next(s for s in self.p625_statements if s["id"] == self.selected_statement_id)


def source_wikidata_precision_note(receipt: WikidataPointReceipt) -> str:
    """Disclose an unusable original precision without changing its coordinate value."""
    if receipt.precision_status != "negative_source_precision_not_adopted":
        return ""
    precision = _claim_value(receipt.selected_statement, "P625")["precision"]
    return (
        f"Wikidata 原始角度精度为 {precision}，该负值未采用，项目精度字段留空；"
        "经纬度保留所选原始声明，不表示米级定位精度。"
    )


def source_provider_identity_note(bridge: ProviderWikidataIdentityBridge) -> str:
    """Keep a reviewed cross-name official-ID bridge visible without generating aliases."""
    key = _claim_value(bridge.p821_statement, "P821")
    return (
        f"坐标身份关联：DFHD {bridge.dfhd_id} 与 CGNDB {key} 由 Wikidata {bridge.qid} "
        "原始 P2526／P821 声明关联；官方名称分别保留，不生成别名或精确遗址范围。"
    )


PointReceipt = Annotated[
    ProviderPointReceipt | WikidataPointReceipt,
    Field(discriminator="kind"),
]


def _aliases(row: DfhdSourceRow) -> list[str]:
    return list(
        dict.fromkeys(name.strip() for name in (row.other_names or "").split("|") if name.strip())
    )


def _normalised_name(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", value).casefold()))


def _validate_point_identity(row: DfhdSourceRow, receipt: PointReceipt) -> None:
    if isinstance(receipt, WikidataPointReceipt):
        if receipt.dfhd_id != row.designation_id:
            raise ValueError("Wikidata external ID must match the exact original designation")
        return
    names = [row.name or "", *_aliases(row)]
    suffix = _normalised_name(DESIGNATION_TYPE)
    expected = {_normalised_name(name).removesuffix(suffix) + suffix for name in names if name}
    if (
        receipt.dfhd_id != row.designation_id
        or row.country != "Canada"
        or receipt.provider_attributes.province_territory != row.province_territory
        or (
            _normalised_name(receipt.provider_attributes.name) not in expected
            and receipt.wikidata_identity_bridge is None
        )
    ):
        raise ValueError("CGNDB receipt must identify the same cultural object and source province")


class CanadaDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_row: DfhdSourceRow
    disposition: Literal["include", "existing", "component", "hold"]
    target_id: StrictStr | None
    reason: StrictStr = Field(min_length=1)
    evidence: list[SourceReference] = Field(min_length=1)
    source_files: list[SourceArtifact] = Field(min_length=1)
    point_receipt: PointReceipt | None

    @model_validator(mode="after")
    def validate_decision(self) -> CanadaDecision:
        if not self.reason.strip() or (self.disposition == "hold") != (self.target_id is None):
            raise ValueError(
                "hold decisions have no target; accepted decisions need a target/reason"
            )
        if self.target_id is not None and not self.target_id.strip():
            raise ValueError("accepted decision target cannot be blank")
        if self.point_receipt:
            _validate_point_identity(self.source_row, self.point_receipt)
        return self


def _qualification_uri(uri: str, identifier: str) -> bool:
    parsed = urlsplit(uri)
    query = parse_qs(parsed.query)
    try:
        filters = json.loads(query.get("filters", [""])[0])
    except (ValueError, TypeError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "open.canada.ca"
        and parsed.path == "/data/api/3/action/datastore_search"
        and query.get("resource_id") == [SOURCE_RESOURCE_ID]
        and filters == {"Directory of Federal Heritage Designations Identifier": identifier}
        and query.get("limit") == ["1"]
    )


def source_details(row: DfhdSourceRow) -> str:
    """Expose only literal source country/province facts in the new search documents."""
    return (
        f"Source country association: {row.country} ({row.country_code}). "
        f"Source province or territory: {row.province_territory}."
    )


class CanadaRecord(SupplementRecord):
    source_row: DfhdSourceRow
    title_source: Literal["designation_name", "first_other_name"]
    administrative_review: AdministrativeReview
    point_receipt: PointReceipt | None

    @model_validator(mode="after")
    def validate_source_projection(self) -> CanadaRecord:
        row, site = self.source_row, self.site
        if row.name is None:
            alternatives = _aliases(row)
            if not alternatives or self.title_source != "first_other_name":
                raise ValueError(
                    "a missing primary name requires its explicit original alias source"
                )
            title = alternatives[0]
        else:
            if self.title_source != "designation_name":
                raise ValueError("a supplied original primary name must remain the title source")
            title = row.name
        if (
            site.id != "auth:ca-dfhd:" + row.designation_id
            or site.title != title
            or site.names != [name for name in _aliases(row) if name != title]
            or site.description != (row.description or "")
            or site.description_zh
            or site.location_precision is not None
            or self.country_label != row.country
            or site.details != source_details(row)
            or site.geography is None
            or site.geography.countries != [row.country_code]
            or site.geography.regions != [REGION]
            or site.geography.source not in site.source_refs
        ):
            raise ValueError(
                "Canadian source text, title choice and literal geography must be retained"
            )
        qualifiers = [ref for ref in site.source_refs if ref.id.startswith("qualification:")]
        if (
            len(qualifiers) != 1
            or qualifiers[0].excerpt != row.designation_type
            or qualifiers[0].license != OGL
            or not _qualification_uri(qualifiers[0].uri, row.designation_id)
            or site.source_uri != qualifiers[0].uri
        ):
            raise ValueError("qualification must quote the original NHS type, never Highlight")
        if self.administrative_review.source_highlight != row.highlight:
            raise ValueError("administrative notice must retain the complete original Highlight")
        if self.administrative_review.state == "source_admin_review":
            notes = [
                ref
                for ref in site.source_refs
                if ref.id.startswith("administrative:") and ref.uri.rstrip("/") in ADMIN_REVIEW_URIS
            ]
            if (
                source_administrative_note(self.administrative_review) not in site.geography.note
                or not notes
                or not any(a.uri == ref.uri for a in self.source_files for ref in notes)
            ):
                raise ValueError(
                    "official administrative review must remain visible with its FAQ source"
                )
        raw = row.model_dump(mode="json", by_alias=True)
        receipt = (
            self.point_receipt.model_dump(mode="json", by_alias=True)
            if self.point_receipt
            else None
        )
        if (
            self.provenance.get("source_record") != raw
            or self.provenance.get("point_receipt") != receipt
        ):
            raise ValueError("provenance must retain all source fields and the full point receipt")
        if self.point_receipt is None:
            if self.coordinate.method != "unknown" or any(
                value is not None
                for value in (
                    self.coordinate.source_uri,
                    self.coordinate.statement_id,
                    self.coordinate.globe,
                    self.coordinate.precision,
                    self.coordinate.rank,
                )
            ):
                raise ValueError(
                    "without an approved receipt the representative point remains absent"
                )
        else:
            _validate_point_identity(row, self.point_receipt)
            if (
                self.coordinate.point != self.point_receipt.reference_point
                or self.coordinate.source_uri != self.point_receipt.artifact.uri
                or self.point_receipt.artifact not in self.source_files
                or self.point_receipt.identity_artifact not in self.source_files
            ):
                raise ValueError(
                    "adopted point must match its complete independently reviewed receipt"
                )
            if isinstance(self.point_receipt, ProviderPointReceipt):
                bridge = self.point_receipt.wikidata_identity_bridge
                if bridge is not None and (
                    bridge.artifact not in self.source_files
                    or not any(ref.uri == bridge.artifact.uri and ref.license == "CC0-1.0"
                               for ref in site.source_refs)
                    or source_provider_identity_note(bridge) not in self.coordinate.note
                    or source_provider_identity_note(bridge) not in site.geography.note
                ):
                    raise ValueError("provider identity bridge must remain public and pinned")
                if (
                    self.coordinate.method != "authority"
                    or any(
                        value is not None
                        for value in (
                            self.coordinate.statement_id,
                            self.coordinate.globe,
                            self.coordinate.precision,
                            self.coordinate.rank,
                        )
                    )
                    or not any(
                        ref.uri == self.coordinate.source_uri and ref.license == OGL
                        for ref in site.source_refs
                    )
                ):
                    raise ValueError(
                        "raw provider accuracy cannot become precision or Wikidata fields"
                    )
            else:
                if any(
                    evidence.artifact not in self.source_files
                    or evidence.source not in site.source_refs
                    for evidence in self.point_receipt.selection_evidence
                ):
                    raise ValueError("reviewed selection sources must remain public and pinned")
                statement = self.point_receipt.selected_statement
                value = _claim_value(statement, "P625")
                precision = value.get("precision")
                expected_precision = precision if precision is None or precision >= 0 else None
                precision_note = source_wikidata_precision_note(self.point_receipt)
                if (
                    self.coordinate.method != "wikidata"
                    or self.coordinate.statement_id != statement["id"]
                    or self.coordinate.globe != value["globe"]
                    or self.coordinate.rank != statement["rank"]
                    or self.coordinate.precision != expected_precision
                    or not any(
                        ref.uri == self.coordinate.source_uri and ref.license == "CC0-1.0"
                        for ref in site.source_refs
                    )
                ):
                    raise ValueError(
                        "Wikidata coordinate metadata must preserve its original Earth claim"
                    )
                if precision_note and (
                    precision_note not in self.coordinate.note
                    or precision_note not in site.geography.note
                ):
                    raise ValueError("unadopted negative precision must remain publicly disclosed")
        return self


class CanadaScopeEvidence(BaseModel):
    """Literal government fields supporting a reviewed relationship between two records."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    dfhd_id: StrictStr = Field(pattern=r"^[0-9]+$")
    field: Literal["Designation description"]
    field_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source_page_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source_uri: StrictStr
    normalized_excerpt: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_excerpt(self) -> CanadaScopeEvidence:
        if self.normalized_excerpt != " ".join(self.normalized_excerpt.split()):
            raise ValueError("scope evidence must preserve its normalized literal excerpt")
        return self


class CanadaScopeRelation(BaseModel):
    """A source-reviewed edge; no transitive, geometric or political inference."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_dfhd_id: StrictStr = Field(pattern=r"^[0-9]+$")
    target_dfhd_id: StrictStr = Field(pattern=r"^[0-9]+$")
    source_record_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    target_record_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal[
        "contains", "within", "same_site_distinct_layer", "partial_overlap",
        "co_located_distinct_resources",
    ]
    note: StrictStr = Field(min_length=1)
    evidence: list[CanadaScopeEvidence] = Field(min_length=2)
    source_files: list[SourceArtifact] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_endpoints(self) -> CanadaScopeRelation:
        if self.source_dfhd_id == self.target_dfhd_id or not self.note.strip():
            raise ValueError("scope relationships require distinct endpoints and a literal note")
        if {e.dfhd_id for e in self.evidence} != {
            self.source_dfhd_id, self.target_dfhd_id,
        }:
            raise ValueError("scope evidence must bind both original endpoint records")
        return self


def source_scope_note(relation: CanadaScopeRelation, peer_title: str) -> str:
    """Expose the same reviewed relationship on incoming and outgoing new records."""
    source, target = f"DFHD {relation.source_dfhd_id}", f"DFHD {relation.target_dfhd_id}"
    symmetric_labels = {
        "same_site_distinct_layer": "同址不同历史层",
        "partial_overlap": "部分重叠",
        "co_located_distinct_resources": "同处一地但文化资源不同",
    }
    if relation.kind == "contains":
        relationship = f"{source} 包含 {target}"
    elif relation.kind == "within":
        relationship = f"{source} 位于 {target} 的来源对象范围内"
    else:
        relationship = f"{source} 与 {target} {symmetric_labels[relation.kind]}"
    return f"来源范围关系：{relationship}；关联资料：{peer_title}。{relation.note}"


class CanadaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cohort_version: Literal["canada-dfhd-v1"]
    corpus_version: Literal["global-v13"]
    base_count: Literal[1999]
    base_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pool_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    handoff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_contract_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_source_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dedup_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    point_review_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_scope_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_relations: list[CanadaScopeRelation]
    selection: Literal[
        "Complete frozen DFHD NHS inventory; independently reviewed source decisions."
    ]
    countries: list[CountryAssociation] = Field(min_length=1)
    decisions: list[CanadaDecision] = Field(min_length=SOURCE_COUNT, max_length=SOURCE_COUNT)
    records: list[CanadaRecord]


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_pins() -> None:
    for pin in (
        POOL_SHA256,
        HANDOFF_SHA256,
        SOURCE_CONTRACT_SHA256,
        FINAL_SOURCE_REVIEW_SHA256,
        DEDUP_REVIEW_SHA256,
        POINT_SOURCE_REVIEW_SHA256,
        SCOPE_SOURCE_REVIEW_SHA256,
        SCOPE_RELATIONS_SHA256,
        SOURCE_ROSTER_SHA256,
        SPEC_SHA256,
        SITES_SHA256,
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", pin):
            raise CanadaError("Canadian independent approval and compiled pins are not configured")


def _source_roster(spec: CanadaSpec) -> list[dict[str, Any]]:
    """Bind source facts and independently approved scope/targets in the external pin."""
    return [
        {
            "dfhd_id": row.source_row.designation_id,
            **row.model_dump(mode="json", by_alias=True),
        }
        for row in sorted(
            spec.decisions,
            key=lambda row: (int(row.source_row.designation_id), row.source_row.designation_id),
        )
    ]


def _source_row_hash(row: DfhdSourceRow) -> str:
    payload = json.dumps(
        row.model_dump(mode="json", by_alias=True),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    return _hash(payload)


def _validate_scope_relations(spec: CanadaSpec) -> None:
    relationships = [r.model_dump(mode="json") for r in spec.scope_relations]
    if _hash(_bytes(relationships)) != SCOPE_RELATIONS_SHA256:
        raise CanadaError("Canadian scope relationships differ from their external pin")
    decisions = {row.source_row.designation_id: row for row in spec.decisions}
    keys: set[tuple[str, str, str]] = set()
    for relation in spec.scope_relations:
        key = (relation.source_dfhd_id, relation.target_dfhd_id, relation.kind)
        if key in keys or any(identifier not in decisions for identifier in key[:2]):
            raise CanadaError("scope relationships need unique reviewed edges and known endpoints")
        keys.add(key)
        for identifier, expected in (
            (relation.source_dfhd_id, relation.source_record_sha256),
            (relation.target_dfhd_id, relation.target_record_sha256),
        ):
            if _source_row_hash(decisions[identifier].source_row) != expected:
                raise CanadaError("scope relationship endpoint differs from its original row")
        for evidence in relation.evidence:
            decision = decisions[evidence.dfhd_id]
            description = decision.source_row.description or ""
            if (
                evidence.source_record_sha256 != _source_row_hash(decision.source_row)
                or evidence.field_sha256 != _hash(description.encode())
                or evidence.normalized_excerpt not in " ".join(description.split())
                or not _qualification_uri(evidence.source_uri, evidence.dfhd_id)
                or not any(
                    artifact.sha256 == evidence.source_page_sha256
                    and artifact in decision.source_files
                    for artifact in relation.source_files
                )
            ):
                raise CanadaError("scope relationship evidence differs from original source fields")
    for record in spec.records:
        identifier = record.source_row.designation_id
        related = [r for r in spec.scope_relations
                   if identifier in {r.source_dfhd_id, r.target_dfhd_id}]
        if record.provenance.get("scope_relations") != [
            r.model_dump(mode="json") for r in related
        ]:
            raise CanadaError("record provenance must retain every incoming and outgoing relation")
        assert record.site.geography is not None
        for relation in related:
            peer_id = (relation.target_dfhd_id if identifier == relation.source_dfhd_id
                       else relation.source_dfhd_id)
            peer = decisions[peer_id].source_row
            peer_title = peer.name if peer.name is not None else _aliases(peer)[0]
            if source_scope_note(relation, peer_title) not in record.site.geography.note:
                raise CanadaError("every incoming and outgoing relation must remain public")


def _artifacts(spec: CanadaSpec) -> dict[str, SourceArtifact]:
    result: dict[str, SourceArtifact] = {}
    country_artifacts = [source.artifact for source in spec.countries]
    for artifact in country_artifacts:
        if artifact.filename in result and result[artifact.filename] != artifact:
            raise CanadaError(
                "country snapshots cannot reuse a filename with conflicting contracts"
            )
        result[artifact.filename] = artifact
    rows: list[CanadaDecision | CanadaRecord] = [*spec.decisions, *spec.records]
    for row in rows:
        artifacts = list(row.source_files)
        if row.point_receipt:
            artifacts.extend([row.point_receipt.artifact, row.point_receipt.identity_artifact])
            if isinstance(row.point_receipt, WikidataPointReceipt):
                artifacts.extend(e.artifact for e in row.point_receipt.selection_evidence)
            elif row.point_receipt.wikidata_identity_bridge is not None:
                artifacts.append(row.point_receipt.wikidata_identity_bridge.artifact)
        for artifact in artifacts:
            if artifact.filename in result and result[artifact.filename] != artifact:
                raise CanadaError("one Canadian snapshot filename has conflicting source contracts")
            result[artifact.filename] = artifact
    for relation in spec.scope_relations:
        for artifact in relation.source_files:
            if artifact.filename in result and result[artifact.filename] != artifact:
                raise CanadaError("scope snapshots cannot reuse a conflicting source filename")
            result[artifact.filename] = artifact
    return result


def _spec(directory: Path) -> CanadaSpec:
    _require_pins()
    payload = (directory / SPEC_FILE).read_bytes()
    if _hash(payload) != SPEC_SHA256:
        raise CanadaError("Canadian review differs from its independent pin")
    spec = CanadaSpec.model_validate_json(payload)
    if (
        spec.pool_sha256 != POOL_SHA256
        or spec.handoff_sha256 != HANDOFF_SHA256
        or spec.source_contract_report_sha256 != SOURCE_CONTRACT_SHA256
        or spec.final_source_report_sha256 != FINAL_SOURCE_REVIEW_SHA256
        or spec.dedup_report_sha256 != DEDUP_REVIEW_SHA256
        or spec.point_review_report_sha256 != POINT_SOURCE_REVIEW_SHA256
        or spec.source_scope_report_sha256 != SCOPE_SOURCE_REVIEW_SHA256
    ):
        raise CanadaError("Canadian pool/handoff/source/dedup review binding differs")
    ids = [row.source_row.designation_id for row in spec.decisions]
    datastore_ids = [row.source_row.datastore_id for row in spec.decisions]
    if len(ids) != len(set(ids)) or len(datastore_ids) != len(set(datastore_ids)):
        raise CanadaError("Canadian complete decisions duplicate a designation or datastore row")
    if _hash(_bytes(_source_roster(spec))) != SOURCE_ROSTER_SHA256:
        raise CanadaError(
            "Canadian source rows or technical receipts differ from their external pin"
        )
    _validate_scope_relations(spec)
    associations = {row.source_country: row for row in spec.countries}
    if len(associations) != len(spec.countries) or set(associations) != {
        row.source_row.country for row in spec.decisions
    }:
        raise CanadaError("country associations must preserve the complete source-country roster")
    records = {row.site.id: row for row in spec.records}
    included = [row for row in spec.decisions if row.disposition == "include"]
    targets = [row.target_id for row in included]
    if (
        len(records) != len(spec.records)
        or len(targets) != len(set(targets))
        or set(targets) != set(records)
    ):
        raise CanadaError("Canadian include decisions and records must match one-to-one")
    for decision in included:
        if decision.target_id != "auth:ca-dfhd:" + decision.source_row.designation_id:
            raise CanadaError("Canadian include target must retain its original canonical DFHD ID")
        assert decision.target_id is not None
        record = records[decision.target_id]
        if (
            record.source_row != decision.source_row
            or record.point_receipt != decision.point_receipt
        ):
            raise CanadaError(
                "Canadian record differs from its reviewed source row or point receipt"
            )
        association = associations[record.source_row.country]
        if not any(ref == association.source for ref in record.site.source_refs):
            raise CanadaError(
                "Canadian record must retain its own country-specific regional source"
            )
    _artifacts(spec)
    return spec


def _ordered(spec: CanadaSpec) -> list[CanadaRecord]:
    return sorted(
        spec.records,
        key=lambda row: (
            _hash((COHORT_VERSION + ":" + row.site.id).encode()),
            row.site.id,
        ),
    )


def _manifest(spec: CanadaSpec, payload: bytes) -> dict[str, Any]:
    decisions = sorted(
        spec.decisions,
        key=lambda row: (int(row.source_row.designation_id), row.source_row.designation_id),
    )
    records = _ordered(spec)
    return {
        "schema_version": 1,
        "cohort_version": COHORT_VERSION,
        "corpus_version": CORPUS_VERSION,
        "base": {key: value for key, value in spec.model_dump().items() if key.startswith("base_")},
        "selection": spec.selection,
        "independent_source_review": {
            "pool_sha256": spec.pool_sha256,
            "handoff_sha256": spec.handoff_sha256,
            "source_contract_report_sha256": spec.source_contract_report_sha256,
            "final_source_report_sha256": spec.final_source_report_sha256,
            "dedup_report_sha256": spec.dedup_report_sha256,
            "point_review_report_sha256": spec.point_review_report_sha256,
            "source_scope_report_sha256": spec.source_scope_report_sha256,
            "scope_relations_sha256": SCOPE_RELATIONS_SHA256,
            "source_roster_sha256": SOURCE_ROSTER_SHA256,
            "scope": "Independent source/scope/dedup review; not expert or chronology approval.",
        },
        "files": {SPEC_FILE: {"sha256": SPEC_SHA256}, SITES_FILE: {"sha256": _hash(payload)}},
        "counts": {
            "base": BASE_COUNT,
            "source_designations": len(decisions),
            "added": len(records),
            "total": BASE_COUNT + len(records),
            "decisions": dict(sorted(Counter(row.disposition for row in decisions).items())),
            "adopted_reference_points": sum(row.site.repr_point is not None for row in records),
            "provider_reference_points": sum(
                isinstance(row.point_receipt, ProviderPointReceipt) for row in records
            ),
            "wikidata_reference_points": sum(
                isinstance(row.point_receipt, WikidataPointReceipt) for row in records
            ),
            "no_adopted_representative": sum(row.site.repr_point is None for row in records),
            "source_admin_review_notices": sum(
                "identified for review" in (row.source_row.highlight or "").casefold()
                for row in decisions
            ),
            "scope_relations": len(spec.scope_relations),
        },
        "countries": [
            row.model_dump(mode="json") for row in sorted(spec.countries, key=lambda row: row.code)
        ],
        "decisions": [row.model_dump(mode="json", by_alias=True) for row in decisions],
        "catalogue_associations": [
            {
                "dfhd_id": row.source_row.designation_id,
                "site_id": row.target_id,
                "disposition": row.disposition,
                "country": row.source_row.country,
                "province_territory": row.source_row.province_territory,
                "meaning": "Reviewed relationship only; original1999 Site fields remain unchanged.",
            }
            for row in decisions
            if row.disposition in {"existing", "component"}
        ],
        "scope_relations": [r.model_dump(mode="json") for r in spec.scope_relations],
        "records": [
            {
                "id": row.site.id,
                "source_row": row.source_row.model_dump(mode="json", by_alias=True),
                "title_source": row.title_source,
                "administrative_review": row.administrative_review.model_dump(mode="json"),
                "coordinate": row.coordinate.model_dump(mode="json"),
                "point_receipt": (
                    row.point_receipt.model_dump(mode="json", by_alias=True)
                    if row.point_receipt
                    else None
                ),
                "identity_review": row.independent_review.model_dump(mode="json"),
                "source_files": [artifact.model_dump() for artifact in row.source_files],
                "provenance": row.provenance,
            }
            for row in records
        ],
        "administrative_review_semantics": "Original Highlight designation/plaque-reasons review "
        "is not project approval, cultural affirmation, delisting or automatic exclusion.",
        "chronology": "No source date is promoted into a historical phase.",
        "location_semantics": "Only independently reviewed point receipts are adopted. "
        "Raw API position is NAD83/4269; MapServer source3978 is a projected layer; do not confuse "
        "their coordinate roles. Raw accuracy100 is uninterpreted and precision remainsNone. "
        "CGNDB named-feature MultiPoint/MultiPolygon is not a published legal registered range. "
        "Wikidata points retain exact P2526 identity and original Earth GUID/rank; "
        "a sole preferred statement may outrank normal statements, which remain in the receipt. "
        "Multiple normal claims need independently reviewed evidence from a reference on the "
        "selected original claim. A provider cross-name bridge requires exact original P2526/P821 "
        "identifiers and the same source province; no alias is generated. "
        "Valid original "
        "angular precision is retained; a negative original value is preserved only in the raw "
        "statement and publicly disclosed, with the adopted precision field left empty, "
        "without replacing the original government text or source country.",
        "licenses": "Released DFHD fields and referenced CGNDB data retain OGL-Canada; "
        "Wikidata statements retain CC0-1.0. "
        "This grant is not extended to unrelated webpages, images, finder points or third parties.",
    }


def rebuild_canada(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Compile pinned approved facts offline without fetching or transforming geometry."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        payload = _bytes([row.site.model_dump(mode="json") for row in _ordered(spec)])
        if _hash(payload) != SITES_SHA256:
            raise CanadaError("compiled Canadian sites differ from their independent pin")
        manifest = _manifest(spec, payload)
        (directory / SITES_FILE).write_bytes(payload)
        (directory / MANIFEST_FILE).write_bytes(_bytes(manifest))
        return manifest
    except CanadaError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise CanadaError(f"cannot rebuild the frozen Canadian supplement: {error}") from error


def load_canada(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Append approved records, preserving every original base object and source field."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        if base_contract(base) != {
            "base_count": spec.base_count,
            "base_ids_sha256": spec.base_ids_sha256,
            "base_sites_sha256": spec.base_sites_sha256,
        }:
            raise CanadaError("Canadian base differs from the complete unchanged1999 contract")
        base_ids = {site.id for site in base}
        if len(base_ids) != BASE_COUNT or any(
            row.target_id not in base_ids
            for row in spec.decisions
            if row.disposition in {"existing", "component"}
        ):
            raise CanadaError("Canadian existing/component target is absent or base IDs duplicate")
        additions = [row.site for row in _ordered(spec)]
        if base_ids & {site.id for site in additions}:
            raise CanadaError("Canadian additions duplicate an original identity")
        payload = (directory / SITES_FILE).read_bytes()
        if (
            payload != _bytes([site.model_dump(mode="json") for site in additions])
            or _hash(payload) != SITES_SHA256
        ):
            raise CanadaError("Canadian sites differ from the independently reviewed facts")
        if _bytes(json.loads((directory / MANIFEST_FILE).read_bytes())) != _bytes(
            _manifest(spec, payload)
        ):
            raise CanadaError("Canadian manifest differs from its frozen source contract")
        return base + additions
    except CanadaError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise CanadaError(f"cannot load the frozen Canadian supplement: {error}") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Check optional raw evidence hashes without fetching or executing source files."""
    try:
        spec = _spec(Path(data_dir))
        root = Path(cache_dir).resolve()
        artifacts = _artifacts(spec)
        for filename, artifact in artifacts.items():
            path = (root / filename).resolve()
            if not path.is_relative_to(root) or _hash(path.read_bytes()) != artifact.sha256:
                raise CanadaError(f"Canadian source snapshot differs: {filename}")
        return len(artifacts)
    except CanadaError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise CanadaError(f"cannot verify Canadian source snapshots: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile reviewed Canadian designation facts offline"
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
                            args.verify_source_cache,
                            args.data_dir,
                        )
                    }
                )
            )
        if args.rebuild:
            print(json.dumps(rebuild_canada(args.data_dir)["counts"]))
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild or --verify-source-cache")
    except CanadaError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
