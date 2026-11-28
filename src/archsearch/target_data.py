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
FINLAND_VARK = NamedPlaceCohort(
    "finland-vark-public-v1",
    "global-v21",
    "finland_vark",
    "9d487a5e46f31f671254b4ae7184a0c245c178265cdf53b83a97b11eaeb290b8",
    "fb4e142b0f9517ae9e82328f8394c7d985692efb84a846b855cab476ce5270fa",
)
WALES_CADW = NamedPlaceCohort(
    "wales-cadw-public-v1",
    "global-v21",
    "wales_cadw",
    "800a7f09b32eb1d0a0e605895e42d60c5b6073a1ffe4a32470333669c3ecafd4",
    "f142e838e97dcd2545fc52c36827f0dbc448722c8ef6a58a96d0cf42ef435eb7",
)
THAILAND_FAD = NamedPlaceCohort(
    "thailand-fad-public-v1",
    "global-v21",
    "thailand_fad",
    "1cc7aecfdb0cb1b2925e15c4dc4c6587b8d6451b19a1a2e63929fc371f0fc44c",
    "9ee26d0b20abf35338d93430a812c06df435bffe827654d4081154d1670c08d4",
)
AFRICA_VISIT = NamedPlaceCohort(
    "africa-public-visit-v1",
    "global-v21",
    "africa_visit",
    "184d58133b5930819d4209057789071e0998c8a88b09434934403364a7fd3d76",
    "f16570a0fe066763579adadc8b440622378bce8cffa3bd23e4a7a10ab6788155",
)
SCOTLAND_HES = NamedPlaceCohort(
    "scotland-hes-public-v1",
    "global-v21",
    "scotland_hes",
    "1db3d61d10a10bc8d59c6fb725b21a99b7b564a46da46578c896b4551e902e86",
    "b8b553b4026ce9ac1f2def85457fd85c300f6651e636d96e1f5db8797dd04723",
)
CARIBBEAN_NRHP = NamedPlaceCohort(
    "caribbean-nrhp-public-v1",
    "global-v21",
    "caribbean_nrhp",
    "697c34f8caf877b70fda7f2f7b47d1803ce8bbad414d8c8a40d936480916c88c",
    "8899b0b29eec454e2e7f1f71241c02a01ee809319dafb49dc8992ae0c1f3e2d3",
    country_labels=(("PR", "Puerto Rico"), ("VI", "United States Virgin Islands")),
)
PERU_PUBLIC = NamedPlaceCohort(
    "peru-mincul-public-v1",
    "global-v21",
    "peru_public",
    "fd042f30ff3f8719364f132e085b2d019c08d10920833e18ed62ef0fd37eba77",
    "b77b25d193ba22505e0255a93863e794eb2ab8a70e822a5f8f83d7c1708f1dcf",
)
INDIA_ASI = NamedPlaceCohort(
    "india-asi-public-v1",
    "global-v21",
    "india_asi",
    "df0e2c551a3a2a96686f0b595221bdb935d3c4d930d80442474c4b93e8763d37",
    "3647c59d3957018304bd9226faa2faa9792648de152aa27eeeb2684fcfc49c4d",
)
INDIA_ASI_NEXT = NamedPlaceCohort(
    "india-asi-public-v2",
    "global-v21",
    "india_asi_next",
    "71a5d01e639267be7c014e654d14a0e290dc16a765a10a8012049e3d45d1dbd8",
    "5fc2ecb2d575c6b6ae51fbab98cc03f5b250bda39589751363ff71d31f66c7a6",
)
SRI_LANKA_PUBLIC = NamedPlaceCohort(
    "sri-lanka-public-v1",
    "global-v21",
    "sri_lanka_public",
    "c70da6586e71c743f37f43dbe8a3c5c8fd4e9ba3ffd771d6ac14a4ba5f3ae3d9",
    "0b369ab2c8cf1e7bfc3054a7cada630153a8855a90ec204a1148307c208f4489",
)
SOUTH_ASIA_PUBLIC = NamedPlaceCohort(
    "south-asia-bd-np-pk-public-v1",
    "global-v21",
    "south_asia_public",
    "70cd25abac05104b6f7be6661a50a8dd5105c5117377433436331d676d7a72b9",
    "298a855b6905f736f209ab6674587f77953df0106341997c7913143eb49e23f0",
)
CENTRAL_AMERICA_PUBLIC = NamedPlaceCohort(
    "public-central-america-colombia-v1",
    "global-v21",
    "central_america_public",
    "03aa02e5faf3c14747413a1a62e0d431a5a28509b3398690851973a60d7ee517",
    "1fd5f68277153eff34d2e7d48d52ddc956ee3c22ed9432759891e350c1b5388f",
)
SOUTHERN_PUBLIC = NamedPlaceCohort(
    "southern-cone-public-v1",
    "global-v21",
    "southern_public",
    "97706bbef72a4c30d511fdf5ba73bb5e782b3e535eb44759741e0864f1f503d8",
    "8606c50ab848729252bc30c9c711e5c4cecd6410a7cbc5eb26ba9d820aa4e17f",
)
NEW_ZEALAND_PUBLIC = NamedPlaceCohort(
    "new-zealand-public-v1",
    "global-v21",
    "new_zealand_public",
    "ca03ffffdb79bb4c43d3f22e5d0bbf1884bf8cac213cb9df77b6bee4f77b3dc3",
    "dba29f8e7562b2df0f30787353a143f3c8b78cb05938a00af8fac9c4ea3534dd",
)
EGYPT_PUBLIC = NamedPlaceCohort(
    "egypt-mota-public-v1",
    "global-v21",
    "egypt_public",
    "89a99e29afb86070b703281471219c5454ea127554ac9b9da83b0382cb6df3d6",
    "fbfb0317e370df2f3f0fd4601ca2f6a00a130d10324733cdbc106f1bbb815c3e",
)
SOUTHEAST_PUBLIC = NamedPlaceCohort(
    "vietnam-cambodia-public-v1",
    "global-v21",
    "southeast_public",
    "5cb9406321605edf6c7a3fb96affc7a9fba9519712605caf6484fdd14dff348b",
    "261a0aa22efe6beb61a518944538dcddeee6d416e4c866813dd543da7ccdc974",
)
CARIBBEAN_ISLANDS_PUBLIC = NamedPlaceCohort(
    "caribbean-islands-public-v1",
    "global-v21",
    "caribbean_islands_public",
    "ca91998d3226028b7f9272a684fce9048a2de5fe073a32023fa72ea730233136",
    "7bd2b413ce2ef6cb8139bc2002cd30b6c4ef87aed1eaa9e2f78314b20de61c14",
)
TUNISIA_PUBLIC = NamedPlaceCohort(
    "tunisia-amvppc-public-v1",
    "global-v21",
    "tunisia_public",
    "4f69a96aa81163c5c60d4eaafa032eec198dde0d74aaa84d329dedfedfeee243",
    "89ccb4b61061707fb118c139dfd0f1cc54cc1b2540b6b045cb145008c0583b9c",
)
MOROCCO_PUBLIC = NamedPlaceCohort(
    "morocco-public-v1",
    "global-v21",
    "morocco_public",
    "b344ca464c90c8df4fab286604bdbcfacfa6e800d8f909233dcf69e77d260f65",
    "4a7d7186e52702bb0eb7c01ff2a28237d9f1cf7363f250e8e6fe9a4bc00acc9a",
)
NORTH_CENTRAL_PUBLIC = NamedPlaceCohort(
    "north-central-america-public-v1",
    "global-v21",
    "north_central_public",
    "e23c43b1b7a06fc8716472613810bc05c841b0bd1c72c489e7bc87d0b08a4bae",
    "0c484da970e39f89bda49cecb495eee01f16df5c195f058e031290e00073c692",
)
PACIFIC_ISLANDS_PUBLIC = NamedPlaceCohort(
    "pacific-islands-public-v1",
    "global-v21",
    "pacific_islands_public",
    "b61c75a75a93a2eaf1d6bee29f28311aa4e62a4e8c938cbd483b407dd0125d48",
    "f48e2fad24bab384a826c9885413f4ce6e7298f03f0d82c6bbb524e3207fd87b",
)
EAST_AFRICA_PUBLIC = NamedPlaceCohort(
    "tanzania-uganda-public-v1",
    "global-v21",
    "east_africa_public",
    "c68fd862dd7caad2f6e351159c186c9072dacc9bd3e5fa21c928947776e3d904",
    "2522b3601149e8289d86fdf75bbac046d4afd362df00017bab3a8aaaf10907b9",
)
KENYA_PUBLIC = NamedPlaceCohort(
    "kenya-nmk-public-v1",
    "global-v21",
    "kenya_public",
    "c5334adb77f40a3f3127ce99654541e11fd0036961e5b44761062c66ce3027e0",
    "24a0ce444669cfb70e31856df0f3429ee6e14da741e40d570a7d1bd6857d6a9e",
)
RIVER_PLATE_PUBLIC = NamedPlaceCohort(
    "uruguay-paraguay-public-v1",
    "global-v21",
    "river_plate_public",
    "a692b95b91fdb084f96d54b87f98445598b43360d5ced82ad8155ce7ed3de149",
    "40671f78f50f735966c246bf0df18f82e626f828b569b141fb461ec41da120e1",
)
CENTRAL_ASIA_PUBLIC = NamedPlaceCohort(
    "kazakhstan-uzbekistan-public-v1",
    "global-v21",
    "central_asia_public",
    "ab9d4632b74b58889c197ce9a2a553409d6d6670afc83970f332f6da6084477b",
    "e87bf1088d402513a9cf8102cdd475d25ff046e710a6d197414b63f25dba2a99",
)
POINT_COHORTS = (
    IRELAND, ANDALUCIA, TAIWAN_ICULTURE, MEXICO_SIC, FINLAND_VARK, WALES_CADW, THAILAND_FAD,
    AFRICA_VISIT, SCOTLAND_HES, CARIBBEAN_NRHP, PERU_PUBLIC, INDIA_ASI, INDIA_ASI_NEXT,
    SRI_LANKA_PUBLIC, SOUTH_ASIA_PUBLIC, CENTRAL_AMERICA_PUBLIC, SOUTHERN_PUBLIC,
    NEW_ZEALAND_PUBLIC, EGYPT_PUBLIC, SOUTHEAST_PUBLIC, CARIBBEAN_ISLANDS_PUBLIC,
    TUNISIA_PUBLIC, MOROCCO_PUBLIC, NORTH_CENTRAL_PUBLIC, PACIFIC_ISLANDS_PUBLIC,
    EAST_AFRICA_PUBLIC, KENYA_PUBLIC, RIVER_PLATE_PUBLIC, CENTRAL_ASIA_PUBLIC,
)


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
