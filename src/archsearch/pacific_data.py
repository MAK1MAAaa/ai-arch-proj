"""Compile reviewed Pacific and African interior cultural facts without networking."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from archsearch.domain import Site
from archsearch.supplement_data import SourceArtifact, SupplementRecord, base_contract

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "pacific-interior-supplement-v1"
CORPUS_VERSION = "global-v10"
BASE_COUNT = 1800
SPEC_FILE = "pacific_review.json"
SITES_FILE = "pacific_sites.json"
MANIFEST_FILE = "pacific_manifest.json"
CANDIDATES_SHA256 = "acd3f49bb1e13aa51d28a03cf452a749cd8f76e21704608b77147382cfad1c6d"
INDEPENDENT_REVIEW_SHA256 = "84628016e43cf3c728fea158871d69b70448b01287db9ad9df251d77ab5bb3cf"
SPEC_SHA256 = "6ed31ae1c789ffd90fdff950e9103297800d4a1de20d2df22e12d57c1846d869"
SITES_SHA256 = "b8e1a4f6ffa85af0a97c7e9d943bb461ffe0d84db09b1fcb667e57026142b21a"
EXPECTED_GEOGRAPHY = MappingProxyType({
    "auth:nps-nris:83004524": ("FM", "asia-pacific"),
    "auth:whc-tentative:2066": ("MH", "asia-pacific"),
    "auth:palau-register:B.NE-4.4": ("PW", "asia-pacific"),
    "wd:Q19871758": ("PW", "asia-pacific"),
    "auth:whc-tentative:1375": ("FJ", "asia-pacific"),
    "auth:antiquity-projgall:clist347-ngongo-church": ("CD", "africa"),
    "auth:antiquity-projgall:clist347-kindoki": ("CD", "africa"),
})
EXPECTED_IDS = frozenset(EXPECTED_GEOGRAPHY)
EXPECTED_COUNTRIES = frozenset(country for country, _ in EXPECTED_GEOGRAPHY.values())
EXPECTED_POINT_IDS = frozenset({"wd:Q19871758"})


class PacificError(RuntimeError):
    """A reviewed source, independent approval or unchanged-base contract differs."""


class PacificRecord(SupplementRecord):
    @model_validator(mode="after")
    def validate_location_scope(self) -> PacificRecord:
        site = self.site
        geography = EXPECTED_GEOGRAPHY.get(site.id)
        if (
            geography is None or site.location_precision is not None or site.geography is None
            or site.geography.authority_id != "supplement:" + site.id
            or site.geography.countries != [geography[0]]
            or site.geography.regions != [geography[1]]
            or (site.repr_point is not None) != (site.id in EXPECTED_POINT_IDS)
            or site.geography.point_count != int(site.repr_point is not None)
        ):
            raise ValueError(
                "Pacific/interior identity, geography and adopted-point scope must remain"
            )
        if self.coordinate.method == "unknown" and any(value is not None for value in (
            self.coordinate.source_uri, self.coordinate.statement_id, self.coordinate.globe,
            self.coordinate.precision, self.coordinate.rank,
        )):
            raise ValueError("an unadopted coordinate cannot acquire positional metadata")
        return self


class PacificSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cohort_version: Literal["pacific-interior-supplement-v1"]
    corpus_version: Literal["global-v10"]
    base_count: Literal[1800]
    base_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_candidates_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: str = Field(min_length=1)
    records: list[PacificRecord] = Field(min_length=1)


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _spec(directory: Path) -> PacificSpec:
    payload = (directory / SPEC_FILE).read_bytes()
    if _hash(payload) != SPEC_SHA256:
        raise PacificError("Pacific review differs from its independent pin")
    spec = PacificSpec.model_validate_json(payload)
    if (
        spec.reviewed_candidates_sha256 != CANDIDATES_SHA256
        or spec.independent_report_sha256 != INDEPENDENT_REVIEW_SHA256
    ):
        raise PacificError("Pacific independent source-review binding differs")
    identifiers = [record.site.id for record in spec.records]
    countries = {code for record in spec.records if record.site.geography
                 for code in record.site.geography.countries}
    if len(identifiers) != len(set(identifiers)):
        raise PacificError("Pacific selection duplicates an identity")
    if set(identifiers) != EXPECTED_IDS or countries != EXPECTED_COUNTRIES:
        raise PacificError("Pacific selection differs from its reviewed cohort")
    artifacts: dict[str, SourceArtifact] = {}
    for record in spec.records:
        for artifact in record.source_files:
            if artifact.filename in artifacts and artifacts[artifact.filename] != artifact:
                raise PacificError("one source snapshot filename has conflicting contracts")
            artifacts[artifact.filename] = artifact
    return spec


def _ordered(spec: PacificSpec) -> list[PacificRecord]:
    return sorted(spec.records, key=lambda record: (
        hashlib.sha256((COHORT_VERSION + ":" + record.site.id).encode()).hexdigest(),
        record.site.id,
    ))


def _manifest(spec: PacificSpec, payload: bytes) -> dict[str, Any]:
    records = _ordered(spec)
    return {
        "schema_version": 1, "cohort_version": COHORT_VERSION, "corpus_version": CORPUS_VERSION,
        "base": {key: value for key, value in spec.model_dump().items() if key.startswith("base_")},
        "selection": spec.selection,
        "independent_source_review": {
            "candidates_sha256": spec.reviewed_candidates_sha256,
            "report_sha256": spec.independent_report_sha256,
            "scope": (
                "Independent source/identity/location/rights review; "
                "not chronology, expert or human archaeological approval."
            ),
        },
        "files": {SPEC_FILE: {"sha256": SPEC_SHA256}, SITES_FILE: {"sha256": _hash(payload)}},
        "counts": {
            "base": BASE_COUNT, "added": len(records), "total": BASE_COUNT + len(records),
            "countries": len(EXPECTED_COUNTRIES),
            "known_locations": sum(record.site.repr_point is not None for record in records),
            "no_adopted_coordinate": sum(record.site.repr_point is None for record in records),
        },
        "countries": sorted(EXPECTED_COUNTRIES),
        "records": [{
            "id": record.site.id, "coordinate": record.coordinate.model_dump(mode="json"),
            "identity_review": record.independent_review.model_dump(mode="json"),
            "source_files": [source.model_dump() for source in record.source_files],
        } for record in records],
        "chronology": (
            "All historical phases remain not_reviewed; "
            "no nomination, protection or publication date becomes a site phase."
        ),
        "licenses": "Wikidata metadata CC0; authority excerpts retain individual rights.",
    }


def rebuild_pacific(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Compile frozen reviewed facts without fetching or reinterpreting source pages."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        payload = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        if _hash(payload) != SITES_SHA256:
            raise PacificError("compiled Pacific sites differ from their independent pin")
        manifest = _manifest(spec, payload)
        (directory / SITES_FILE).write_bytes(payload)
        (directory / MANIFEST_FILE).write_bytes(_bytes(manifest))
        return manifest
    except PacificError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PacificError(f"cannot rebuild the Pacific supplement: {error}") from error


def load_pacific(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Append the reviewed records without rewriting the preceding1800 sites or search text."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        if base_contract(base) != {
            "base_count": spec.base_count, "base_ids_sha256": spec.base_ids_sha256,
            "base_sites_sha256": spec.base_sites_sha256,
        }:
            raise PacificError("Pacific base differs from the unchanged1800 contract")
        payload = (directory / SITES_FILE).read_bytes()
        expected = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        if payload != expected or _hash(payload) != SITES_SHA256:
            raise PacificError("Pacific sites differ from their reviewed facts")
        manifest = json.loads((directory / MANIFEST_FILE).read_bytes())
        if _bytes(manifest) != _bytes(_manifest(spec, payload)):
            raise PacificError("Pacific manifest differs from its frozen contract")
        additions = [record.site for record in _ordered(spec)]
        if {site.id for site in base} & {site.id for site in additions}:
            raise PacificError("Pacific supplement duplicates an existing identity")
        countries = {code for site in base if site.geography for code in site.geography.countries}
        regions = {code for site in base if site.geography for code in site.geography.regions}
        if any(
            site.geography is None or not set(site.geography.countries) <= countries
            or not set(site.geography.regions) <= regions for site in additions
        ):
            raise PacificError("Pacific geography exceeds the existing label registry")
        return base + additions
    except PacificError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PacificError(f"cannot load the Pacific supplement: {error}") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Verify optional cached evidence bytes without executing source documents."""
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
                    raise PacificError(f"source snapshot differs: {artifact.filename}")
                checked.add(artifact.filename)
        return len(checked)
    except PacificError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise PacificError(f"cannot verify Pacific source snapshots: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild reviewed Pacific/interior facts offline")
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
            print(json.dumps(rebuild_pacific(args.data_dir)["counts"]))
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild or --verify-source-cache")
    except PacificError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
