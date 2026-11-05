"""Pinned source-declared subdivisions, separate from site text and political maps."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from archsearch import canada_data
from archsearch.domain import Site, SourceReference
from archsearch.supplement_data import SourceArtifact

DATA_DIR = Path(__file__).with_name("data")
VERSION: Literal["source-subdivisions-v6"] = "source-subdivisions-v6"
REVIEW_FILE = "subdivision_review.json"
PAYLOAD_FILE = "subdivisions.json"
MANIFEST_FILE = "subdivisions_manifest.json"
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_REVIEW_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
REVIEW_SHA256 = "6845883876b8694eba4d54e7c61ca58ed2e808b218dd2f50bb3fc169763aa327"
PAYLOAD_SHA256 = "34db3bbeffe43dbf60de981335b55acce42c24d6c21a1ebbb490ed400e6f4164"
SOURCE_REVIEW_SHA256 = "60ae194c7c65a5ccd80a8171336b036e3bf3a7a4e8c0963b83f80e5848abe3a9"
SOURCE_FACTS_SHA256 = "e0d22b77a37edb1736323d5f6050e9d0a1f67dc6f05986d3625d246e534b6350"
SUBDIVISION_PATTERN = r"^[A-Z]{2}:[a-z0-9][a-z0-9-]{0,63}$"
PREPARATION_HINT = (
    "请运行 python -m archsearch.subdivisions --rebuild 修复来源省区索引并重启服务。"
)
MEMBERSHIP_NOTE = (
    "省区来自已复核的现代来源字段，筛选资料对象及完整原定位点列，"
    "不推断各点所属省区、省界、历史政治归属或遗址边界。"
)
FEATURE_DISTRICT_NOTE = (
    "香港区级条件关联已复核整体对应的来源要素地区，不表示整体或全部几何都属于该区。"
    "筛入整体及完整来源多边形，不按多边形坐标反查行政区或裁切范围，"
    "不推断法定边界、历史政治归属或遗址生命周期。"
)
RECORD_LOCALITY_NOTE = (
    "巴西地区选项来自Iepha-MG原登记行的municipio（市镇）全文值；"
    "多地值保持原串，不自动拆分或地理编码。一处登记范围可对应多个原行和地区，"
    "筛选保留整个资料对象，不表示整体或全部组成部分都属于该地区，"
    "也不将市镇、保护编号或法律日期转换成坐标、边界或历史阶段。"
)
MERIMEE_ORIGINAL_AREAS = frozenset({"GP", "BL", "MF", "MQ", "RE"})
MERIMEE_EXTENSION_AREAS = frozenset({"GF", "YT", "PM"})
MERIMEE_AREAS = MERIMEE_ORIGINAL_AREAS | MERIMEE_EXTENSION_AREAS
RECORD_COMMUNE_NOTE = (
    "地区选项保留Mérimée原Commune_forme_editoriale（市镇）全文；多地值不拆分。"
    "国家／地区按原COG码经INSEE2026与UN M49关联现代统计区域，原Region和Departement仍保留。"
    "筛选保留整条来源记录及其限定保护范围，不表示建筑整体、全部组成部分或历史政权归属。"
    "名录含曾经或当前受保护对象，原坐标定位方法及精度未明确。"
)
MembershipRole = Literal[
    "source_declared_subdivision", "explicit_place_location", "source_feature_district",
    "source_record_locality", "source_record_commune",
]


class SubdivisionUnavailable(RuntimeError):
    """The independently reviewed local subdivision lookup is unavailable."""


class SubdivisionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: StrictStr = Field(pattern=SUBDIVISION_PATTERN)
    country: StrictStr = Field(pattern=r"^[A-Z]{2}$")
    label: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_country(self) -> SubdivisionDefinition:
        if self.id.partition(":")[0] != self.country or not self.label.strip():
            raise ValueError("subdivision IDs must retain their own source-country namespace")
        return self


class SubdivisionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: StrictStr = Field(min_length=1)
    source: SourceReference
    artifact: SourceArtifact
    field: StrictStr = Field(min_length=1)
    raw_value: StrictStr = Field(min_length=1)
    source_label: StrictStr | None = Field(default=None, min_length=1)
    source_row_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    role: MembershipRole


class ExtraMembership(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    site_id: StrictStr = Field(min_length=1)
    subdivision_id: StrictStr = Field(pattern=SUBDIVISION_PATTERN)
    source: SourceReference
    artifact: SourceArtifact
    field: StrictStr = Field(min_length=1)
    raw_value: StrictStr = Field(min_length=1)
    source_label: StrictStr | None = Field(default=None, min_length=1)
    source_row: dict[str, Any] = Field(min_length=1, max_length=128)
    source_row_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    role: MembershipRole
    review_method: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def validate_original_field(self) -> ExtraMembership:
        if (
            self.source_row.get(self.field) != self.raw_value
            or _row_hash(self.source_row) != self.source_row_sha256
            or not self.review_method.strip()
            or not self.source.excerpt.strip()
            or self.source.uri != self.artifact.uri
            or self.source_label is not None and self.source_label not in self.raw_value
        ):
            raise ValueError("extra membership needs its exact original field and reviewed page")
        return self


class SubdivisionReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    version: Literal["source-subdivisions-v6"]
    corpus_version: StrictStr = Field(min_length=1)
    corpus_ids_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_countries_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    canada_spec_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    hong_kong_spec_sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    minas_spec_sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    merimee_spec_sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    merimee_extension_spec_sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_review_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    review_method: StrictStr = Field(min_length=1)
    reviewed_at: StrictStr = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    subdivisions: list[SubdivisionDefinition] = Field(min_length=1)
    extra_memberships: list[ExtraMembership] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_review(self) -> SubdivisionReview:
        if not self.review_method.strip() or date.fromisoformat(self.reviewed_at).isoformat() != (
            self.reviewed_at
        ):
            raise ValueError("independent source review needs a method and actual ISO date")
        return self


class SubdivisionMembership(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    site_id: StrictStr = Field(min_length=1)
    subdivision_id: StrictStr = Field(pattern=SUBDIVISION_PATTERN)
    evidence: list[SubdivisionEvidence] = Field(min_length=1)


class SubdivisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    version: Literal["source-subdivisions-v6"]
    corpus_version: StrictStr = Field(min_length=1)
    corpus_ids_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_countries_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    canada_spec_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    hong_kong_spec_sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    minas_spec_sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    merimee_spec_sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    merimee_extension_spec_sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_review_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source_facts_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    review_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    subdivisions: list[SubdivisionDefinition] = Field(min_length=1)
    memberships: list[SubdivisionMembership] = Field(min_length=1)
    note: Literal[
        "Reviewed Canadian whole-object provinces, Hong Kong source-feature districts, "
        "Iepha-MG original-record municipality values and Mérimée original communes. "
        "Explicit record-to-object links only; "
        "no geocoding, boundary, chronology or text inference."
    ]


class SubdivisionStatus(BaseModel):
    ready: bool
    reason: str | None
    version: str | None


class SubdivisionFacet(BaseModel):
    id: str
    label: str
    count: int


class SubdivisionFacetsResponse(BaseModel):
    ready: bool
    reason: str | None
    subdivision_version: str | None
    corpus_version: str
    country: str
    supported: bool
    total: int
    assigned: int
    unassigned: int
    subdivisions: list[SubdivisionFacet]
    note: str


class SiteSubdivisionsResponse(BaseModel):
    ready: bool
    reason: str | None
    subdivision_version: str | None
    corpus_version: str
    site_id: str
    subdivisions: list[SubdivisionDefinition]
    memberships: list[SubdivisionMembership]
    note: str


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _row_hash(value: dict[str, Any]) -> str:
    return _hash(json.dumps(value, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")).encode())


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise SubdivisionUnavailable("来源省区文件超过紧凑索引容量限制。")
    return raw


def corpus_contract(sites: Sequence[Site]) -> dict[str, str]:
    roster = sorted((site.id, sorted(site.geography.countries) if site.geography else [])
                    for site in sites)
    if len({row[0] for row in roster}) != len(roster):
        raise ValueError("subdivision corpus identities must be unique")
    return {"corpus_ids_sha256": _hash(_bytes([row[0] for row in roster])),
            "corpus_countries_sha256": _hash(_bytes(roster))}


def _pins() -> None:
    if any(not re.fullmatch(r"[0-9a-f]{64}", pin) for pin in (
        REVIEW_SHA256, PAYLOAD_SHA256, SOURCE_REVIEW_SHA256, SOURCE_FACTS_SHA256,
    )):
        raise SubdivisionUnavailable("来源省区独立审批校验尚未配置。")


def source_facts(review: SubdivisionReview) -> dict[str, Any]:
    """Bind the independently checked facts without a circular report self-hash."""
    return review.model_dump(mode="json", exclude={"source_review_sha256"})


def _hong_kong_pin_matches(pin: str | None) -> bool:
    if pin is None:
        return True
    from archsearch.hong_kong_data import SPEC_SHA256

    return pin == SPEC_SHA256


def _minas_pin_matches(pin: str | None) -> bool:
    if pin is None:
        return True
    from archsearch.minas_data import SPEC_SHA256

    return pin == SPEC_SHA256


def _merimee_pin_matches(pin: str | None) -> bool:
    if pin is None:
        return True
    from archsearch.merimee_data import SPEC_SHA256

    return pin == SPEC_SHA256


def _merimee_extension_pin_matches(pin: str | None) -> bool:
    if pin is None:
        return True
    from archsearch.merimee_extension_data import SPEC_SHA256

    return pin == SPEC_SHA256


def _validate_payload(payload: SubdivisionPayload, sites: Sequence[Site], version: str) -> None:
    if payload.corpus_version != version or any(
        getattr(payload, key) != value for key, value in corpus_contract(sites).items()
    ):
        raise SubdivisionUnavailable("来源省区索引与当前语料身份或国家字段不匹配。")
    definitions = {row.id: row for row in payload.subdivisions}
    if len(definitions) != len(payload.subdivisions):
        raise SubdivisionUnavailable("来源省区定义重复。")
    by_id = {site.id: site for site in sites}
    seen: set[tuple[str, str]] = set()
    used: set[str] = set()
    for row in payload.memberships:
        pair = (row.site_id, row.subdivision_id)
        definition = definitions.get(row.subdivision_id)
        site = by_id.get(row.site_id)
        if (pair in seen or definition is None or site is None or site.geography is None
                or definition.country not in site.geography.countries):
            raise SubdivisionUnavailable("来源省区成员重复、缺失或与对象国家不匹配。")
        seen.add(pair)
        used.add(row.subdivision_id)
        for evidence in row.evidence:
            literal = evidence.source_label or definition.label
            if (evidence.role in {"source_declared_subdivision", "source_feature_district",
                                  "source_record_locality", "source_record_commune"}
                    and evidence.raw_value != literal):
                raise SubdivisionUnavailable("来源省区原始字段与标签不匹配。")
            if (evidence.role == "explicit_place_location"
                    and literal not in evidence.raw_value):
                raise SubdivisionUnavailable("地点来源未明确给出所采用省区。")
            if evidence.role == "source_feature_district" and (
                definition.country != "HK" or evidence.field != "DISTRICT"
                or payload.hong_kong_spec_sha256 is None
            ):
                raise SubdivisionUnavailable("来源要素地区必须绑定香港已核整体与原DISTRICT字段。")
            if evidence.role == "source_record_locality" and (
                definition.country != "BR" or evidence.field != "municipio"
                or payload.minas_spec_sha256 is None
                or not row.site_id.startswith("auth:br-iepha-mg:scope-")
                or evidence.raw_value in {"", "0"}
            ):
                raise SubdivisionUnavailable(
                    "来源登记地区必须绑定已核Iepha-MG范围及原municipio值。"
                )
            if evidence.role == "source_record_commune" and (
                definition.country not in MERIMEE_AREAS
                or evidence.field != "Commune_forme_editoriale"
                or (definition.country in MERIMEE_ORIGINAL_AREAS
                    and payload.merimee_spec_sha256 is None)
                or (definition.country in MERIMEE_EXTENSION_AREAS
                    and payload.merimee_extension_spec_sha256 is None)
                or re.fullmatch(r"auth:fr-merimee:PA[0-9]{8}", row.site_id) is None
                or not evidence.raw_value.strip()
            ):
                raise SubdivisionUnavailable(
                    "来源市镇必须绑定已核Mérimée记录、现代统计区域及原市镇全文。"
                )
    if used != set(definitions):
        raise SubdivisionUnavailable("来源省区定义不能包含无已审成员的选项。")


def _manifest(payload: SubdivisionPayload, payload_bytes: bytes) -> dict[str, Any]:
    return {
        "schema_version": 1, "version": VERSION, "corpus_version": payload.corpus_version,
        "review_sha256": REVIEW_SHA256, "source_review_sha256": SOURCE_REVIEW_SHA256,
        "source_facts_sha256": SOURCE_FACTS_SHA256,
        "canada_spec_sha256": payload.canada_spec_sha256,
        "hong_kong_spec_sha256": payload.hong_kong_spec_sha256,
        "minas_spec_sha256": payload.minas_spec_sha256,
        "merimee_spec_sha256": payload.merimee_spec_sha256,
        "merimee_extension_spec_sha256": payload.merimee_extension_spec_sha256,
        "files": {REVIEW_FILE: {"sha256": REVIEW_SHA256},
                  PAYLOAD_FILE: {"sha256": _hash(payload_bytes)}},
        "counts": {"subdivisions": len(payload.subdivisions),
                   "memberships": len(payload.memberships),
                   "assigned_sites": len({row.site_id for row in payload.memberships})},
        "policy": payload.note,
    }


def compile_payload(
    review: SubdivisionReview, sites: Sequence[Site],
    decisions: Sequence[canada_data.CanadaDecision],
) -> SubdivisionPayload:
    """Compile approved literal fields; a component never assigns its parent's province."""
    definitions = {row.label: row for row in review.subdivisions if row.country == "CA"}
    if len({row.id for row in review.subdivisions}) != len(review.subdivisions):
        raise SubdivisionUnavailable("duplicate subdivision definitions")
    if len(definitions) != sum(row.country == "CA" for row in review.subdivisions):
        raise SubdivisionUnavailable("duplicate Canadian source province labels")
    members: dict[tuple[str, str], list[SubdivisionEvidence]] = {}
    for decision in decisions:
        if decision.disposition not in {"include", "existing"}:
            continue
        row = decision.source_row
        if row.country != "Canada":
            continue
        definition = definitions.get(row.province_territory)
        if definition is None or decision.target_id is None:
            raise SubdivisionUnavailable("approved DFHD row has no literal province definition")
        pages = [artifact for artifact in decision.source_files
                 if artifact.filename.startswith("dfhd-pages/nhs-")]
        if len(pages) != 1:
            raise SubdivisionUnavailable("DFHD province needs its one original released page")
        original = row.model_dump(mode="json", by_alias=True)
        qualification = next((source for source in decision.evidence
                              if source.id.startswith("qualification:")), None)
        if qualification is None:
            raise SubdivisionUnavailable("DFHD qualification URI is absent")
        evidence = SubdivisionEvidence(
            source_id="ca-dfhd:" + row.designation_id,
            source=SourceReference(
                id="subdivision:ca-dfhd:" + row.designation_id,
                title="Federal Heritage Designations: Province or territory — "
                      + (row.name or row.other_names or row.designation_id),
                uri=qualification.uri, publisher=qualification.publisher,
                license=canada_data.OGL, revision="Original released row SHA256 "
                    + _row_hash(original), accessed=qualification.accessed,
                excerpt=row.province_territory,
            ),
            artifact=pages[0], field="Province or territory", raw_value=row.province_territory,
            source_row_sha256=_row_hash(original), role="source_declared_subdivision",
        )
        members.setdefault((decision.target_id, definition.id), []).append(evidence)
    for extra in review.extra_memberships:
        evidence = SubdivisionEvidence(
            source_id=extra.source.id, source=extra.source, artifact=extra.artifact,
            field=extra.field, raw_value=extra.raw_value,
            source_label=extra.source_label,
            source_row_sha256=extra.source_row_sha256, role=extra.role,
        )
        members.setdefault((extra.site_id, extra.subdivision_id), []).append(evidence)
    payload = SubdivisionPayload(
        schema_version=1, version=VERSION, corpus_version=review.corpus_version,
        corpus_ids_sha256=review.corpus_ids_sha256,
        corpus_countries_sha256=review.corpus_countries_sha256,
        canada_spec_sha256=review.canada_spec_sha256,
        hong_kong_spec_sha256=review.hong_kong_spec_sha256,
        minas_spec_sha256=review.minas_spec_sha256,
        merimee_spec_sha256=review.merimee_spec_sha256,
        merimee_extension_spec_sha256=review.merimee_extension_spec_sha256,
        source_review_sha256=review.source_review_sha256, review_sha256=REVIEW_SHA256,
        source_facts_sha256=_hash(_bytes(source_facts(review))),
        subdivisions=sorted(review.subdivisions, key=lambda row: row.id),
        memberships=[SubdivisionMembership(site_id=site_id, subdivision_id=subdivision_id,
                                          evidence=evidence)
                     for (site_id, subdivision_id), evidence in sorted(members.items())],
        note="Reviewed Canadian whole-object provinces, Hong Kong source-feature districts, "
             "Iepha-MG original-record municipality values and Mérimée original communes. "
             "Explicit record-to-object links only; "
             "no geocoding, boundary, chronology or text inference.",
    )
    _validate_payload(payload, sites, review.corpus_version)
    return payload


