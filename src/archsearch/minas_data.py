"""Compile independently reviewed Minas Gerais register scopes entirely offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Literal

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
from archsearch.supplement_data import IdentityReview, SourceArtifact, base_contract

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "minas-tombados-v1"
CORPUS_VERSION = "global-v16"
BASE_COUNT = 3193
SOURCE_COUNT = 153
DATASET_ID = "a4b4c3d6-6fe3-40e5-8bf9-426625efdbba"
DATASET_URI = "https://dados.mg.gov.br/dataset/bens-tombados"
CSV_URI = (
    f"https://dados.mg.gov.br/dataset/{DATASET_ID}/resource/"
    "41e80d65-e365-44e8-81c9-df4e61914c8e/download/processos-tombo.csv"
)
DATAPACKAGE_URI = (
    f"https://dados.mg.gov.br/dataset/{DATASET_ID}/resource/"
    "de160191-1c72-4081-a1cc-e26061489410/download/datapackage.json"
)
METADATA_URI = f"https://dados.mg.gov.br/api/3/action/package_show?id={DATASET_ID}"
COUNTRY_CONTEXT_URI = "https://www.mg.gov.br/pagina/geografia"
LICENCE_URI = "https://creativecommons.org/licenses/by/4.0/"
PUBLISHER = "Instituto Estadual do Patrimônio Histórico e Artístico de Minas Gerais - IEPHA"
LICENCE = "CC BY 4.0"
ROSTER_FILE = "minas_source_roster.json"
SPEC_FILE = "minas_review.json"
SITES_FILE = "minas_sites.json"
MANIFEST_FILE = "minas_manifest.json"
MAX_FILE_BYTES = 4 * 1024 * 1024
# Root activates these only after actual independent source and derivative approval.
RAW_SOURCE_SHA256 = "0ef07b94a16da7f01fe43e60fae4ced24546662288e3af93c3e92136b9fbb8df"
METADATA_SHA256 = "4a2ad9f3bad1ba21c1b9d23d27044da5bd17acad813c144fa63bab345dbc027d"
DATAPACKAGE_SHA256 = "bd43dcda3ac700a15034af4403b52d9a47a2d050405f7201fec532975d6f49b4"
CANDIDATES_SHA256 = "06ed3a65718af9da02319645981d312a1d5972f57503e966f27c655f6c7b4f7e"
HANDOFF_SHA256 = "4b48810f256b3bbfce04b1c64b6cdeb699931b293cfde22ecb2ec2e35cb431a8"
INDEPENDENT_REVIEW_SHA256 = "d408771355483eb506fb784a0e76b89b719ddbcef04aeb70f1669201122e4672"
SOURCE_FACTS_SHA256 = "f5b7d8214995d0d0b3468a9b9f67c3abaca465e8fe2a6157f55efb5759fbe49c"
SOURCE_ROSTER_SHA256 = "81978be79313fb4ebaed8f5349512a57dac1c399a337139963321123edab687e"
SPEC_SHA256 = "def84d9b4c6a5c0c04794779337614dfb563e9b5b1d224d927c906d0721c7dca"
SITES_SHA256 = "f623e147db95017c0d6ce95ab3a341d11b920abcd048b255077b7ae4c357a173"
_SHA256 = r"^[0-9a-f]{64}$"


class MinasError(RuntimeError):
    """Frozen source, independent review, unchanged base or derivative differs."""


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def compact_hash(value: Any) -> str:
    return _hash(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )


def scope_key(process: str, full_scope: str) -> str:
    """Keep exact source strings; process alone cannot identify a protected whole."""
    return compact_hash([process, full_scope])


def project_id(key: str) -> str:
    if re.fullmatch(_SHA256, key) is None:
        raise ValueError("project scope identity requires its exact lowercase SHA256")
    return "auth:br-iepha-mg:scope-" + key


class SourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: SourceReference
    artifact: SourceArtifact

    @model_validator(mode="after")
    def validate_binding(self) -> SourceEvidence:
        if self.source.uri != self.artifact.uri or not self.source.excerpt.strip():
            raise ValueError("source evidence needs a nonempty excerpt bound to its original URI")
        return self


class MinasSourceRow(BaseModel):
    """All nine original strings, including literal0 and nonbreaking spaces."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    processo_ano: StrictStr
    denominacao: StrictStr
    denominacao_completa: StrictStr
    categoria: Literal["BI", "BM", "CH", "CP"]
    classe_subclasse: StrictStr
    municipio: StrictStr
    distrito: StrictStr
    ato_legal: StrictStr
    livro_de_tombo: StrictStr

    @field_validator("processo_ano", "denominacao", "denominacao_completa")
    @classmethod
    def nonblank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("original process and source names must not be blank")
        return value

    @property
    def scope_key(self) -> str:
        return scope_key(self.processo_ano, self.denominacao_completa)


