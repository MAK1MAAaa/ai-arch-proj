"""Compile independently source-reviewed South American cultural records offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from archsearch.domain import Site
from archsearch.supplement_data import SourceArtifact, SupplementRecord, base_contract

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "southamerica-supplement-v1"
CORPUS_VERSION = "global-v7"
BASE_COUNT = 1689
SPEC_FILE = "southamerica_review.json"
SITES_FILE = "southamerica_sites.json"
MANIFEST_FILE = "southamerica_manifest.json"
CANDIDATES_SHA256 = "c6883b889bb292a620c0da2dc8df7009aba006590e433e5f2820e76c2ec0157f"
INDEPENDENT_REVIEW_SHA256 = "85ac1964ebd7982d87e3a61e4a377b3927519a3004f0bb1c8ca2c0b1f09bbc6b"
DELEGATED_REVIEW_SHA256 = "b03903d24bd253cd4217d04ceb98f33c8a00b4cc5bd8be62faed4dbdd18eff38"
TRANSLATION_CANDIDATES_SHA256 = "8835b3fb6aafc35cbb37c3ca5a914e70c755fcbdb8c5daca6760719c70f7cf0a"
TRANSLATION_REVIEW_SHA256 = "1075f5a010804abb97a38392362f66f5438e2857f0c742bdcefaf2a8fa37531d"
SPEC_SHA256 = "b47a0025111eab092714ab8ee0311b25377b7390fd382b6f813663e457b64e56"
SITES_SHA256 = "45f46eb00e961592b45eb125a0dcc0f6d46094aec7dacaeb45dfb9a89a750dca"
EXPECTED_COUNTRIES = frozenset({"BO", "BR", "CL", "CO", "PE", "UY"})


class SouthAmericaError(RuntimeError):
    """A frozen source, independent review or unchanged-base contract differs."""


class SouthAmericaRecord(SupplementRecord):
    @model_validator(mode="after")
    def validate_location_scope(self) -> SouthAmericaRecord:
        site = self.site
        if (
            site.location_precision is not None or site.geography is None
            or site.geography.authority_id != "supplement:" + site.id
            or site.geography.regions != ["latin-america-caribbean"]
            or site.geography.point_count != int(site.repr_point is not None)
        ):
            raise ValueError("South America scope and unknown location precision must remain")
        if self.coordinate.method == "unknown" and any(value is not None for value in (
            self.coordinate.source_uri, self.coordinate.statement_id, self.coordinate.globe,
            self.coordinate.precision, self.coordinate.rank,
        )):
            raise ValueError("an unadopted coordinate cannot acquire positional metadata")
        return self


class SouthAmericaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cohort_version: Literal["southamerica-supplement-v1"]
    corpus_version: Literal["global-v7"]
    base_count: Literal[1689]
    base_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_candidates_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    delegated_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    translation_candidates_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    translation_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: str = Field(min_length=1)
    records: list[SouthAmericaRecord] = Field(min_length=1)


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _spec(directory: Path) -> SouthAmericaSpec:
    payload = (directory / SPEC_FILE).read_bytes()
    if _hash(payload) != SPEC_SHA256:
        raise SouthAmericaError("South America review differs from its independent pin")
    spec = SouthAmericaSpec.model_validate_json(payload)
    if (
        spec.reviewed_candidates_sha256 != CANDIDATES_SHA256
        or spec.independent_report_sha256 != INDEPENDENT_REVIEW_SHA256
        or spec.delegated_report_sha256 != DELEGATED_REVIEW_SHA256
        or spec.translation_candidates_sha256 != TRANSLATION_CANDIDATES_SHA256
        or spec.translation_report_sha256 != TRANSLATION_REVIEW_SHA256
    ):
        raise SouthAmericaError("South America independent source-review binding differs")
    identifiers = [record.site.id for record in spec.records]
    countries = {code for record in spec.records if record.site.geography
                 for code in record.site.geography.countries}
    if len(identifiers) != len(set(identifiers)):
        raise SouthAmericaError("South America selection duplicates an identity")
    if len(identifiers) != 11 or countries != EXPECTED_COUNTRIES:
        raise SouthAmericaError("South America selection differs from its reviewed cohort")
    artifacts: dict[str, SourceArtifact] = {}
    for record in spec.records:
        for artifact in record.source_files:
            if artifact.filename in artifacts and artifacts[artifact.filename] != artifact:
                raise SouthAmericaError("one source snapshot filename has conflicting contracts")
            artifacts[artifact.filename] = artifact
    return spec


def _ordered(spec: SouthAmericaSpec) -> list[SouthAmericaRecord]:
    return sorted(spec.records, key=lambda record: (
        hashlib.sha256((COHORT_VERSION + ":" + record.site.id).encode()).hexdigest(),
        record.site.id,
    ))


def _manifest(spec: SouthAmericaSpec, payload: bytes) -> dict[str, Any]:
    records = _ordered(spec)
    return {
        "schema_version": 1, "cohort_version": COHORT_VERSION, "corpus_version": CORPUS_VERSION,
        "base": {key: value for key, value in spec.model_dump().items() if key.startswith("base_")},
        "selection": spec.selection,
        "independent_source_review": {
            "candidates_sha256": spec.reviewed_candidates_sha256,
            "report_sha256": spec.independent_report_sha256,
            "delegated_report_sha256": spec.delegated_report_sha256,
            "translation_candidates_sha256": spec.translation_candidates_sha256,
            "translation_report_sha256": spec.translation_report_sha256,
            "scope": (
                "Independent source/identity/location/rights review; "
                "not chronology or expert approval."
            ),
        },
        "files": {SPEC_FILE: {"sha256": SPEC_SHA256}, SITES_FILE: {"sha256": _hash(payload)}},
        "counts": {
            "base": BASE_COUNT, "added": len(records), "total": BASE_COUNT + len(records),
            "countries": len(EXPECTED_COUNTRIES),
            "known_locations": sum(record.site.repr_point is not None for record in records),
            "no_verified_coordinate": sum(record.site.repr_point is None for record in records),
        },
        "countries": sorted(EXPECTED_COUNTRIES),
        "records": [{
            "id": record.site.id, "coordinate": record.coordinate.model_dump(mode="json"),
            "identity_review": record.independent_review.model_dump(mode="json"),
            "source_files": [source.model_dump() for source in record.source_files],
        } for record in records],
        "chronology": (
            "All historical phases remain not_reviewed; "
            "no nomination or discovery date becomes a site phase."
        ),
        "licenses": (
            "Wikidata metadata CC0; PLOS author article CC BY4.0; "
            "other authority excerpts retain individual rights."
        ),
    }


def rebuild_southamerica(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Compile frozen reviewed facts; do not fetch or reinterpret authority pages."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        payload = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        if _hash(payload) != SITES_SHA256:
            raise SouthAmericaError("compiled South America sites differ from their source pin")
        manifest = _manifest(spec, payload)
        (directory / SITES_FILE).write_bytes(payload)
        (directory / MANIFEST_FILE).write_bytes(_bytes(manifest))
        return manifest
    except SouthAmericaError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SouthAmericaError(f"cannot rebuild the South America supplement: {error}") from error


def load_southamerica(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Append the reviewed records without rewriting the preceding1689 records or text."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        if base_contract(base) != {
            "base_count": spec.base_count, "base_ids_sha256": spec.base_ids_sha256,
            "base_sites_sha256": spec.base_sites_sha256,
        }:
            raise SouthAmericaError("South America base differs from the unchanged1689 contract")
        payload = (directory / SITES_FILE).read_bytes()
        expected = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        if payload != expected or _hash(payload) != SITES_SHA256:
            raise SouthAmericaError("South America sites differ from their reviewed facts")
        manifest = json.loads((directory / MANIFEST_FILE).read_bytes())
        if _bytes(manifest) != _bytes(_manifest(spec, payload)):
            raise SouthAmericaError("South America manifest differs from its frozen contract")
        additions = [record.site for record in _ordered(spec)]
        if {site.id for site in base} & {site.id for site in additions}:
            raise SouthAmericaError("South America supplement duplicates an existing identity")
        countries = {code for site in base if site.geography for code in site.geography.countries}
        regions = {code for site in base if site.geography for code in site.geography.regions}
        if any(
            site.geography is None or not set(site.geography.countries) <= countries
            or not set(site.geography.regions) <= regions for site in additions
        ):
            raise SouthAmericaError("South America geography exceeds the existing label registry")
        return base + additions
    except SouthAmericaError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SouthAmericaError(f"cannot load the South America supplement: {error}") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Verify optional cached evidence bytes without running source documents."""
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
                    raise SouthAmericaError(f"source snapshot differs: {artifact.filename}")
                checked.add(artifact.filename)
        return len(checked)
    except SouthAmericaError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise SouthAmericaError(f"cannot verify South America source snapshots: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild reviewed South America facts offline")
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
            print(json.dumps(rebuild_southamerica(args.data_dir)["counts"]))
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild or --verify-source-cache")
    except SouthAmericaError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