def rebuild_subdivisions(
    sites: Sequence[Site], corpus_version: str, data_dir: Path = DATA_DIR,
) -> dict[str, Any]:
    _pins()
    directory = Path(data_dir)
    try:
        raw_review = _read_bounded(directory / REVIEW_FILE, MAX_REVIEW_BYTES)
        if _hash(raw_review) != REVIEW_SHA256:
            raise SubdivisionUnavailable("来源省区复核文件与独立校验不符。")
        review = SubdivisionReview.model_validate_json(raw_review)
        if (review.source_review_sha256 != SOURCE_REVIEW_SHA256
                or _hash(_bytes(source_facts(review))) != SOURCE_FACTS_SHA256
                or review.canada_spec_sha256 != canada_data.SPEC_SHA256
                or not _hong_kong_pin_matches(review.hong_kong_spec_sha256)
                or not _minas_pin_matches(review.minas_spec_sha256)
                or not _merimee_pin_matches(review.merimee_spec_sha256)
                or not _merimee_extension_pin_matches(review.merimee_extension_spec_sha256)
                or review.corpus_version != corpus_version):
            raise SubdivisionUnavailable("来源省区事实、源版本或独立审批不符。")
        spec = canada_data._spec(directory)
        payload = compile_payload(review, sites, spec.decisions)
        raw_payload = _bytes(payload.model_dump(mode="json"))
        if _hash(raw_payload) != PAYLOAD_SHA256:
            raise SubdivisionUnavailable("来源省区派生文件与独立校验不符。")
        manifest = _manifest(payload, raw_payload)
        (directory / PAYLOAD_FILE).write_bytes(raw_payload)
        (directory / MANIFEST_FILE).write_bytes(_bytes(manifest))
        return manifest
    except SubdivisionUnavailable:
        raise
    except (OSError, ValueError, TypeError, canada_data.CanadaError) as error:
        raise SubdivisionUnavailable(f"无法重建来源省区索引：{error}") from error


