"""Compile independently reviewed African cultural identities without runtime networking."""

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
COHORT_VERSION = "africa-supplement-v1"
CORPUS_VERSION = "global-v9"
BASE_COUNT = 1795
SPEC_FILE = "africa_review.json"
SITES_FILE = "africa_sites.json"
MANIFEST_FILE = "africa_manifest.json"
CANDIDATES_SHA256 = "bafb01060cf5abb6f87662edb238ce1f5d2e30497fa33d6dee356822583f922d"
INDEPENDENT_REVIEW_SHA256 = "00cffa1fd91d20af0f6b12b891379ef817b3f19ab534256c722e0aa55750663c"
SPEC_SHA256 = "b3de78f6b0db17c347da2028b351cfae140b9bc5eb15bac871f477986fbca1df"
SITES_SHA256 = "31ae3d3ca8076e4f1159008ae766fd922dd2483614873fe9474a94192b2165a6"
EXPECTED_COUNTRIES = frozenset({"AO", "CD", "CM", "NE"})
EXPECTED_IDS = frozenset(
    "auth:whc-tentative:" + identifier for identifier in ("961", "6251", "5045", "5044", "6320")
)


class AfricaError(RuntimeError):
    """A reviewed source, independent approval or unchanged-base contract differs."""


class AfricaRecord(SupplementRecord):
    @model_validator(mode="after")
    def validate_location_scope(self) -> AfricaRecord:
        site = self.site
        if (
            site.location_precision is not None or site.geography is None
            or site.geography.authority_id != "supplement:" + site.id
            or site.geography.regions != ["africa"]
            or site.geography.point_count != int(site.repr_point is not None)
        ):
            raise ValueError("African scope and unknown location precision must remain")
        if self.coordinate.method == "unknown" and any(value is not None for value in (
            self.coordinate.source_uri, self.coordinate.statement_id, self.coordinate.globe,
            self.coordinate.precision, self.coordinate.rank,
        )):
            raise ValueError("an unadopted coordinate cannot acquire positional metadata")
        return self


class AfricaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cohort_version: Literal["africa-supplement-v1"]
    corpus_version: Literal["global-v9"]
    base_count: Literal[1795]
    base_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_candidates_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: str = Field(min_length=1)
    records: list[AfricaRecord] = Field(min_length=1)


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _spec(directory: Path) -> AfricaSpec:
    payload = (directory / SPEC_FILE).read_bytes()
    if _hash(payload) != SPEC_SHA256:
        raise AfricaError("Africa review differs from its independent pin")
    spec = AfricaSpec.model_validate_json(payload)
    if (
        spec.reviewed_candidates_sha256 != CANDIDATES_SHA256
        or spec.independent_report_sha256 != INDEPENDENT_REVIEW_SHA256
    ):
        raise AfricaError("Africa independent source-review binding differs")
    identifiers = [record.site.id for record in spec.records]
    countries = {code for record in spec.records if record.site.geography
                 for code in record.site.geography.countries}
    if len(identifiers) != len(set(identifiers)):
        raise AfricaError("Africa selection duplicates an identity")
    if set(identifiers) != EXPECTED_IDS or countries != EXPECTED_COUNTRIES:
        raise AfricaError("Africa selection differs from its reviewed cohort")
    artifacts: dict[str, SourceArtifact] = {}
    for record in spec.records:
        for artifact in record.source_files:
            if artifact.filename in artifacts and artifacts[artifact.filename] != artifact:
                raise AfricaError("one source snapshot filename has conflicting contracts")
            artifacts[artifact.filename] = artifact
    return spec


def _ordered(spec: AfricaSpec) -> list[AfricaRecord]:
    return sorted(spec.records, key=lambda record: (
        hashlib.sha256((COHORT_VERSION + ":" + record.site.id).encode()).hexdigest(),
        record.site.id,
    ))


def _manifest(spec: AfricaSpec, payload: bytes) -> dict[str, Any]:
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


def rebuild_africa(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Compile frozen reviewed facts without fetching or reinterpreting source pages."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        payload = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        if _hash(payload) != SITES_SHA256:
            raise AfricaError("compiled Africa sites differ from their independent pin")
        manifest = _manifest(spec, payload)
        (directory / SITES_FILE).write_bytes(payload)
        (directory / MANIFEST_FILE).write_bytes(_bytes(manifest))
        return manifest
    except AfricaError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise AfricaError(f"cannot rebuild the Africa supplement: {error}") from error


def load_africa(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Append the reviewed records without rewriting the preceding1795 sites or search text."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        if base_contract(base) != {
            "base_count": spec.base_count, "base_ids_sha256": spec.base_ids_sha256,
            "base_sites_sha256": spec.base_sites_sha256,
        }:
            raise AfricaError("Africa base differs from the unchanged1795 contract")
        payload = (directory / SITES_FILE).read_bytes()
        expected = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        if payload != expected or _hash(payload) != SITES_SHA256:
            raise AfricaError("Africa sites differ from their reviewed facts")
        manifest = json.loads((directory / MANIFEST_FILE).read_bytes())
        if _bytes(manifest) != _bytes(_manifest(spec, payload)):
            raise AfricaError("Africa manifest differs from its frozen contract")
        additions = [record.site for record in _ordered(spec)]
        if {site.id for site in base} & {site.id for site in additions}:
            raise AfricaError("Africa supplement duplicates an existing identity")
        countries = {code for site in base if site.geography for code in site.geography.countries}
        regions = {code for site in base if site.geography for code in site.geography.regions}
        if any(
            site.geography is None or not set(site.geography.countries) <= countries
            or not set(site.geography.regions) <= regions for site in additions
        ):
            raise AfricaError("Africa geography exceeds the existing label registry")
        return base + additions
    except AfricaError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise AfricaError(f"cannot load the Africa supplement: {error}") from error


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
                    raise AfricaError(f"source snapshot differs: {artifact.filename}")
                checked.add(artifact.filename)
        return len(checked)
    except AfricaError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise AfricaError(f"cannot verify Africa source snapshots: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild reviewed African cultural facts offline")
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
            print(json.dumps(rebuild_africa(args.data_dir)["counts"]))
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild or --verify-source-cache")
    except AfricaError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
