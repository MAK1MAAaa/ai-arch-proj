"""Append a small, independently verified set of named cultural places offline."""

from __future__ import annotations

import argparse
import hashlib
import json
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
            site.source_kind != "supplement" or site.types != ["historic-site"]
            or site.periods or site.period_evidence or site.geography is None
            or site.chronology.status != "reviewed" or site.location_precision is not None
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
    cohort_version: Literal["named-places-v1"]
    corpus_version: Literal["global-v19"]
    base_count: Literal[3897]
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


def _compile(base: list[Site], directory: Path) -> tuple[list[Site], bytes, dict[str, Any]]:
    raw = _read(directory / SPEC_FILE)
    if _hash(raw) != SPEC_SHA256:
        raise TargetDataError("named-place review differs from its independent checksum")
    spec = TargetSpec.model_validate_json(raw)
    if any(getattr(spec, key) != value for key, value in base_contract(base).items()):
        raise TargetDataError("named-place base identities or fields changed")
    additions = sorted((record.site for record in spec.records), key=lambda site: site.id)
    ids = [site.id for site in [*base, *additions]]
    if len(ids) != len(set(ids)):
        raise TargetDataError("named places duplicate an existing corpus identity")
    payload = _bytes([site.model_dump(mode="json") for site in additions])
    if _hash(payload) != SITES_SHA256:
        raise TargetDataError("named-place derivative differs from the reviewed checksum")
    manifest = {
        "schema_version": 1, "cohort_version": VERSION, "corpus_version": CORPUS_VERSION,
        **base_contract(base),
        "files": {SPEC_FILE: {"sha256": SPEC_SHA256},
                  SITES_FILE: {"sha256": SITES_SHA256}},
        "counts": {"added": len(additions), "total": len(base) + len(additions)},
        "selection": spec.selection,
        "processing": "Source-based bilingual summaries; no generated dates or coordinates. "
                      "Representative points retain their source scope; no inferred boundaries.",
    }
    return additions, payload, manifest


def load_targets(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Validate and append the frozen named-place cohort without reading source caches."""
    try:
        additions, payload, manifest = _compile(base, Path(data_dir))
        if (_read(Path(data_dir) / SITES_FILE) != payload
                or json.loads(_read(Path(data_dir) / MANIFEST_FILE)) != manifest):
            raise TargetDataError("named-place shipped files do not match their reviewed facts")
        return [*base, *additions]
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        raise TargetDataError("named-place evidence is absent or invalid") from error


def rebuild_targets(base: list[Site], data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Rebuild deterministic public artifacts from the compact, reviewed evidence."""
    _, payload, manifest = _compile(base, Path(data_dir))
    (data_dir / SITES_FILE).write_bytes(payload)
    (data_dir / MANIFEST_FILE).write_bytes(_bytes(manifest))
    return manifest


def main() -> None:
    from archsearch.corpus import load_pre_targets_corpus

    parser = argparse.ArgumentParser(description="重建已复核的专名地点资料")
    parser.add_argument("--output", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    print(json.dumps(rebuild_targets(load_pre_targets_corpus(), args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
