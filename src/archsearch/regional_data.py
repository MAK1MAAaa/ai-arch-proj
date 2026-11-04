"""Deterministic, independently reviewed additions for sparse geographic regions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from archsearch.domain import Site
from archsearch.supplement_data import SourceArtifact, SupplementRecord, base_contract

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "regional-supplement-v1"
CORPUS_VERSION = "global-v6"
BASE_COUNT = 1663
SPEC_FILE = "regional_supplement_review.json"
SITES_FILE = "regional_sites.json"
MANIFEST_FILE = "regional_manifest.json"
SPEC_SHA256 = "d81bf00c9fbfd7f33557a63db3f3b577da93516d3f52cccf107df6af73386060"
SITES_SHA256 = "ec4c7158a45c65bf12391923ccaef098ec51a66d214009bfb96f689b670ff384"


class RegionalError(RuntimeError):
    """A reviewed regional source contract or its unchanged base is inconsistent."""


class RegionalRecord(SupplementRecord):
    focus: Literal["northern", "islands-interior"]


class RegionalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cohort_version: Literal["regional-supplement-v1"]
    corpus_version: Literal["global-v6"]
    base_count: Literal[1663]
    base_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: str = Field(min_length=1)
    records: list[RegionalRecord] = Field(min_length=1)


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _spec(directory: Path) -> RegionalSpec:
    payload = (directory / SPEC_FILE).read_bytes()
    if _hash(payload) != SPEC_SHA256:
        raise RegionalError("regional review differs from its independent pin")
    spec = RegionalSpec.model_validate_json(payload)
    identifiers = [record.site.id for record in spec.records]
    if len(identifiers) != len(set(identifiers)):
        raise RegionalError("regional selection duplicates an identity")
    if {record.focus for record in spec.records} != {"northern", "islands-interior"}:
        raise RegionalError("regional selection must preserve both reviewed geographic focuses")
    artifacts: dict[str, SourceArtifact] = {}
    for record in spec.records:
        for artifact in record.source_files:
            if artifact.filename in artifacts and artifacts[artifact.filename] != artifact:
                raise RegionalError("one source snapshot filename has conflicting contracts")
            artifacts[artifact.filename] = artifact
    return spec


def _ordered(spec: RegionalSpec) -> list[RegionalRecord]:
    return sorted(spec.records, key=lambda record: (
        hashlib.sha256((COHORT_VERSION + ":" + record.site.id).encode()).hexdigest(),
        record.site.id,
    ))


def _manifest(spec: RegionalSpec, payload: bytes) -> dict[str, Any]:
    records = _ordered(spec)
    return {
        "schema_version": 1, "cohort_version": COHORT_VERSION, "corpus_version": CORPUS_VERSION,
        "base": {key: value for key, value in spec.model_dump().items() if key.startswith("base_")},
        "selection": spec.selection,
        "files": {SPEC_FILE: {"sha256": SPEC_SHA256}, SITES_FILE: {"sha256": _hash(payload)}},
        "counts": {
            "base": BASE_COUNT, "added": len(records), "total": BASE_COUNT + len(records),
            "known_locations": sum(record.site.repr_point is not None for record in records),
            "no_verified_coordinate": sum(record.site.repr_point is None for record in records),
            "northern": sum(record.focus == "northern" for record in records),
            "islands_interior": sum(record.focus == "islands-interior" for record in records),
        },
        "records": [{
            "id": record.site.id, "focus": record.focus,
            "coordinate": record.coordinate.model_dump(mode="json"),
            "identity_review": record.independent_review.model_dump(mode="json"),
            "source_files": [source.model_dump() for source in record.source_files],
        } for record in records],
        "chronology": "Identity/location review only; no historical phase is inferred.",
        "licenses": "Structured fields and authority excerpts retain their individual rights.",
    }


def rebuild_regional(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Compile reviewed facts offline; source pages are not fetched or reinterpreted."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        payload = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        if _hash(payload) != SITES_SHA256:
            raise RegionalError("compiled regional sites differ from their independent pin")
        manifest = _manifest(spec, payload)
        (directory / SITES_FILE).write_bytes(payload)
        (directory / MANIFEST_FILE).write_bytes(_bytes(manifest))
        return manifest
    except RegionalError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RegionalError(f"cannot rebuild the regional supplement: {error}") from error


def load_regional(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Append identities without rewriting any of the1663 earlier records or documents."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        if base_contract(base) != {
            "base_count": spec.base_count, "base_ids_sha256": spec.base_ids_sha256,
            "base_sites_sha256": spec.base_sites_sha256,
        }:
            raise RegionalError("regional base differs from the unchanged1663 contract")
        payload = (directory / SITES_FILE).read_bytes()
        expected = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        if payload != expected or _hash(payload) != SITES_SHA256:
            raise RegionalError("regional sites differ from their reviewed facts")
        manifest = json.loads((directory / MANIFEST_FILE).read_bytes())
        if _bytes(manifest) != _bytes(_manifest(spec, payload)):
            raise RegionalError("regional manifest differs from its frozen contract")
        additions = [record.site for record in _ordered(spec)]
        if {site.id for site in base} & {site.id for site in additions}:
            raise RegionalError("regional supplement duplicates an existing identity")
        countries = {code for site in base if site.geography for code in site.geography.countries}
        regions = {code for site in base if site.geography for code in site.geography.regions}
        if any(
            site.geography is None or not set(site.geography.countries) <= countries
            or not set(site.geography.regions) <= regions for site in additions
        ):
            raise RegionalError("regional source geography is outside the existing label registry")
        return base + additions
    except RegionalError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RegionalError(f"cannot load the regional supplement: {error}") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Verify archived evidence bytes without downloading or executing source documents."""
    try:
        spec = _spec(Path(data_dir))
        root = Path(cache_dir).resolve()
        checked: set[str] = set()
        for record in spec.records:
            for artifact in record.source_files:
                if artifact.filename in checked:
                    continue
                path = (root / artifact.filename).resolve()
                if not path.is_relative_to(root) or _hash(path.read_bytes()) != artifact.sha256:
                    raise RegionalError(f"regional source snapshot differs: {artifact.filename}")
                checked.add(artifact.filename)
        return len(checked)
    except RegionalError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise RegionalError(f"cannot verify regional source snapshots: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild reviewed regional culture facts offline")
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
            print(json.dumps(rebuild_regional(args.data_dir)["counts"]))
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild or --verify-source-cache")
    except (RegionalError, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
