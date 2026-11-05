"""Append separately reviewed GF/YT/PM Mérimée notices entirely offline."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, StrictStr, model_validator

from archsearch import merimee_data as original
from archsearch.domain import Site
from archsearch.merimee_common import NoticeProjection, project_notice
from archsearch.supplement_data import IdentityReview, SourceArtifact, base_contract

DATA_DIR = original.DATA_DIR
COHORT_VERSION = "merimee-extension-v1"
CORPUS_VERSION = "global-v18"
BASE_COUNT = 3775
SOURCE_COUNT = 123
FULL_SOURCE_COUNT = original.FULL_SOURCE_COUNT
ROSTER_FILE = "merimee_extension_source_roster.json"
SPEC_FILE = "merimee_extension_review.json"
SITES_FILE = "merimee_extension_sites.json"
MANIFEST_FILE = "merimee_extension_manifest.json"
CACHE_PREFIX = "merimee-extension-source-candidate/"
# Root activates this cohort only after its own independent source and derivative review.
RAW_SOURCE_SHA256 = "d83f5a3beb83221ed55169159fc0ce7c6d3dad66edca205a225cd30c136dd6ec"
METADATA_SHA256 = "d4865cdc53abbbbdcf8db24195c9711b3bab6fde3e6ad4d9f97037e423671496"
LICENCE_SHA256 = "e3abcb87edeca051d99be349976a688802f1340f8482a0290ebabea73561fcb8"
CANDIDATES_SHA256 = "f068d8b43328031de6c6ec16f4ec1eead98b43525d4bd73a894561abbe8daa1e"
HANDOFF_SHA256 = "78748e5af942123c16a3833fd347a5dac5466d4ca4c3527ef2b0fecfde6a9a0e"
INDEPENDENT_REVIEW_SHA256 = "d458ff4442a63d007598e1a7b1f135e78426aacdaf5ab4fc7987c6beaa046e1a"
SOURCE_FACTS_SHA256 = "8c8b20f9fdc9d293056cf4617bab415f64e4dc5e791ff18a8790b28ea5100322"
SOURCE_ROSTER_SHA256 = "a7461cf8ec1070ec8ed49350f977bfab4ae18cbb12315079f0860c186b380e17"
SPEC_SHA256 = "1bea70c52cbf37a8264d1919888aa6cd9f7151cbdd3f5e6987b2b776cc6e425d"
SITES_SHA256 = "10a86bec621e6d55c951069d4301e5f02db25468ea616f4d844ba91bf87fb076"
_SHA256 = r"^[0-9a-f]{64}$"
AreaCode = Literal["GF", "YT", "PM"]


class MerimeeExtensionError(RuntimeError):
    """An extension source, independent review, frozen base or derivative differs."""


class MerimeeExtensionDecision(original.FrozenModel):
    reference: StrictStr = Field(pattern=r"^PA[0-9]{8}$")
    disposition: Literal["include", "existing", "component", "hold", "exclude"]
    qualification: Literal["immovable_cultural", "uncertain", "existing_overlap"]
    scope_kind: Literal["whole_notice_scope", "specified_parts", "composite_protected_scope"]
    supported_scope_field: StrictStr
    supported_scope_literal: StrictStr = Field(min_length=1)
    target_id: StrictStr | None
    reason: StrictStr = Field(min_length=1)
    independent_review: IdentityReview
    evidence: list[original.SourceEvidence] = Field(min_length=1)
    area_code: AreaCode
    point_adoption: Literal["provider_reference", "unavailable", "withheld"]

    @model_validator(mode="after")
    def validate_decision(self) -> MerimeeExtensionDecision:
        if self.supported_scope_field not in original.SOURCE_FIELDS or not all(
            value.strip() for value in (self.reason, self.supported_scope_literal)
        ):
            raise ValueError(
                "extension review needs complete literal source scope and audit reason"
            )
        if self.disposition in {"hold", "exclude"}:
            if self.target_id is not None:
                raise ValueError("held or excluded notices cannot acquire a public target")
        elif not self.target_id or not self.target_id.strip():
            raise ValueError("accepted notices require an independently reviewed target")
        if self.disposition == "include" and (
            self.qualification != "immovable_cultural"
            or self.target_id != original.project_id(self.reference)
        ):
            raise ValueError("new notices require cultural qualification and exact PA identity")
        if self.disposition != "include" and self.point_adoption == "provider_reference":
            raise ValueError("a redirect or unadopted notice cannot supply a new reference point")
        return self


class MerimeeExtensionArea(original.FrozenModel):
    code: AreaCode
    name: StrictStr = Field(min_length=1)
    project_region: Literal["africa", "latin-america-caribbean", "europe-north-america"]
    source_m49_cells: list[StrictStr] = Field(min_length=15, max_length=15)
    evidence: list[original.SourceEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_active_row(self) -> MerimeeExtensionArea:
        expected = {
            "GF": (
                [
                    "019",
                    "Americas",
                    "419",
                    "Latin America and the Caribbean",
                    "005",
                    "South America",
                ],
                "French Guiana",
                "254",
                "GUF",
                "latin-america-caribbean",
            ),
            "YT": (
                ["002", "Africa", "202", "Sub-Saharan Africa", "014", "Eastern Africa"],
                "Mayotte",
                "175",
                "MYT",
                "africa",
            ),
            "PM": (
                ["019", "Americas", "021", "Northern America", "", ""],
                "Saint Pierre and Miquelon",
                "666",
                "SPM",
                "europe-north-america",
            ),
        }
        hierarchy, name, numeric, iso3, region = expected[self.code]
        if (
            self.source_m49_cells
            != ["001", "World", *hierarchy, name, numeric, self.code, iso3, "", "", ""]
            or self.name != name
            or self.project_region != region
        ):
            raise ValueError(
                "extension area requires its exact current15-cell M49 row and grouping"
            )
        return self


class MerimeeExtensionCogEvidence(original.MerimeeCogEvidence):
    """Separate current-code contract; the original five-area validator stays unchanged."""

    def area(self) -> str:
        if self.current_commune is not None and self.current_department is not None:
            if self.current_overseas_commune is not None or self.current_overseas_area is not None:
                raise ValueError("one COG token cannot mix commune and overseas joins")
            commune, department = self.current_commune, self.current_department
            if (
                commune.get("COM") != self.original_code
                or commune.get("TYPECOM") != "COM"
                or commune.get("DEP") != department.get("DEP")
            ):
                raise ValueError("extension current commune-to-department exact join differs")
            result = {"973": "GF", "976": "YT"}.get(department.get("DEP", ""))
        elif self.current_overseas_commune is not None and self.current_overseas_area is not None:
            if self.current_commune is not None or self.current_department is not None:
                raise ValueError("one COG token cannot mix commune and overseas joins")
            commune, area = self.current_overseas_commune, self.current_overseas_area
            if commune.get("COM_COMER") != self.original_code or commune.get("COMER") != area.get(
                "COMER"
            ):
                raise ValueError("extension current overseas commune-to-area exact join differs")
            result = {"975": "PM"}.get(area.get("COMER", ""))
        else:
            raise ValueError("extension COG requires a complete original current INSEE join")
        if result is None:
            raise ValueError(
                "current COG token is outside the independently reviewed extension areas"
            )
        return result


class MerimeeExtensionAreaCrosswalk(original.FrozenModel):
    reference: StrictStr = Field(pattern=r"^PA[0-9]{8}$")
    source_cog_literal: StrictStr
    source_commune_literal: StrictStr
    source_region: StrictStr
    current_statistical_area: AreaCode
    current_cog_evidence: list[MerimeeExtensionCogEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_join(self) -> MerimeeExtensionAreaCrosswalk:
        if self.source_cog_literal.split(";") != [
            item.original_code for item in self.current_cog_evidence
        ] or any(
            item.area() != self.current_statistical_area for item in self.current_cog_evidence
        ):
            raise ValueError(
                "each original extension COG token needs its exact current same-area join"
            )
        return self


class MerimeeExtensionReview(original.FrozenModel):
    schema_version: Literal[1]
    cohort_version: Literal["merimee-extension-v1"]
    corpus_version: Literal["global-v18"]
    base_count: Literal[3775]
    base_ids_sha256: StrictStr = Field(pattern=_SHA256)
    base_sites_sha256: StrictStr = Field(pattern=_SHA256)
    candidates_sha256: StrictStr = Field(pattern=_SHA256)
    handoff_sha256: StrictStr = Field(pattern=_SHA256)
    independent_report_sha256: StrictStr = Field(pattern=_SHA256)
    metadata: original.MerimeeMetadata
    licence: original.MerimeeLicence
    areas: list[MerimeeExtensionArea] = Field(min_length=3, max_length=3)
    area_crosswalk: list[MerimeeExtensionAreaCrosswalk] = Field(min_length=1)
    point_axis_evidence: list[original.SourceEvidence] = Field(min_length=1)
    decisions: list[MerimeeExtensionDecision] = Field(min_length=1)


class MerimeeExtensionSpec(original.FrozenModel):
    roster: original.MerimeeSourceRoster
    review: MerimeeExtensionReview


def _source_facts(spec: MerimeeExtensionSpec) -> dict[str, Any]:
    return {
        "roster": spec.roster.model_dump(mode="json"),
        "review": spec.review.model_dump(
            mode="json",
            exclude={"candidates_sha256", "handoff_sha256", "independent_report_sha256"},
        ),
    }


def _artifacts(spec: MerimeeExtensionSpec) -> dict[str, SourceArtifact]:
    evidence = [spec.review.metadata.evidence, spec.review.licence.evidence]
    evidence += spec.review.point_axis_evidence
    evidence += [item for area in spec.review.areas for item in area.evidence]
    evidence += [item for decision in spec.review.decisions for item in decision.evidence]
    artifacts = [spec.roster.source_artifact, *(item.artifact for item in evidence)]
    artifacts += [
        SourceArtifact(
            filename=CACHE_PREFIX + row.api_receipt.filename,
            sha256=row.api_receipt.page_sha256,
            uri=row.api_receipt.uri,
        )
        for row in spec.roster.records
    ]
    result: dict[str, SourceArtifact] = {}
    for artifact in artifacts:
        if artifact.filename in result and result[artifact.filename] != artifact:
            raise MerimeeExtensionError("one extension cache filename has conflicting URI/hash")
        result[artifact.filename] = artifact
    return result


def _validate_spec(spec: MerimeeExtensionSpec) -> None:
    records = {row.raw_fields["Reference"]: row.raw_fields for row in spec.roster.records}
    decisions = {row.reference: row for row in spec.review.decisions}
    mappings = {row.reference: row for row in spec.review.area_crosswalk}
    if (
        len(records) != SOURCE_COUNT
        or len(decisions) != len(spec.review.decisions)
        or set(records) != set(decisions)
        or set(mappings) != set(records)
        or len(mappings) != len(spec.review.area_crosswalk)
    ):
        raise MerimeeExtensionError(
            "every original extension notice needs exactly one decision/join"
        )
    if {area.code for area in spec.review.areas} != {"GF", "YT", "PM"}:
        raise MerimeeExtensionError("all three distinct extension statistical areas are required")
    accepted = {
        original.project_id(row.reference)
        for row in spec.review.decisions
        if row.disposition == "include"
    }
    for reference, fields in records.items():
        decision, mapping = decisions[reference], mappings[reference]
        if decision.supported_scope_literal != fields[decision.supported_scope_field]:
            raise MerimeeExtensionError("extension scope must retain the full exact original field")
        if (
            mapping.source_cog_literal != fields["COG_Insee_lors_de_la_protection"]
            or mapping.source_commune_literal != fields["Commune_forme_index"]
            or mapping.source_region != fields["Region"]
            or decision.area_code != mapping.current_statistical_area
        ):
            raise MerimeeExtensionError("extension area must bind the original COG/commune/Region")
        point = original.parse_reference_point(fields["coordonnees_au_format_WGS84"])
        if (point is None) != (decision.point_adoption == "unavailable"):
            raise MerimeeExtensionError(
                "missing extension coordinates cannot become invented points"
            )
        if decision.disposition == "component" and (
            decision.target_id == original.project_id(reference)
            or (
                decision.target_id is not None
                and decision.target_id in {original.project_id(ref) for ref in decisions}
                and decision.target_id not in accepted
            )
        ):
            raise MerimeeExtensionError(
                "component must target a distinct accepted whole, not a chain"
            )
    _artifacts(spec)


def _require_pins() -> None:
    if any(
        re.fullmatch(_SHA256, value) is None
        for value in (
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
        )
    ):
        raise MerimeeExtensionError(
            "extension independent source/derivative pins are not configured"
        )


def _spec(directory: Path) -> MerimeeExtensionSpec:
    _require_pins()
    roster = original._read_bounded(directory, ROSTER_FILE)
    review = original._read_bounded(directory, SPEC_FILE)
    if original._hash(roster) != SOURCE_ROSTER_SHA256 or original._hash(review) != SPEC_SHA256:
        raise MerimeeExtensionError("extension roster/review differs from independent pin")
    spec = MerimeeExtensionSpec(
        roster=original.MerimeeSourceRoster.model_validate_json(roster),
        review=MerimeeExtensionReview.model_validate_json(review),
    )
    if (
        spec.roster.source_artifact.sha256 != RAW_SOURCE_SHA256
        or spec.review.metadata.evidence.artifact.sha256 != METADATA_SHA256
        or spec.review.licence.evidence.artifact.sha256 != LICENCE_SHA256
        or spec.review.candidates_sha256 != CANDIDATES_SHA256
        or spec.review.handoff_sha256 != HANDOFF_SHA256
        or spec.review.independent_report_sha256 != INDEPENDENT_REVIEW_SHA256
        or original._hash(original._bytes(_source_facts(spec))) != SOURCE_FACTS_SHA256
    ):
        raise MerimeeExtensionError("extension source receipts or complete reviewed facts differ")
    _validate_spec(spec)
    return spec


def _ordered(spec: MerimeeExtensionSpec) -> list[MerimeeExtensionDecision]:
    return sorted(
        (row for row in spec.review.decisions if row.disposition == "include"),
        key=lambda d: (
            original._hash((COHORT_VERSION + ":" + original.project_id(d.reference)).encode()),
            d.reference,
        ),
    )


def compile_merimee_extension(spec: MerimeeExtensionSpec) -> list[Site]:
    """Project only separately approved source literals; approval pins remain external."""
    _validate_spec(spec)
    records = {row.raw_fields["Reference"]: row.raw_fields for row in spec.roster.records}
    areas = {area.code: area for area in spec.review.areas}
    result = []
    for decision in _ordered(spec):
        area = areas[decision.area_code]
        result.append(
            project_notice(
                records[decision.reference],
                NoticeProjection(
                    reference=decision.reference,
                    scope_kind=decision.scope_kind,
                    scope_field=decision.supported_scope_field,
                    scope_literal=decision.supported_scope_literal,
                    adopt_point=decision.point_adoption == "provider_reference",
                    area_code=area.code,
                    project_region=area.project_region,
                    geography_source=area.evidence[0].source,
                    raw_source_sha256=spec.roster.source_artifact.sha256,
                    accessed=spec.review.licence.accessed,
                    metadata_source=spec.review.metadata.evidence.source,
                    licence_source=spec.review.licence.evidence.source,
                ),
            )
        )
    return result


def _validate_base(base: list[Site], spec: MerimeeExtensionSpec) -> None:
    expected = {
        key: value for key, value in spec.review.model_dump().items() if key.startswith("base_")
    }
    if base_contract(base) != expected:
        raise MerimeeExtensionError(
            "extension base differs from the unchanged3775 field/order contract"
        )
    ids = {site.id for site in base}
    additions = {original.project_id(d.reference) for d in _ordered(spec)}
    if len(ids) != BASE_COUNT or ids & additions:
        raise MerimeeExtensionError("extension additions duplicate frozen base identities")
    for decision in spec.review.decisions:
        if decision.disposition == "existing" and decision.target_id not in ids:
            raise MerimeeExtensionError("existing notice target is absent from the frozen base")
        if decision.disposition == "component" and decision.target_id not in ids | additions:
            raise MerimeeExtensionError("component target is absent from base and accepted notices")


def _manifest(spec: MerimeeExtensionSpec, additions: list[Site], payload: bytes) -> dict[str, Any]:
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
            SITES_FILE: {"sha256": original._hash(payload)},
        },
        "counts": {
            "base": BASE_COUNT,
            "source_records": len(spec.roster.records),
            "added": len(additions),
            "total": BASE_COUNT + len(additions),
            "decisions": dict(
                sorted(Counter(d.disposition for d in spec.review.decisions).items())
            ),
            "adopted_reference_points": sum(s.repr_point is not None for s in additions),
            "missing_reference_points": sum(s.repr_point is None for s in additions),
            "new_historical_phases": 0,
            "areas": dict(sorted(Counter(d.area_code for d in _ordered(spec)).items())),
        },
        "metadata": spec.review.metadata.model_dump(mode="json"),
        "licence": spec.review.licence.model_dump(mode="json"),
        "areas": [area.model_dump(mode="json") for area in spec.review.areas],
        "decisions": [d.model_dump(mode="json") for d in spec.review.decisions],
        "source_artifacts": [
            a.model_dump(mode="json") for _, a in sorted(_artifacts(spec).items())
        ],
        "semantics": "Independent append-only GF/YT/PM notice cohort; original fields and scope "
        "limits retained. Old3775 records unchanged. Current statistical areas are not historical "
        "jurisdictions; original WGS84 references have unknown method and precision. No generated "
        "points, aliases, phases, UNESCO listing or current legal-status assertions. OpenLicence2 "
        "covers dataset fields, not automatically linked media.",
    }


def _public_error(error: Exception, action: str) -> MerimeeExtensionError:
    return MerimeeExtensionError(f"cannot {action} frozen Mérimée extension: {error}")


def rebuild_merimee_extension(
    data_dir: Path = DATA_DIR,
    *,
    base: list[Site] | None = None,
) -> dict[str, Any]:
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        if base is not None:
            _validate_base(base, spec)
        additions = compile_merimee_extension(spec)
        payload = original._bytes([site.model_dump(mode="json") for site in additions])
        if original._hash(payload) != SITES_SHA256:
            raise MerimeeExtensionError("compiled extension sites differ from independent pin")
        manifest = _manifest(spec, additions, payload)
        sites_path = original._output_path(directory, SITES_FILE)
        manifest_path = original._output_path(directory, MANIFEST_FILE)
        sites_path.write_bytes(payload)
        manifest_path.write_bytes(original._bytes(manifest))
        return manifest
    except MerimeeExtensionError:
        raise
    except (
        original.MerimeeError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
    ) as error:
        raise _public_error(error, "rebuild") from error


def load_merimee_extension(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        _validate_base(base, spec)
        additions = compile_merimee_extension(spec)
        payload = original._read_bounded(directory, SITES_FILE)
        if payload != original._bytes([s.model_dump(mode="json") for s in additions]) or (
            original._hash(payload) != SITES_SHA256
        ):
            raise MerimeeExtensionError("extension derivative differs from approved source facts")
        if original._bytes(json.loads(original._read_bounded(directory, MANIFEST_FILE))) != (
            original._bytes(_manifest(spec, additions, payload))
        ):
            raise MerimeeExtensionError("extension manifest differs from its frozen contract")
        return base + additions
    except MerimeeExtensionError:
        raise
    except (
        original.MerimeeError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
    ) as error:
        raise _public_error(error, "load") from error


def new_country_labels(directory: Path = DATA_DIR) -> dict[str, str]:
    try:
        return {area.code: area.name for area in _spec(Path(directory)).review.areas}
    except MerimeeExtensionError:
        raise
    except (
        original.MerimeeError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
    ) as error:
        raise _public_error(error, "load area labels for") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Replay this cohort's original selected CSV rows and API pages, never fetch."""
    try:
        spec = _spec(Path(data_dir))
        artifacts = _artifacts(spec)
        for artifact in artifacts.values():
            original._verify_hash(cache_dir, artifact)
        selected = {row.original_record_index: row for row in spec.roster.records}
        found: set[int] = set()
        total = 0
        with original._path(cache_dir, spec.roster.source_artifact.filename).open(
            encoding="utf-8-sig",
            newline="",
        ) as stream:
            reader = csv.DictReader(stream, delimiter="|", strict=True)
            if reader.fieldnames != list(original.SOURCE_FIELDS):
                raise MerimeeExtensionError("extension original78-field header/order differs")
            for index, fields in enumerate(reader, start=1):
                total += 1
                if index in selected:
                    if fields != selected[index].raw_fields:
                        raise MerimeeExtensionError("extension physical CSV record differs")
                    found.add(index)
        if total != FULL_SOURCE_COUNT or found != set(selected):
            raise MerimeeExtensionError("full CSV count or selected extension indices differ")
        pages: dict[str, Any] = {}
        for notice in spec.roster.records:
            receipt = notice.api_receipt
            if receipt.filename not in pages:
                pages[receipt.filename] = json.loads(
                    original._read_bounded(
                        cache_dir,
                        CACHE_PREFIX + receipt.filename,
                    )
                )
            row = pages[receipt.filename]["data"][receipt.array_index]
            if (
                original.compact_hash(row) != receipt.api_row_compact_sha256
                or row["__id"] != notice.original_record_index
                or {key: "" if row[key] is None else row[key] for key in original.SOURCE_FIELDS}
                != notice.raw_fields
            ):
                raise MerimeeExtensionError("extension API corroboration differs from original CSV")
        return len(artifacts)
    except MerimeeExtensionError:
        raise
    except (
        original.MerimeeError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        RecursionError,
        csv.Error,
    ) as error:
        raise _public_error(error, "verify source cache for") from error


def main() -> None:
    from archsearch.corpus import CorpusError, load_pre_merimee_extension_corpus

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
                            args.verify_source_cache,
                            args.data_dir,
                        )
                    }
                )
            )
        if args.rebuild:
            print(
                json.dumps(
                    rebuild_merimee_extension(
                        args.data_dir,
                        base=load_pre_merimee_extension_corpus(args.data_dir),
                    )["counts"]
                )
            )
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild and/or --verify-source-cache")
    except (MerimeeExtensionError, CorpusError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