class SubdivisionIndex:
    """Load a validated compact snapshot once; per-request lookup only uses immutable sets."""

    def __init__(
        self, sites: Sequence[Site], corpus_version: str, data_dir: Path = DATA_DIR,
        *, payload: SubdivisionPayload | None = None,
    ) -> None:
        self.corpus_version = corpus_version
        self.reason: str | None = None
        self.version: str | None = None
        definitions: dict[str, SubdivisionDefinition] = {}
        members: dict[str, frozenset[str]] = {}
        associations: dict[str, tuple[SubdivisionMembership, ...]] = {}
        try:
            if payload is None:
                _pins()
                directory = Path(data_dir)
                raw = _read_bounded(directory / PAYLOAD_FILE, MAX_PAYLOAD_BYTES)
                if _hash(raw) != PAYLOAD_SHA256:
                    raise SubdivisionUnavailable("来源省区索引校验不符。")
                payload = SubdivisionPayload.model_validate_json(raw)
                if (payload.review_sha256 != REVIEW_SHA256
                        or payload.source_review_sha256 != SOURCE_REVIEW_SHA256
                        or payload.source_facts_sha256 != SOURCE_FACTS_SHA256
                        or payload.canada_spec_sha256 != canada_data.SPEC_SHA256
                        or not _hong_kong_pin_matches(payload.hong_kong_spec_sha256)
                        or not _minas_pin_matches(payload.minas_spec_sha256)
                        or not _merimee_pin_matches(payload.merimee_spec_sha256)
                        or not _merimee_extension_pin_matches(
                            payload.merimee_extension_spec_sha256)):
                    raise SubdivisionUnavailable("来源省区索引的原始审批或来源绑定不符。")
                manifest = json.loads(_read_bounded(directory / MANIFEST_FILE,
                                                   MAX_MANIFEST_BYTES))
                if _bytes(manifest) != _bytes(_manifest(payload, raw)):
                    raise SubdivisionUnavailable("来源省区清单与已审索引不符。")
            _validate_payload(payload, sites, corpus_version)
            definitions = {row.id: row for row in payload.subdivisions}
            member_sets: dict[str, set[str]] = {identifier: set() for identifier in definitions}
            association_lists: dict[str, list[SubdivisionMembership]] = {}
            for membership in payload.memberships:
                member_sets[membership.subdivision_id].add(membership.site_id)
                association_lists.setdefault(membership.site_id, []).append(membership)
            members = {identifier: frozenset(values) for identifier, values in member_sets.items()}
            associations = {identifier: tuple(values)
                            for identifier, values in association_lists.items()}
            self.version = payload.version
        except (SubdivisionUnavailable, OSError, ValueError, TypeError, RecursionError) as error:
            self.reason = f"{error} {PREPARATION_HINT}"
        self.definitions = MappingProxyType(definitions)
        self.members = MappingProxyType(members)
        self.associations = MappingProxyType(associations)
        self.site_countries = MappingProxyType({
            site.id: frozenset(site.geography.countries) if site.geography else frozenset()
            for site in sites
        })

    @property
    def ready(self) -> bool:
        return self.reason is None and self.version is not None

    def status(self) -> SubdivisionStatus:
        return SubdivisionStatus(ready=self.ready, reason=self.reason, version=self.version)

    def validate(self, country: str | None, subdivision: str | None) -> None:
        if subdivision is None:
            return
        if not re.fullmatch(SUBDIVISION_PATTERN, subdivision) or country != subdivision[:2]:
            raise ValueError("来源省区必须与已选择的国家／地区一致。")
        if not self.ready:
            raise SubdivisionUnavailable(self.reason or PREPARATION_HINT)
        if subdivision not in self.definitions:
            raise ValueError("未知来源省区，请从当前来源选项选择。")

    def ids(self, country: str | None, subdivision: str | None) -> frozenset[str] | None:
        self.validate(country, subdivision)
        return self.members[subdivision] if subdivision is not None else None

    def facets(self, country: str, total: int) -> SubdivisionFacetsResponse:
        definitions = [row for row in self.definitions.values() if row.country == country]
        assigned = set().union(*(self.members[row.id] for row in definitions))
        return SubdivisionFacetsResponse(
            ready=self.ready, reason=self.reason, subdivision_version=self.version,
            corpus_version=self.corpus_version, country=country,
            supported=bool(definitions), total=total, assigned=len(assigned),
            unassigned=total - len(assigned),
            subdivisions=[SubdivisionFacet(id=row.id, label=row.label,
                                           count=len(self.members[row.id]))
                          for row in sorted(definitions, key=lambda row: row.label.casefold())],
            note=(FEATURE_DISTRICT_NOTE if country == "HK" else RECORD_LOCALITY_NOTE
                  if country == "BR" else RECORD_COMMUNE_NOTE
                  if country in MERIMEE_AREAS else MEMBERSHIP_NOTE)
                 + "未采用地区证据不表示实际地理未知；默认国家／地区目录保留全部资料。",
        )

    def site_response(self, site_id: str) -> SiteSubdivisionsResponse:
        memberships = self.associations.get(site_id, ())
        return SiteSubdivisionsResponse(
            ready=self.ready, reason=self.reason, subdivision_version=self.version,
            corpus_version=self.corpus_version, site_id=site_id,
            subdivisions=[self.definitions[row.subdivision_id] for row in memberships],
            memberships=list(memberships),
            note=(FEATURE_DISTRICT_NOTE if "HK" in self.site_countries.get(site_id, ())
                  else RECORD_LOCALITY_NOTE if "BR" in self.site_countries.get(site_id, ())
                  else RECORD_COMMUNE_NOTE
                  if MERIMEE_AREAS.intersection(self.site_countries.get(site_id, ()))
                  else MEMBERSHIP_NOTE),
        )


def main() -> None:
    from archsearch.corpus import CORPUS_VERSION, load_corpus

    parser = argparse.ArgumentParser(description="Compile source-declared subdivisions offline")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if not args.rebuild:
        parser.error("choose --rebuild")
    try:
        print(json.dumps(rebuild_subdivisions(load_corpus(), CORPUS_VERSION, args.data_dir)
                         ["counts"]))
    except (SubdivisionUnavailable, OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