SOURCE_FIELDS = tuple(MinasSourceRow.model_fields)


class MinasOriginalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    record_index: StrictInt = Field(ge=1)
    raw_fields: MinasSourceRow
    raw_fields_compact_sha256: StrictStr = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def validate_original_fields(self) -> MinasOriginalRecord:
        if compact_hash(self.raw_fields.model_dump(mode="json")) != self.raw_fields_compact_sha256:
            raise ValueError("all original row fields must match their complete compact hash")
        return self


class MinasSourceRoster(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    dataset_id: Literal["a4b4c3d6-6fe3-40e5-8bf9-426625efdbba"]
    source_artifact: SourceArtifact
    fields: list[StrictStr]
    records: list[MinasOriginalRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_roster(self) -> MinasSourceRoster:
        if self.source_artifact.uri != CSV_URI or self.fields != list(SOURCE_FIELDS):
            raise ValueError("original CSV identity and exact nine-field header must be retained")
        if [row.record_index for row in self.records] != list(range(1, len(self.records) + 1)):
            raise ValueError("every original ordered CSV record must appear exactly once")
        return self


class MinasDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope_key: StrictStr = Field(pattern=_SHA256)
    source_record_indices: list[StrictInt] = Field(min_length=1)
    disposition: Literal["include", "existing", "component", "exclude", "hold"]
    qualification: Literal[
        "immovable_cultural", "movable", "natural_only", "uncertain", "existing_overlap"
    ]
    scope_kind: Literal["single_record_scope", "composite_source_scope"]
    supported_scope_literal: StrictStr = Field(min_length=1)
    target_id: StrictStr | None
    reason: StrictStr = Field(min_length=1)
    independent_review: IdentityReview
    evidence: list[SourceEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_target(self) -> MinasDecision:
        indices = self.source_record_indices
        if indices != sorted(set(indices)) or any(value < 1 for value in indices):
            raise ValueError("scope source members must be unique ordered positive record indices")
        if not self.reason.strip() or not self.supported_scope_literal.strip():
            raise ValueError("scope decisions require literal scope and explicit reason")
        if self.disposition in {"exclude", "hold"}:
            if self.target_id is not None:
                raise ValueError("excluded or held scopes cannot acquire a public target")
        elif not self.target_id or not self.target_id.strip():
            raise ValueError("accepted scopes require a verified public target")
        if self.disposition == "include" and (
            self.qualification != "immovable_cultural"
            or self.target_id != project_id(self.scope_key)
        ):
            raise ValueError(
                "new wholes need independent cultural qualification and exact scope identity"
            )
        return self


class MinasMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence: SourceEvidence
    data_package: SourceEvidence
    csv_last_modified: StrictStr
    metadata_created: StrictStr
    metadata_modified: StrictStr
    datapackage_version: StrictFloat | StrictInt
    update_frequency_literal: StrictStr
    missing_values: list[StrictStr]

    @model_validator(mode="after")
    def validate_metadata(self) -> MinasMetadata:
        if (
            self.evidence.source.uri != METADATA_URI
            or self.data_package.source.uri != DATAPACKAGE_URI
        ):
            raise ValueError(
                "release metadata must retain its original CKAN and data-package sources"
            )
        if self.missing_values != ["0"]:
            raise ValueError(
                "retain the ambiguous original missing marker without interpreting row0"
            )
        return self


class MinasLicence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Literal["CC BY 4.0"]
    uri: Literal["https://creativecommons.org/licenses/by/4.0/"]
    attribution: StrictStr = Field(min_length=1)
    accessed: StrictStr
    evidence: SourceEvidence

    @model_validator(mode="after")
    def validate_licence(self) -> MinasLicence:
        if date.fromisoformat(self.accessed).isoformat() != self.accessed:
            raise ValueError("licence access date requires ISO YYYY-MM-DD")
        if self.evidence.source.uri != DATAPACKAGE_URI or any(
            value not in self.attribution for value in (DATASET_URI, LICENCE_URI, self.accessed)
        ):
            raise ValueError(
                "licence attribution must retain original package, source and access links"
            )
        return self


class MinasCountry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: Literal["BR"]
    region: Literal["latin-america-caribbean"]
    evidence: SourceEvidence

    @model_validator(mode="after")
    def validate_context(self) -> MinasCountry:
        if self.evidence.source.uri != COUNTRY_CONTEXT_URI:
            raise ValueError("country association needs its official source-state context")
        return self


class MinasReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cohort_version: Literal["minas-tombados-v1"]
    corpus_version: Literal["global-v16"]
    base_count: Literal[3193]
    base_ids_sha256: StrictStr = Field(pattern=_SHA256)
    base_sites_sha256: StrictStr = Field(pattern=_SHA256)
    candidates_sha256: StrictStr = Field(pattern=_SHA256)
    handoff_sha256: StrictStr = Field(pattern=_SHA256)
    independent_report_sha256: StrictStr = Field(pattern=_SHA256)
    metadata: MinasMetadata
    licence: MinasLicence
    country: MinasCountry
    decisions: list[MinasDecision] = Field(min_length=1)


class MinasSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    roster: MinasSourceRoster
    review: MinasReview


def _source_facts(spec: MinasSpec) -> dict[str, Any]:
    return {
        "roster": spec.roster.model_dump(mode="json"),
        "review": spec.review.model_dump(
            mode="json",
            exclude={
                "candidates_sha256",
                "handoff_sha256",
                "independent_report_sha256",
            },
        ),
    }


def _artifacts(spec: MinasSpec) -> dict[str, SourceArtifact]:
    evidence = [
        spec.review.metadata.evidence,
        spec.review.metadata.data_package,
        spec.review.licence.evidence,
        spec.review.country.evidence,
    ]
    evidence.extend(item for decision in spec.review.decisions for item in decision.evidence)
    result: dict[str, SourceArtifact] = {}
    for artifact in [spec.roster.source_artifact, *(item.artifact for item in evidence)]:
        if artifact.filename in result and result[artifact.filename] != artifact:
            raise MinasError("one cache filename has conflicting original artifact contracts")
        result[artifact.filename] = artifact
    return result


def _validate_spec(spec: MinasSpec) -> None:
    if len(spec.roster.records) != SOURCE_COUNT:
        raise MinasError("complete original Minas CSV roster is required")
    groups: dict[str, list[MinasOriginalRecord]] = {}
    for row in spec.roster.records:
        groups.setdefault(row.raw_fields.scope_key, []).append(row)
    decisions = {row.scope_key: row for row in spec.review.decisions}
    if len(decisions) != len(spec.review.decisions) or set(decisions) != set(groups):
        raise MinasError(
            "each exact process/full-scope group requires exactly one independent decision"
        )
    for key, members in groups.items():
        decision = decisions[key]
        if decision.source_record_indices != [row.record_index for row in members]:
            raise MinasError("whole grouping must retain every exact-scope source member once")
        if decision.supported_scope_literal != members[0].raw_fields.denominacao_completa:
            raise MinasError("a short name or process alone cannot replace original complete scope")
        expected_kind = "single_record_scope" if len(members) == 1 else "composite_source_scope"
        if decision.scope_kind != expected_kind:
            raise MinasError("whole grouping must distinguish single and composite source scopes")
        if decision.disposition == "include" and (
            any(row.raw_fields.categoria == "BM" for row in members)
            or all(row.raw_fields.classe_subclasse == "Patrimônio Natural" for row in members)
        ):
            raise MinasError(
                "movable or solely natural source classes cannot become cultural places"
            )
    _artifacts(spec)


def _read_bounded(root: Path, filename: str) -> bytes:
    directory = root.resolve()
    path = (directory / filename).resolve()
    if not path.is_relative_to(directory):
        raise MinasError("local source or derivative path escapes its chosen directory")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise MinasError(f"local Minas file exceeds its bounded contract: {filename}")
    return raw


def _require_pins() -> None:
    if any(
        re.fullmatch(_SHA256, value) is None
        for value in (
            RAW_SOURCE_SHA256,
            METADATA_SHA256,
            DATAPACKAGE_SHA256,
            CANDIDATES_SHA256,
            HANDOFF_SHA256,
            INDEPENDENT_REVIEW_SHA256,
            SOURCE_FACTS_SHA256,
            SOURCE_ROSTER_SHA256,
            SPEC_SHA256,
            SITES_SHA256,
        )
    ):
        raise MinasError("Minas independent source approval and derivative pins are not configured")


def _spec(directory: Path) -> MinasSpec:
    _require_pins()
    roster, review = _read_bounded(directory, ROSTER_FILE), _read_bounded(directory, SPEC_FILE)
    if _hash(roster) != SOURCE_ROSTER_SHA256 or _hash(review) != SPEC_SHA256:
        raise MinasError("Minas normalized roster or review differs from its independent pin")
    spec = MinasSpec(
        roster=MinasSourceRoster.model_validate_json(roster),
        review=MinasReview.model_validate_json(review),
    )
    if (
        spec.roster.source_artifact.sha256 != RAW_SOURCE_SHA256
        or spec.review.metadata.evidence.artifact.sha256 != METADATA_SHA256
        or spec.review.metadata.data_package.artifact.sha256 != DATAPACKAGE_SHA256
        or spec.review.licence.evidence.artifact != spec.review.metadata.data_package.artifact
        or spec.review.candidates_sha256 != CANDIDATES_SHA256
        or spec.review.handoff_sha256 != HANDOFF_SHA256
        or spec.review.independent_report_sha256 != INDEPENDENT_REVIEW_SHA256
        or _hash(_bytes(_source_facts(spec))) != SOURCE_FACTS_SHA256
    ):
        raise MinasError("Minas original sources or complete independent source facts differ")
    _validate_spec(spec)
    return spec


def _ordered(spec: MinasSpec) -> list[MinasDecision]:
    return sorted(
        (row for row in spec.review.decisions if row.disposition == "include"),
        key=lambda row: (
            _hash((COHORT_VERSION + ":" + project_id(row.scope_key)).encode()),
            project_id(row.scope_key),
        ),
    )


def compile_minas(spec: MinasSpec) -> list[Site]:
    """Project reviewed original fields; only the pinned loader activates source approval."""
    _validate_spec(spec)
    by_index = {row.record_index: row.raw_fields for row in spec.roster.records}
    result = []
    for decision in _ordered(spec):
        rows = [by_index[index] for index in decision.source_record_indices]
        source = SourceReference(
            id="source:br-iepha-mg:" + decision.scope_key,
            title="Patrimônio Cultural Tombado — original CSV fields",
            uri=DATASET_URI,
            publisher=PUBLISHER,
            license=LICENCE,
            revision="sha256:" + spec.roster.source_artifact.sha256,
            accessed=spec.review.licence.accessed,
            excerpt=rows[0].denominacao_completa,
        )
        references = [
            source,
            spec.review.metadata.data_package.source,
            spec.review.country.evidence.source,
        ]
        unique_refs = list(dict.fromkeys(item.model_dump_json() for item in references))
        identifier = project_id(decision.scope_key)
        result.append(
            Site(
                id=identifier,
                title=rows[0].denominacao_completa,
                description="",
                description_zh="",
                details="Original source fields (Portuguese):\n"
                + json.dumps(
                    [
                        {"record_index": index, **by_index[index].model_dump(mode="json")}
                        for index in decision.source_record_indices
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                names=[],
                types=["historic-site"],
                periods=[],
                repr_point=None,
                location_precision=None,
                source_uri=DATASET_URI,
                contributors=[PUBLISHER],
                period_evidence=[],
                source_kind="supplement",
                source_refs=[SourceReference.model_validate_json(item) for item in unique_refs],
                geography=Geography(
                    authority_id="supplement:" + identifier,
                    countries=["BR"],
                    regions=["latin-america-caribbean"],
                    source=spec.review.country.evidence.source,
                    point_count=0,
                    note=(
                        "Minas Gerais来源目录与既有BR目录分组；不是UNESCO列入或政治归属声明。"
                        "原municipio/distrito整串保留，不拆分、地理编码或推断代表点。"
                        "原字段0与数据字典缺失值说明存在字段语义歧义，保持原值；"
                        "登记、法律和书号信息不转换成生命周期。项目scope编号不是永久法定ID。"
                    ),
                ),
            )
        )
    return result


def _manifest(spec: MinasSpec, payload: bytes) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "cohort_version": COHORT_VERSION,
        "corpus_version": CORPUS_VERSION,
        "base": {
            key: value for key, value in spec.review.model_dump().items() if key.startswith("base_")
        },
        "independent_source_review": {
            "candidates_sha256": CANDIDATES_SHA256,
            "handoff_sha256": HANDOFF_SHA256,
            "report_sha256": INDEPENDENT_REVIEW_SHA256,
            "source_facts_sha256": SOURCE_FACTS_SHA256,
        },
        "files": {
            ROSTER_FILE: {"sha256": SOURCE_ROSTER_SHA256},
            SPEC_FILE: {"sha256": SPEC_SHA256},
            SITES_FILE: {"sha256": _hash(payload)},
        },
        "counts": {
            "base": BASE_COUNT,
            "source_records": len(spec.roster.records),
            "source_scopes": len(spec.review.decisions),
            "added": len(_ordered(spec)),
            "total": BASE_COUNT + len(_ordered(spec)),
            "decisions": dict(
                sorted(Counter(row.disposition for row in spec.review.decisions).items())
            ),
            "adopted_reference_points": 0,
            "new_historical_phases": 0,
        },
        "metadata": spec.review.metadata.model_dump(mode="json"),
        "licence": spec.review.licence.model_dump(mode="json"),
        "country": spec.review.country.model_dump(mode="json"),
        "decisions": [row.model_dump(mode="json") for row in spec.review.decisions],
        "source_artifacts": [
            value.model_dump(mode="json") for _, value in sorted(_artifacts(spec).items())
        ],
        "semantics": "Exact process/full-scope identity; source rows preserved. "
        "Composite scopes are not split. "
        "Administrative0 retained despite missing-value ambiguity. No inferred point, district, "
        "precision, lifecycle or UNESCO designation. CC BY4 applies to original dataset fields.",
    }


def _validate_base(base: list[Site], spec: MinasSpec) -> set[str]:
    expected = {
        key: value for key, value in spec.review.model_dump().items() if key.startswith("base_")
    }
    if base_contract(base) != expected:
        raise MinasError("Minas base differs from the unchanged3193 field/order contract")
    ids = {site.id for site in base}
    if len(ids) != BASE_COUNT or any(
        row.target_id not in ids
        for row in spec.review.decisions
        if row.disposition in {"existing", "component"}
    ):
        raise MinasError("Minas existing/component target is absent or base IDs duplicate")
    return ids


def _output_path(directory: Path, filename: str) -> Path:
    path = directory / filename
    if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
        raise MinasError("Minas derivative output must remain a regular local path")
    return path


def rebuild_minas(data_dir: Path = DATA_DIR, *, base: list[Site] | None = None) -> dict[str, Any]:
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        if base is not None:
            _validate_base(base, spec)
        payload = _bytes([site.model_dump(mode="json") for site in compile_minas(spec)])
        if _hash(payload) != SITES_SHA256:
            raise MinasError("compiled Minas sites differ from their independent pin")
        manifest = _manifest(spec, payload)
        sites_path = _output_path(directory, SITES_FILE)
        manifest_path = _output_path(directory, MANIFEST_FILE)
        sites_path.write_bytes(payload)
        manifest_path.write_bytes(_bytes(manifest))
        return manifest
    except MinasError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise MinasError(f"cannot rebuild frozen Minas facts: {error}") from error


def load_minas(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        base_ids = _validate_base(base, spec)
        additions = compile_minas(spec)
        if base_ids & {site.id for site in additions}:
            raise MinasError("Minas additions duplicate an existing identity")
        payload = _read_bounded(directory, SITES_FILE)
        if (
            payload != _bytes([site.model_dump(mode="json") for site in additions])
            or _hash(payload) != SITES_SHA256
        ):
            raise MinasError("Minas sites differ from independently approved source facts")
        manifest = json.loads(_read_bounded(directory, MANIFEST_FILE))
        if _bytes(manifest) != _bytes(_manifest(spec, payload)):
            raise MinasError("Minas manifest differs from the frozen contract")
        return base + additions
    except MinasError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise MinasError(f"cannot load frozen Minas facts: {error}") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Check optional original snapshots and every ordered raw CSV field; never fetch."""
    try:
        spec = _spec(Path(data_dir))
        artifacts = _artifacts(spec)
        for name, artifact in artifacts.items():
            if _hash(_read_bounded(cache_dir, name)) != artifact.sha256:
                raise MinasError(f"Minas original source snapshot differs: {name}")
        raw = _read_bounded(cache_dir, spec.roster.source_artifact.filename)
        reader = csv.DictReader(
            io.StringIO(raw.decode("utf-8-sig"), newline=""), delimiter=";", strict=True
        )
        if reader.fieldnames != list(SOURCE_FIELDS):
            raise MinasError("Minas original CSV header/order differs")
        original = list(reader)
        if len(original) != len(spec.roster.records) or any(
            row != expected.raw_fields.model_dump(mode="json")
            for row, expected in zip(original, spec.roster.records, strict=True)
        ):
            raise MinasError("Minas original CSV fields/order differ from their complete roster")
        return len(artifacts)
    except MinasError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError, csv.Error) as error:
        raise MinasError(f"cannot verify Minas source snapshots: {error}") from error


def main() -> None:
    from archsearch.corpus import CorpusError, load_pre_minas_corpus

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
            print(
                json.dumps(
                    rebuild_minas(args.data_dir, base=load_pre_minas_corpus(args.data_dir))[
                        "counts"
                    ]
                )
            )
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild and/or --verify-source-cache")
    except (MinasError, CorpusError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
