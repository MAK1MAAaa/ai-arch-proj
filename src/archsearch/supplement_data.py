"""Compile and validate a source-reviewed country supplement without runtime networking."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from archsearch.domain import Site

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "country-supplement-v1"
CORPUS_VERSION = "global-v5"
BASE_COUNT = 1625
SPEC_FILE = "country_supplement_review.json"
SITES_FILE = "supplement_sites.json"
MANIFEST_FILE = "supplement_manifest.json"
SPEC_SHA256 = "71365cf8fc4fadabdbe9d30f9dc966f2969dc6a219bee6a52610e44e7cb45c2d"
SITES_SHA256 = "b1aac96510bd46942f4ed7925f08cc83a568f7d2f6ee653b34aa8ce2653aa1fb"
EXPECTED_COUNTRIES = frozenset(
    "BI BN BS BT BZ CD CF CG CK DJ DM GD GN GQ GW GY KI KW LC LI LR MC MV NR NU "
    "SB SC SL SO SS SZ TL TO TT TV VC WS ZM".split()
)


class SupplementError(RuntimeError):
    """Frozen supplemental identity, geography, source or review evidence is inconsistent."""


class SourceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    filename: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    uri: str

    @model_validator(mode="after")
    def validate_path(self) -> SourceArtifact:
        paths = (PurePosixPath(self.filename), PureWindowsPath(self.filename))
        if any(
            path.is_absolute() or path.drive or path.root or ".." in path.parts or not path.parts
            for path in paths
        ):
            raise ValueError("source cache filename must remain inside the chosen cache directory")
        parts = urlsplit(self.uri)
        if (
            parts.scheme not in {"http", "https"} or not parts.netloc
            or parts.username is not None or parts.password is not None
        ):
            raise ValueError("source artifact requires a public HTTP(S) origin")
        return self


class IdentityReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["approved"]
    reviewer: str = Field(min_length=1)
    method: str = Field(min_length=1)
    reviewed_at: str

    @model_validator(mode="after")
    def validate_date(self) -> IdentityReview:
        if date.fromisoformat(self.reviewed_at).isoformat() != self.reviewed_at:
            raise ValueError("identity review requires an ISO date")
        if not self.reviewer.strip() or not self.method.strip():
            raise ValueError("identity review requires a named method and reviewer")
        return self


class CoordinateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    method: Literal["wikidata", "authority", "unknown"]
    point: tuple[float, float] | None
    source_uri: str | None
    statement_id: str | None = None
    globe: str | None = None
    precision: float | None = None
    rank: str | None = None
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_coordinate_origin(self) -> CoordinateEvidence:
        if self.method == "unknown":
            if self.point is not None:
                raise ValueError("unknown source location cannot gain a substitute coordinate")
        elif self.point is None or not self.source_uri:
            raise ValueError("known location requires its own coordinate source")
        if self.method == "wikidata" and (
            not self.statement_id or self.globe not in {
                "http://www.wikidata.org/entity/Q2", "https://www.wikidata.org/entity/Q2",
            } or self.rank not in {"normal", "preferred"}
        ):
            raise ValueError("Wikidata point requires a selected active Earth statement")
        if self.precision is not None and (
            not math.isfinite(self.precision) or self.precision < 0
        ):
            raise ValueError("invalid source precision cannot be relabelled as precise")
        return self


class SupplementRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    site: Site
    country_label: str = Field(min_length=1)
    coordinate: CoordinateEvidence
    independent_review: IdentityReview
    source_files: list[SourceArtifact] = Field(min_length=1)
    provenance: dict[str, Any]

    @model_validator(mode="after")
    def validate_reviewed_record(self) -> SupplementRecord:
        site = self.site
        if (
            site.source_kind != "supplement" or site.geography is None
            or len(site.geography.countries) != 1 or len(site.geography.regions) != 1
            or site.geography.regions == ["antarctica"]
            or site.types != ["historic-site"] or site.periods or site.period_evidence
            or site.chronology.status != "not_reviewed" or site.chronology.phases
            or site.chronology.default_phase_id is not None
        ):
            raise ValueError("supplement identity and unreviewed chronology must be preserved")
        if site.repr_point != self.coordinate.point:
            raise ValueError("representative point differs from its selected source evidence")
        if self.coordinate.source_uri and not any(
            source.uri == self.coordinate.source_uri for source in site.source_refs
        ):
            raise ValueError("selected point source is absent from the public record references")
        if not any(
            source.excerpt.strip() and source.license not in {"CC0", "CC0-1.0"}
            for source in site.source_refs
        ):
            raise ValueError("a Wikidata identity alone cannot establish cultural qualification")
        excerpts: dict[str, set[str]] = {}
        for source in site.source_refs:
            if source.license not in {"CC0", "CC0-1.0", "CC BY 4.0", "CC BY-SA 4.0"}:
                excerpts.setdefault(source.uri, set()).add(source.excerpt)
        if any(sum(len(text.split()) for text in texts) > 25 for texts in excerpts.values()):
            raise ValueError("authority excerpts exceed the source's short-quotation limit")
        return self


class SupplementSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    cohort_version: Literal["country-supplement-v1"]
    corpus_version: Literal["global-v5"]
    base_count: Literal[1625]
    base_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: str = Field(min_length=1)
    records: list[SupplementRecord]


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def base_contract(sites: list[Site]) -> dict[str, str | int]:
    return {
        "base_count": len(sites),
        "base_ids_sha256": _hash(_bytes([site.id for site in sites])),
        "base_sites_sha256": _hash(_bytes([site.model_dump(mode="json") for site in sites])),
    }


def _spec(directory: Path) -> SupplementSpec:
    payload = (directory / SPEC_FILE).read_bytes()
    if _hash(payload) != SPEC_SHA256:
        raise SupplementError("country supplement review differs from its independent pin")
    spec = SupplementSpec.model_validate_json(payload)
    ids = [record.site.id for record in spec.records]
    countries = [record.site.geography.countries[0] for record in spec.records
                 if record.site.geography]
    if (
        len(ids) != len(set(ids)) or set(countries) != EXPECTED_COUNTRIES
        or len(countries) != len(EXPECTED_COUNTRIES)
    ):
        raise SupplementError("country supplement selection is incomplete or duplicates identities")
    return spec


def _ordered(spec: SupplementSpec) -> list[SupplementRecord]:
    return sorted(spec.records, key=lambda record: (
        hashlib.sha256((COHORT_VERSION + ":" + record.site.id).encode()).hexdigest(),
        record.site.id,
    ))


def _manifest(spec: SupplementSpec, sites_payload: bytes) -> dict[str, Any]:
    records = _ordered(spec)
    return {
        "schema_version": 1, "cohort_version": COHORT_VERSION, "corpus_version": CORPUS_VERSION,
        "base": {key: value for key, value in spec.model_dump().items() if key.startswith("base_")},
        "selection": spec.selection,
        "files": {
            SPEC_FILE: {"sha256": SPEC_SHA256}, SITES_FILE: {"sha256": _hash(sites_payload)},
        },
        "counts": {
            "base": BASE_COUNT, "added": len(records), "countries": len(EXPECTED_COUNTRIES),
            "total": BASE_COUNT + len(records),
            "known_locations": sum(record.site.repr_point is not None for record in records),
            "unknown_locations": sum(record.site.repr_point is None for record in records),
        },
        "countries": sorted([
            {"id": record.site.geography.countries[0], "label": record.country_label}
            for record in records if record.site.geography
        ], key=lambda row: row["id"]),
        "records": [{
            "id": record.site.id, "countries": record.site.geography.countries,
            "regions": record.site.geography.regions,
            "coordinate": record.coordinate.model_dump(mode="json"),
            "identity_review": record.independent_review.model_dump(mode="json"),
            "source_files": [source.model_dump() for source in record.source_files],
        } for record in records if record.site.geography],
        "chronology": "Identity/location review only; no new historical phase is inferred.",
        "licenses": "Wikidata fields CC0; authority excerpts retain individual rights.",
    }


def rebuild_supplement(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Compile the frozen reviewed fact specification, without fetching source pages."""
    try:
        spec = _spec(Path(data_dir))
        payload = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        if _hash(payload) != SITES_SHA256:
            raise SupplementError("compiled supplement differs from its independent site pin")
        manifest = _manifest(spec, payload)
        (Path(data_dir) / SITES_FILE).write_bytes(payload)
        (Path(data_dir) / MANIFEST_FILE).write_bytes(_bytes(manifest))
        return manifest
    except SupplementError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SupplementError(f"cannot rebuild the frozen country supplement: {error}") from error


