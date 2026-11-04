"""Compile a source-reviewed NPS register cohort without runtime networking."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from archsearch.domain import Geography, Site, SourceReference
from archsearch.supplement_data import SourceArtifact, SupplementRecord, base_contract

DATA_DIR = Path(__file__).with_name("data")
COHORT_VERSION = "nps-pacific-v1"
CORPUS_VERSION = "global-v11"
BASE_COUNT = 1807
SPEC_FILE = "nps_pacific_review.json"
SITES_FILE = "nps_pacific_sites.json"
MANIFEST_FILE = "nps_pacific_manifest.json"
CANDIDATES_SHA256 = "deec5d898956cbf4149d1112688514ab8d45adb67baea050c94ad500a56d07ed"
INDEPENDENT_REVIEW_SHA256 = "891b23a18c71b836a48bd507a17a7a77a75f01fd7b84b93d0fada5b5fdef096e"
SPEC_SHA256 = "48ea82f4bbf71ff85619571d465752ed83de53f06c67c573106694544593a966"
SITES_SHA256 = "e8cccd7e31c51d062be78a406cd801d7933dcbf1c8ec62c5fe12ed5d72630595"
SOURCE_CONTRACT_SHA256 = "8d567d54e8f4b43c04b7ccdcfef37d89cc3d53ad7e52878d3f2193213c8af99d"
SOURCE_ROSTER_SHA256 = "a3588e0309b8c948eb8a01ffdf0d974d9b34f342e6872e106bb838d3542f1e54"
PROJECT_REGION_ID = "nps-pacific"
PROJECT_REGION_LABEL = "NPS太平洋资料分组"
STATE_COUNTRIES = MappingProxyType({
    "AMERICAN SAMOA": "AS", "FEDERATED STATES OF MICRONESIA": "FM",
    "GUAM": "GU", "MARSHALL ISLANDS": "MH", "N. MARIANA ISLANDS": "MP",
    "PALAU": "PW", "U.S. MINOR ISLANDS": "UM",
})
COUNTRY_LABELS = MappingProxyType({
    "AS": "American Samoa", "FM": "Micronesia (Federated States of)",
    "GU": "Guam", "MH": "Marshall Islands", "MP": "Northern Mariana Islands",
    "PW": "Palau", "UM": "United States Minor Outlying Islands",
})
NEW_COUNTRY_CODES = frozenset({"AS", "GU", "MP", "UM"})
RESTRICTED_REFS = frozenset({"87001980"})


class NpsError(RuntimeError):
    """A frozen source decision, independent approval or base contract differs."""


class NpsDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    refnum: str = Field(pattern=r"^\d{8}$")
    names: list[str] = Field(min_length=1)
    states: list[str] = Field(min_length=1)
    resource_types: list[str] = Field(min_length=1)
    source_feature_ids: list[str] = Field(min_length=1)
    disposition: Literal["include", "existing", "component", "hold"]
    target_id: str | None = None
    reason: str = Field(min_length=1)
    evidence: list[SourceReference] = Field(min_length=1)
    source_files: list[SourceArtifact] = Field(min_length=1)

    @field_validator("names", "states", "resource_types", "source_feature_ids")
    @classmethod
    def validate_unique_values(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(not value.strip() for value in values):
            raise ValueError("NPS source roster fields require nonempty unique original values")
        return values

    @model_validator(mode="after")
    def validate_decision(self) -> NpsDecision:
        if not self.reason.strip() or (self.disposition == "hold") != (self.target_id is None):
            raise ValueError("NPS hold has no target; other decisions need a target and reason")
        if self.target_id is not None and not self.target_id.strip():
            raise ValueError("NPS decision target cannot be blank")
        if not set(self.states) <= STATE_COUNTRIES.keys() or any(
            re.fullmatch(r"[01]:\d+", value) is None for value in self.source_feature_ids
        ):
            raise ValueError("NPS source state or layer feature identity is invalid")
        return self


class NpsRecord(SupplementRecord):
    location_disclosure: Literal["public", "restricted", "unverified"]

    @model_validator(mode="after")
    def validate_location_scope(self) -> NpsRecord:
        site = self.site
        if (
            site.location_precision is not None or site.geography is None
            or site.geography.authority_id != "supplement:" + site.id
            or site.geography.regions != [PROJECT_REGION_ID]
            or site.geography.point_count != int(site.repr_point is not None)
        ):
            raise ValueError("NPS project grouping and unverified location precision must remain")
        if self.coordinate.method not in {"unknown", "authority"} or any(
            value is not None for value in (
                self.coordinate.statement_id, self.coordinate.globe,
                self.coordinate.precision, self.coordinate.rank,
            )
        ):
            raise ValueError("NPS provider metadata belongs in provenance, not Wikidata fields")
        if self.coordinate.method == "unknown" and self.coordinate.source_uri is not None:
            raise ValueError("an unadopted NPS point cannot acquire positional metadata")
        if self.location_disclosure != "public" and site.repr_point is not None:
            raise ValueError("an NPS location not verified public must remain unmapped")
        return self


class NpsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    cohort_version: Literal["nps-pacific-v1"]
    corpus_version: Literal["global-v11"]
    base_count: Literal[1807]
    base_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_sites_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_contract_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    new_countries: dict[str, str]
    selection: str = Field(min_length=1)
    decisions: list[NpsDecision] = Field(min_length=1)
    records: list[NpsRecord]


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source_roster(spec: NpsSpec) -> list[dict[str, Any]]:
    return [{
        "refnum": decision.refnum,
        "names": sorted(decision.names), "states": sorted(decision.states),
        "resource_types": sorted(decision.resource_types),
        "source_feature_ids": sorted(decision.source_feature_ids),
    } for decision in sorted(spec.decisions, key=lambda item: item.refnum)]


def _artifacts(spec: NpsSpec) -> dict[str, SourceArtifact]:
    artifacts: dict[str, SourceArtifact] = {}
    rows: list[NpsDecision | NpsRecord] = [*spec.decisions, *spec.records]
    for row in rows:
        for artifact in row.source_files:
            if artifact.filename in artifacts and artifacts[artifact.filename] != artifact:
                raise NpsError("one NPS source snapshot filename has conflicting contracts")
            artifacts[artifact.filename] = artifact
    return artifacts


def _spec(directory: Path) -> NpsSpec:
    payload = (directory / SPEC_FILE).read_bytes()
    if _hash(payload) != SPEC_SHA256:
        raise NpsError("NPS review differs from its independent pin")
    spec = NpsSpec.model_validate_json(payload)
    if (
        spec.candidates_sha256 != CANDIDATES_SHA256
        or spec.source_contract_report_sha256 != SOURCE_CONTRACT_SHA256
        or spec.independent_report_sha256 != INDEPENDENT_REVIEW_SHA256
    ):
        raise NpsError("NPS independent source-review binding differs")
    refs = [decision.refnum for decision in spec.decisions]
    features = [value for decision in spec.decisions for value in decision.source_feature_ids]
    if len(refs) != len(set(refs)) or len(features) != len(set(features)):
        raise NpsError("NPS source decisions duplicate a reference or feature")
    if _hash(_bytes(_source_roster(spec))) != SOURCE_ROSTER_SHA256:
        raise NpsError("NPS source decision roster differs from the frozen source")
    records = {record.site.id: record for record in spec.records}
    included = [decision for decision in spec.decisions if decision.disposition == "include"]
    targets = [decision.target_id for decision in included]
    if (
        len(records) != len(spec.records) or len(targets) != len(set(targets))
        or set(targets) != set(records)
    ):
        raise NpsError("NPS include decisions and records must match one-to-one")
    for decision in included:
        assert decision.target_id is not None
        if decision.target_id != "auth:nps-nris:" + decision.refnum:
            raise NpsError("NPS include target must preserve its exact canonical register identity")
        record = records[decision.target_id]
        geography = record.site.geography
        countries = {STATE_COUNTRIES[state] for state in decision.states}
        if (
            geography is None or countries != set(geography.countries) or len(countries) != 1
            or record.country_label != COUNTRY_LABELS[geography.countries[0]]
        ):
            raise NpsError("NPS State and country-or-area association differ")
        if decision.refnum in RESTRICTED_REFS and record.site.repr_point is not None:
            raise NpsError("a restricted NPS original place must remain unmapped")
    used = _accepted_country_codes(spec)
    if spec.new_countries != {code: COUNTRY_LABELS[code] for code in used & NEW_COUNTRY_CODES}:
        raise NpsError("NPS new country-or-area labels differ from reviewed source associations")
    _artifacts(spec)
    return spec


def _accepted_country_codes(spec: NpsSpec) -> set[str]:
    return {STATE_COUNTRIES[state] for row in spec.decisions if row.disposition != "hold"
            for state in row.states}


def _catalogue_associations(spec: NpsSpec) -> list[dict[str, Any]]:
    return [{
        "site_id": row.target_id, "refnum": row.refnum, "source_states": list(row.states),
        "country_codes": list(dict.fromkeys(STATE_COUNTRIES[state] for state in row.states)),
        "region": PROJECT_REGION_ID, "disposition": row.disposition,
    } for row in sorted(spec.decisions, key=lambda item: item.refnum)
        if row.disposition in {"existing", "component"}]


def _associate_catalogue(base: list[Site], spec: NpsSpec) -> list[Site]:
    """Append register membership without rewriting original facts or search evidence."""
    by_id = {site.id: site for site in base}
    for decision in sorted(spec.decisions, key=lambda item: item.refnum):
        if decision.disposition not in {"existing", "component"}:
            continue
        assert decision.target_id is not None
        site = by_id[decision.target_id]
        sources = [source.model_copy(update={
            "id": f"association:nps:{decision.refnum}:{index}", "excerpt": "",
            "title": f"NPS登记关联（{decision.refnum}，{decision.disposition}）：{source.title}",
        }) for index, source in enumerate(decision.evidence)]
        countries = list(dict.fromkeys(STATE_COUNTRIES[state] for state in decision.states))
        scope = (
            "来源登记对象是既有资料的组成部分；不将整条资料范围缩为该组成对象，不新增遗址。"
            if decision.disposition == "component" else "同一文化对象的登记关联，不新增遗址。"
        )
        note = (
            f"NPS目录关联：NRIS {decision.refnum}；来源State：{'; '.join(decision.states)}。"
            f"{scope} 来源地区关联不推断政治归属或位置。"
        )
        geography = site.geography
        if geography is None:
            geography = Geography(
                countries=countries, regions=[PROJECT_REGION_ID], source=sources[0],
                point_count=int(site.repr_point is not None), note=note,
            )
        else:
            geography = geography.model_copy(update={
                "countries": list(dict.fromkeys([*geography.countries, *countries])),
                "regions": list(dict.fromkeys([*geography.regions, PROJECT_REGION_ID])),
                "note": geography.note + ("\n\n" if geography.note else "") + note,
            })
        by_id[site.id] = site.model_copy(update={
            "geography": geography, "source_refs": [*site.source_refs, *sources],
        })
    return [by_id[site.id] for site in base]


def _ordered(spec: NpsSpec) -> list[NpsRecord]:
    return sorted(spec.records, key=lambda record: (
        _hash((COHORT_VERSION + ":" + record.site.id).encode()), record.site.id,
    ))


def _manifest(spec: NpsSpec, payload: bytes) -> dict[str, Any]:
    records = _ordered(spec)
    return {
        "schema_version": 1, "cohort_version": COHORT_VERSION, "corpus_version": CORPUS_VERSION,
        "base": {key: value for key, value in spec.model_dump().items() if key.startswith("base_")},
        "selection": spec.selection,
        "independent_source_review": {
            "candidates_sha256": spec.candidates_sha256,
            "source_contract_report_sha256": spec.source_contract_report_sha256,
            "report_sha256": spec.independent_report_sha256,
            "source_roster_sha256": SOURCE_ROSTER_SHA256,
            "scope": "Source identity/location/rights review; not phase or expert approval.",
        },
        "files": {SPEC_FILE: {"sha256": SPEC_SHA256}, SITES_FILE: {"sha256": _hash(payload)}},
        "counts": {
            "base": BASE_COUNT, "added": len(records), "total": BASE_COUNT + len(records),
            "source_references": len(spec.decisions),
            "source_features": sum(len(row.source_feature_ids) for row in spec.decisions),
            "decisions": dict(sorted(Counter(row.disposition for row in spec.decisions).items())),
            "known_locations": sum(row.site.repr_point is not None for row in records),
            "no_adopted_coordinate": sum(row.site.repr_point is None for row in records),
        },
        "new_countries": dict(sorted(spec.new_countries.items())),
        "project_region": {"id": PROJECT_REGION_ID, "label": PROJECT_REGION_LABEL,
                           "method": "Project grouping by frozen NPS State literals; not UNESCO."},
        "decisions": [row.model_dump(mode="json")
                      for row in sorted(spec.decisions, key=lambda item: item.refnum)],
        "catalogue_associations": _catalogue_associations(spec),
        "records": [{
            "id": row.site.id, "coordinate": row.coordinate.model_dump(mode="json"),
            "location_disclosure": row.location_disclosure,
            "identity_review": row.independent_review.model_dump(mode="json"),
            "source_files": [artifact.model_dump() for artifact in row.source_files],
            "provenance": row.provenance,
        } for row in records],
        "chronology": "No listing, certification or edit date becomes a historical phase.",
        "licenses": "NPS government-work factual data; third-party rights remain separate.",
    }


def rebuild_nps(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Compile frozen approved records; do not download evidence or infer locations."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        payload = _bytes([row.site.model_dump(mode="json") for row in _ordered(spec)])
        if _hash(payload) != SITES_SHA256:
            raise NpsError("compiled NPS sites differ from their independent pin")
        manifest = _manifest(spec, payload)
        (directory / SITES_FILE).write_bytes(payload)
        (directory / MANIFEST_FILE).write_bytes(_bytes(manifest))
        return manifest
    except NpsError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise NpsError(f"cannot rebuild the NPS supplement: {error}") from error


def load_nps(base: list[Site], data_dir: Path = DATA_DIR) -> list[Site]:
    """Validate the original cohort, append sourced catalogue links and new identities."""
    try:
        directory = Path(data_dir)
        spec = _spec(directory)
        if base_contract(base) != {
            "base_count": spec.base_count, "base_ids_sha256": spec.base_ids_sha256,
            "base_sites_sha256": spec.base_sites_sha256,
        }:
            raise NpsError("NPS base differs from the unchanged1807 contract")
        base_ids = {site.id for site in base}
        if any(row.target_id not in base_ids for row in spec.decisions
               if row.disposition in {"existing", "component"}):
            raise NpsError("NPS existing/component target is absent from the original base")
        additions = [row.site for row in _ordered(spec)]
        if base_ids & {site.id for site in additions}:
            raise NpsError("NPS supplement duplicates an existing identity")
        countries = {code for site in base if site.geography for code in site.geography.countries}
        used = _accepted_country_codes(spec)
        if set(spec.new_countries) & countries or set(spec.new_countries) != used - countries:
            raise NpsError("NPS new labels cannot overwrite or invent the base country registry")
        payload = (directory / SITES_FILE).read_bytes()
        expected = _bytes([row.site.model_dump(mode="json") for row in _ordered(spec)])
        if payload != expected or _hash(payload) != SITES_SHA256:
            raise NpsError("NPS sites differ from their reviewed facts")
        if _bytes(json.loads((directory / MANIFEST_FILE).read_bytes())) != _bytes(
            _manifest(spec, payload),
        ):
            raise NpsError("NPS manifest differs from its frozen contract")
        return _associate_catalogue(base, spec) + additions
    except NpsError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise NpsError(f"cannot load the NPS supplement: {error}") from error


def new_country_labels(data_dir: Path = DATA_DIR) -> MappingProxyType[str, str]:
    """Expose only the newly used, externally pinned source country-or-area labels."""
    try:
        return MappingProxyType(dict(_spec(Path(data_dir)).new_countries))
    except NpsError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise NpsError(f"cannot load NPS country-or-area labels: {error}") from error


def project_region_labels(data_dir: Path = DATA_DIR) -> MappingProxyType[str, str]:
    """Return the source grouping when any approved new or existing context uses it."""
    try:
        spec = _spec(Path(data_dir))
        return MappingProxyType(
            {PROJECT_REGION_ID: PROJECT_REGION_LABEL} if _accepted_country_codes(spec) else {},
        )
    except NpsError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise NpsError(f"cannot load the NPS project grouping: {error}") from error


def verify_source_cache(cache_dir: Path, data_dir: Path = DATA_DIR) -> int:
    """Verify optional decision/record evidence bytes, without executing or fetching them."""
    try:
        spec = _spec(Path(data_dir))
        root = Path(cache_dir).resolve()
        artifacts = _artifacts(spec)
        for filename, artifact in artifacts.items():
            path = (root / filename).resolve()
            if not path.is_relative_to(root) or _hash(path.read_bytes()) != artifact.sha256:
                raise NpsError(f"NPS source snapshot differs: {filename}")
        return len(artifacts)
    except NpsError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise NpsError(f"cannot verify NPS source snapshots: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild reviewed NPS facts offline")
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
            print(json.dumps(rebuild_nps(args.data_dir)["counts"]))
        if not args.rebuild and args.verify_source_cache is None:
            parser.error("choose --rebuild or --verify-source-cache")
    except NpsError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
