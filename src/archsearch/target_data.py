"""Append a small, independently verified set of named cultural places offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from archsearch.domain import Site
from archsearch.supplement_data import (
    CoordinateEvidence,
    IdentityReview,
    SourceArtifact,
    base_contract,
)

DATA_DIR = Path(__file__).with_name("data")
VERSION = "named-places-v1"
CORPUS_VERSION = "global-v19"
SPEC_FILE = "target_review.json"
SITES_FILE = "target_sites.json"
MANIFEST_FILE = "target_manifest.json"
SPEC_SHA256 = "636dd971a74da8e0bfd92028fedf7a29a696c318a761913e6900709800fbe9b0"
SITES_SHA256 = "6764fe78b83500fe5a7b58a270c329d52d31ee51d42b096a8df024d0d4f129d3"
MAX_ARTIFACT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class NamedPlaceCohort:
    version: str
    corpus_version: str
    file_prefix: str
    review_sha256: str
    sites_sha256: str
    country_labels: tuple[tuple[str, str], ...] = ()

    @property
    def filenames(self) -> tuple[str, str, str]:
        prefix = self.file_prefix
        return f"{prefix}_review.json", f"{prefix}_sites.json", f"{prefix}_manifest.json"


ORIGINAL = NamedPlaceCohort(VERSION, CORPUS_VERSION, "target", SPEC_SHA256, SITES_SHA256)
GUYANA = NamedPlaceCohort(
    "guyana-named-places-v1",
    "global-v20",
    "guyana",
    "b60e4d13bd63e7ea1a74085a4931925fba0c7910d76778497346819923618904",
    "42309086e8ed2a5f01f92e68d6bd09529dc28ea5b75d2946348fb578a5831a80",
)
IRELAND = NamedPlaceCohort(
    "ireland-public-monuments-v1",
    "global-v21",
    "ireland_nms",
    "be4cfaff8cb0aec3818dabf42eecda07b0fe3635439bbe9912988c9782deeb99",
    "323e9e5300416db7337fb177df017b60f6d35edddbd7970168c86537b17c7902",
)
ANDALUCIA = NamedPlaceCohort(
    "andalucia-reca-v1",
    "global-v21",
    "andalucia_reca",
    "b518958cec6782751bb246d32979c06b9186c493171bcc783defc73e2c6bdc75",
    "35fff33b680ce7a40991976fee121bd0beeeba1800d09c82b8be04984c87f321",
)
TAIWAN_ICULTURE = NamedPlaceCohort(
    "taiwan-iculture-v1",
    "global-v21",
    "taiwan_iculture",
    "0ddff3d9dd12b60cc7f54d23fef8c10ab4d514723c9f0119422fdf80db193075",
    "860b2e16629089779e33699a8ba7f6bd06c3fdc020e934c88bc8ce824e4bb8ca",
    country_labels=(("TW", "Taiwan"),),
)
MEXICO_SIC = NamedPlaceCohort(
    "mexico-sic-public-archaeology-v1",
    "global-v21",
    "mexico_sic",
    "45793ce985a6ba2dd4035c9b58d7786943872ee5287a97d4f77c18162fbd08b4",
    "9f1b3d27dfcfe2ed2b631e9f3cd140c8c660425fa4d2e5d4b2e46d7a87753286",
)
POINT_COHORTS = (IRELAND, ANDALUCIA, TAIWAN_ICULTURE, MEXICO_SIC)


class TargetDataError(RuntimeError):
    """Named-place evidence or its frozen base corpus differs from its reviewed snapshot."""


class TargetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    site: Site
    coordinate: CoordinateEvidence
    independent_review: IdentityReview
    source_files: list[SourceArtifact] = Field(min_length=1)
    scope_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence(self) -> TargetRecord:
        site = self.site
        if (
            site.source_kind != "supplement"
            or site.types not in (["historic-site"], ["archaeological-site"])
            or site.periods or site.period_evidence or site.geography is None
            or site.chronology.status == "not_reviewed" or site.location_precision is not None
            or site.repr_point != self.coordinate.point
        ):
            raise ValueError("named places need their own reviewed scope, point and event evidence")
        if self.coordinate.source_uri is not None and not any(
            ref.uri == self.coordinate.source_uri for ref in site.source_refs
        ):
            raise ValueError("the representative point must retain its public source")
        artifacts = {artifact.uri for artifact in self.source_files}
        references = [*site.source_refs, *(source for phase in site.chronology.phases
                                         for source in phase.sources), site.geography.source]
        if any(ref.uri not in artifacts for ref in references):
            raise ValueError("all public source references need a checksummed retrieved artifact")
        excerpts: dict[str, set[str]] = {}
        for ref in references:
            if ref.license not in {"CC0", "CC0-1.0", "CC BY 4.0", "CC BY-SA 4.0"}:
                excerpts.setdefault(ref.uri, set()).add(ref.excerpt)
        if any(sum(len(text.split()) for text in texts) > 25 for texts in excerpts.values()):
            raise ValueError("short authority excerpts must stay within25 words per source")
        return self


class TargetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    cohort_version: str
    corpus_version: str
    base_count: int = Field(gt=0)
    base_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: str = Field(min_length=1)
    records: list[TargetRecord] = Field(min_length=1)


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise TargetDataError("named-place artifact exceeds its compact snapshot limit")
    return raw


def _compile(
    base: list[Site], directory: Path, cohort: NamedPlaceCohort,
) -> tuple[list[Site], bytes, dict[str, Any]]:
    spec_file, sites_file, _ = cohort.filenames
    raw = _read(directory / spec_file)
    if _hash(raw) != cohort.review_sha256:
        raise TargetDataError("named-place review differs from its independent checksum")
    spec = TargetSpec.model_validate_json(raw)
    if (spec.cohort_version, spec.corpus_version) != (cohort.version, cohort.corpus_version):
        raise TargetDataError("named-place review belongs to another cohort or corpus version")
    base_facts = base_contract(base)
    if any(getattr(spec, key) != value for key, value in base_facts.items()):
        raise TargetDataError("named-place base identities or fields changed")
    additions = sorted((record.site for record in spec.records), key=lambda site: site.id)
    ids = [site.id for site in [*base, *additions]]
    if len(ids) != len(set(ids)):
        raise TargetDataError("named places duplicate an existing corpus identity")
    payload = _bytes([site.model_dump(mode="json") for site in additions])
    if _hash(payload) != cohort.sites_sha256:
        raise TargetDataError("named-place derivative differs from the reviewed checksum")
    manifest = {
        "schema_version": 1, "cohort_version": cohort.version,
        "corpus_version": cohort.corpus_version,
        **base_facts,
        "files": {spec_file: {"sha256": cohort.review_sha256},
                  sites_file: {"sha256": cohort.sites_sha256}},
        "counts": {"added": len(additions), "total": len(base) + len(additions)},
        "selection": spec.selection,
        "processing": "Source-based bilingual summaries; no generated dates or coordinates. "
                      "Representative points retain their source scope; no inferred boundaries.",
    }
    return additions, payload, manifest


def load_targets(
    base: list[Site], data_dir: Path = DATA_DIR, *, cohort: NamedPlaceCohort = ORIGINAL,
) -> list[Site]:
    """Validate and append the frozen named-place cohort without reading source caches."""
    try:
        _, sites_file, manifest_file = cohort.filenames
        additions, payload, manifest = _compile(base, data_dir, cohort)
        if (_read(data_dir / sites_file) != payload
                or json.loads(_read(data_dir / manifest_file)) != manifest):
            raise TargetDataError("named-place shipped files do not match their reviewed facts")
        return [*base, *additions]
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        raise TargetDataError("named-place evidence is absent or invalid") from error


def rebuild_targets(
    base: list[Site], data_dir: Path = DATA_DIR, *, cohort: NamedPlaceCohort = ORIGINAL,
) -> dict[str, Any]:
    """Rebuild deterministic public artifacts from the compact, reviewed evidence."""
    _, sites_file, manifest_file = cohort.filenames
    _, payload, manifest = _compile(base, data_dir, cohort)
    (data_dir / sites_file).write_bytes(payload)
    (data_dir / manifest_file).write_bytes(_bytes(manifest))
    return manifest


def main() -> None:
    from archsearch.corpus import (
        load_guyana_corpus,
        load_named_places_v1_corpus,
        load_pre_targets_corpus,
    )

    parser = argparse.ArgumentParser(description="重建已复核的专名地点资料")
    parser.add_argument("--output", type=Path, default=DATA_DIR)
    batches = parser.add_mutually_exclusive_group()
    batches.add_argument("--guyana", action="store_true", help="重建圭亚那批次")
    batches.add_argument(
        "--cohort", choices=[cohort.file_prefix for cohort in POINT_COHORTS],
        help="重建指定的公共点位批次",
    )
    args = parser.parse_args()
    if args.cohort:
        base = load_guyana_corpus()
        for cohort in POINT_COHORTS:
            if cohort.file_prefix == args.cohort:
                break
            base = load_targets(base, cohort=cohort)
    elif args.guyana:
        base, cohort = load_named_places_v1_corpus(), GUYANA
    else:
        base, cohort = load_pre_targets_corpus(), ORIGINAL
    print(json.dumps(rebuild_targets(base, args.output, cohort=cohort),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