def load_supplement(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Append the frozen records and preserve all existing objects and source contracts."""
    try:
        spec = _spec(Path(data_dir))
        if base_contract(base) != {
            "base_count": spec.base_count, "base_ids_sha256": spec.base_ids_sha256,
            "base_sites_sha256": spec.base_sites_sha256,
        }:
            raise SupplementError("base corpus differs from the unchanged1625 contract")
        payload = (Path(data_dir) / SITES_FILE).read_bytes()
        expected = _bytes([record.site.model_dump(mode="json") for record in _ordered(spec)])
        if _hash(payload) != SITES_SHA256 or payload != expected:
            raise SupplementError("country supplement sites differ from the reviewed specification")
        manifest = json.loads((Path(data_dir) / MANIFEST_FILE).read_bytes())
        if _bytes(manifest) != _bytes(_manifest(spec, payload)):
            raise SupplementError("country supplement manifest differs from its frozen contract")
        additions = [record.site for record in _ordered(spec)]
        if {site.id for site in additions} & {site.id for site in base}:
            raise SupplementError("country supplement duplicates an existing physical identity")
        base_countries = {
            code for site in base if site.geography for code in site.geography.countries
        }
        if base_countries & EXPECTED_COUNTRIES:
            raise SupplementError("supplement countries no longer represent the frozen source gaps")
        return base + additions
    except SupplementError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SupplementError(f"cannot load the frozen country supplement: {error}") from error


def country_labels(data_dir: Path = DATA_DIR) -> MappingProxyType[str, str]:
    """Return only newly sourced country labels, never overwrite the older registry."""
    try:
        spec = _spec(Path(data_dir))
        return MappingProxyType({
            record.site.geography.countries[0]: record.country_label
            for record in spec.records if record.site.geography
        })
    except SupplementError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SupplementError(f"cannot load country supplement labels: {error}") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Check archived review evidence without executing or interpreting source documents."""
    try:
        spec = _spec(Path(data_dir))
        checked: set[str] = set()
        root = Path(cache_dir).resolve()
        for record in spec.records:
            for source in record.source_files:
                if source.filename in checked:
                    continue
                path = (root / source.filename).resolve()
                if not path.is_relative_to(root) or _hash(path.read_bytes()) != source.sha256:
                    raise SupplementError(f"source snapshot differs: {source.filename}")
                checked.add(source.filename)
        return len(checked)
    except SupplementError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise SupplementError(f"cannot verify source snapshot cache: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the reviewed country supplement offline")
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
            print(json.dumps(rebuild_supplement(args.data_dir)["counts"]))
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild or --verify-source-cache")
    except (SupplementError, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
