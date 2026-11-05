"""Synthetic extension fixtures never approve real notices or relax the old cohort."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from archsearch import merimee_data as old
from archsearch import merimee_extension_data as cohort
from archsearch.corpus import build_document, load_pre_merimee_corpus
from archsearch.domain import Site
from archsearch.supplement_data import base_contract


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def base() -> list[Site]:
    source = {
        "id": "fixture:base",
        "title": "Original",
        "uri": "https://example.org/base",
        "publisher": "Synthetic fixture",
    }
    return [
        Site.model_validate(
            {
                "id": f"auth:fixture:{index}",
                "title": f"Original {index}",
                "description": "Original",
                "details": "Original field",
                "names": [],
                "types": ["historic-site"],
                "periods": [],
                "period_evidence": [],
                "repr_point": None,
                "source_kind": "supplement",
                "source_uri": source["uri"],
                "source_refs": [source],
                "contributors": [],
                "geography": {
                    "authority_id": f"supplement:auth:fixture:{index}",
                    "countries": ["BR"],
                    "regions": ["latin-america-caribbean"],
                    "source": source,
                    "point_count": 0,
                },
            }
        )
        for index in range(cohort.BASE_COUNT)
    ]


@dataclass
class Bundle:
    directory: Path
    cache: Path
    roster: dict[str, Any]
    review: dict[str, Any]
    monkeypatch: pytest.MonkeyPatch

    def model(self) -> cohort.MerimeeExtensionSpec:
        return cohort.MerimeeExtensionSpec.model_validate(
            {"roster": self.roster, "review": self.review}
        )

    def save(self) -> None:
        spec = self.model()
        for filename, data, pin in (
            (cohort.ROSTER_FILE, spec.roster.model_dump(mode="json"), "SOURCE_ROSTER_SHA256"),
            (cohort.SPEC_FILE, spec.review.model_dump(mode="json"), "SPEC_SHA256"),
        ):
            raw = encoded(data)
            (self.directory / filename).write_bytes(raw)
            self.monkeypatch.setattr(cohort, pin, digest(raw))
        self.monkeypatch.setattr(
            cohort, "SOURCE_FACTS_SHA256", digest(encoded(cohort._source_facts(spec)))
        )

    def rebuild(self, base: list[Site] | None = None) -> dict[str, Any]:
        self.save()
        payload = encoded(
            [s.model_dump(mode="json") for s in cohort.compile_merimee_extension(self.model())]
        )
        self.monkeypatch.setattr(cohort, "SITES_SHA256", digest(payload))
        return cohort.rebuild_merimee_extension(self.directory, base=base)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base: list[Site]) -> Bundle:
    cache = tmp_path / "cache"
    cache.mkdir()

    def evidence(key: str, uri: str) -> dict[str, Any]:
        raw = ("Synthetic original source, not approval: " + key).encode()
        (cache / (key + ".txt")).write_bytes(raw)
        return {
            "source": {
                "id": "fixture:" + key,
                "title": "Original source",
                "uri": uri,
                "publisher": "Synthetic fixture",
                "license": old.LICENCE,
                "excerpt": "Synthetic source evidence only.",
            },
            "artifact": {"filename": key + ".txt", "uri": uri, "sha256": digest(raw)},
        }

    metadata = evidence("metadata", old.METADATA_URI)
    licence = evidence("licence", old.LICENCE_URI)
    geography = evidence("geography", "https://example.org/m49")
    axis = evidence("axis", "https://pop.culture.gouv.fr/notice/merimee/PA00000001")
    identity = {
        "status": "approved",
        "reviewer": "Synthetic fixture",
        "method": "Synthetic independent test only",
        "reviewed_at": "2026-11-05",
    }
    definitions = [
        ("GF", "97302", "5,-52", "include", "specified_parts"),
        ("YT", "97601", "-12,45", "include", "whole_notice_scope"),
        ("PM", "97502", "", "include", "whole_notice_scope"),
        ("GF", "97301", "4,-52", "include", "composite_protected_scope"),
        ("GF", "97301", "", "component", "specified_parts"),
        ("YT", "97602", "-12,45", "hold", "whole_notice_scope"),
        ("PM", "97501", "47,-56", "existing", "whole_notice_scope"),
        ("GF", "97303", "", "include", "whole_notice_scope"),
    ]
    rows, decisions, crosswalk = [], [], []
    for index, (area, code, point, disposition, kind) in enumerate(definitions, start=1):
        fields = dict.fromkeys(old.SOURCE_FIELDS, "")
        reference = f"PA{index:08d}"
        fields.update(
            {
                "Reference": reference,
                "Titre_editorial_de_la_notice": f"Édifice {index}",
                "Commune_forme_editoriale": "Commune A, Commune B",
                "Commune_forme_index": "CommuneA;B",
                "COG_Insee_lors_de_la_protection": code,
                "Region": {"GF": "Guyane", "YT": "Mayotte", "PM": "Saint-Pierre-et-Miquelon"}[area],
                "Precision_de_la_protection": "Façades et toitures uniquement"
                if index == 1
                else "Édifice et cour",
                "Observations": "Protection historique annulée" if index == 8 else "",
                "coordonnees_au_format_WGS84": point,
                "Copyright": "Original Copyright",
                "Description_de_l_edifice": "Description originale complète.",
                "Historique": "Texte historique original.",
                "Autre_appellation_de_l_edifice": "Composant, pas un alias approuvé",
                "Date_et_typologie_de_la_protection": "1993/07/05",
                "Datation_de_l_edifice": "1720",
            }
        )
        rows.append(fields)
        scope_field = "Observations" if index == 8 else "Precision_de_la_protection"
        decisions.append(
            {
                "reference": reference,
                "disposition": disposition,
                "qualification": "uncertain" if disposition == "hold" else "immovable_cultural",
                "scope_kind": kind,
                "supported_scope_field": scope_field,
                "supported_scope_literal": fields[scope_field],
                "target_id": None
                if disposition == "hold"
                else base[0].id
                if disposition == "existing"
                else old.project_id("PA00000004")
                if disposition == "component"
                else old.project_id(reference),
                "reason": "AUDITONLYSENTINEL synthetic identity decision",
                "independent_review": identity,
                "evidence": [metadata],
                "area_code": area,
                "point_adoption": "unavailable"
                if not point
                else "provider_reference"
                if disposition == "include"
                else "withheld",
            }
        )
        join = {"original_code": code}
        if area == "PM":
            join.update(
                {
                    "current_overseas_commune": {"COM_COMER": code, "COMER": "975"},
                    "current_overseas_area": {
                        "COMER": "975",
                        "LIBELLE": "Saint-Pierre-et-Miquelon",
                    },
                }
            )
        else:
            join.update(
                {
                    "current_commune": {"COM": code, "TYPECOM": "COM", "DEP": code[:3]},
                    "current_department": {"DEP": code[:3], "LIBELLE": fields["Region"]},
                }
            )
        crosswalk.append(
            {
                "reference": reference,
                "source_cog_literal": code,
                "source_commune_literal": fields["Commune_forme_index"],
                "source_region": fields["Region"],
                "current_statistical_area": area,
                "current_cog_evidence": [join],
            }
        )
    page_rows = [
        {"__id": index, **{key: value if value else None for key, value in fields.items()}}
        for index, fields in enumerate(rows, start=1)
    ]
    api_raw = encoded({"data": page_rows})
    api_path = cache / cohort.CACHE_PREFIX / "api-pages/fixture.json"
    api_path.parent.mkdir(parents=True)
    api_path.write_bytes(api_raw)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=old.SOURCE_FIELDS, delimiter="|")
    writer.writeheader()
    writer.writerows(rows)
    raw_csv = stream.getvalue().encode("utf-8-sig")
    (cache / "source.csv").write_bytes(raw_csv)
    api_uri = (
        "https://tabular-api.data.gouv.fr/api/resources/"
        "3a52af4a-f9da-4dcc-8110-b07774dfb3bc/data/?page=1"
    )
    roster = {
        "schema_version": 1,
        "dataset_id": old.DATASET_ID,
        "source_artifact": {
            "filename": "source.csv",
            "uri": old.CSV_URI,
            "sha256": digest(raw_csv),
        },
        "fields": list(old.SOURCE_FIELDS),
        "records": [
            {
                "original_record_index": index,
                "raw_fields": fields,
                "raw_fields_compact_sha256": old.compact_hash(fields),
                "api_receipt": {
                    "api_row_compact_sha256": old.compact_hash(page_rows[index - 1]),
                    "array_index": index - 1,
                    "filename": "api-pages/fixture.json",
                    "page_sha256": digest(api_raw),
                    "provider_row_index_not_business_id": index,
                    "uri": api_uri,
                },
            }
            for index, fields in enumerate(rows, start=1)
        ],
    }
    area_rows = {
        "GF": (
            [
                "001",
                "World",
                "019",
                "Americas",
                "419",
                "Latin America and the Caribbean",
                "005",
                "South America",
                "French Guiana",
                "254",
                "GF",
                "GUF",
                "",
                "",
                "",
            ],
            "latin-america-caribbean",
        ),
        "YT": (
            [
                "001",
                "World",
                "002",
                "Africa",
                "202",
                "Sub-Saharan Africa",
                "014",
                "Eastern Africa",
                "Mayotte",
                "175",
                "YT",
                "MYT",
                "",
                "",
                "",
            ],
            "africa",
        ),
        "PM": (
            [
                "001",
                "World",
                "019",
                "Americas",
                "021",
                "Northern America",
                "",
                "",
                "Saint Pierre and Miquelon",
                "666",
                "PM",
                "SPM",
                "",
                "",
                "",
            ],
            "europe-north-america",
        ),
    }
    review = {
        "schema_version": 1,
        "cohort_version": cohort.COHORT_VERSION,
        "corpus_version": cohort.CORPUS_VERSION,
        **base_contract(base),
        "candidates_sha256": "a" * 64,
        "handoff_sha256": "b" * 64,
        "independent_report_sha256": "c" * 64,
        "metadata": {
            "evidence": metadata,
            "csv_last_modified": "2026-10-29T02:16:04+00:00",
            "dataset_modified": "2026-10-29T02:16:05+00:00",
        },
        "licence": {
            "name": old.LICENCE,
            "uri": old.LICENCE_URI,
            "accessed": "2026-11-05",
            "attribution": f"Synthetic {old.DATASET_URI} {old.LICENCE_URI} 2026-11-05",
            "evidence": licence,
        },
        "areas": [
            {
                "code": code,
                "name": cells[8],
                "source_m49_cells": cells,
                "project_region": region,
                "evidence": [geography],
            }
            for code, (cells, region) in area_rows.items()
        ],
        "area_crosswalk": crosswalk,
        "point_axis_evidence": [axis],
        "decisions": decisions,
    }
    for pin, value in {
        "RAW_SOURCE_SHA256": digest(raw_csv),
        "METADATA_SHA256": metadata["artifact"]["sha256"],
        "LICENCE_SHA256": licence["artifact"]["sha256"],
        "CANDIDATES_SHA256": "a" * 64,
        "HANDOFF_SHA256": "b" * 64,
        "INDEPENDENT_REVIEW_SHA256": "c" * 64,
        "SITES_SHA256": "d" * 64,
    }.items():
        monkeypatch.setattr(cohort, pin, value)
    monkeypatch.setattr(cohort, "SOURCE_COUNT", len(rows))
    monkeypatch.setattr(cohort, "FULL_SOURCE_COUNT", len(rows))
    result = Bundle(tmp_path, cache, roster, review, monkeypatch)
    result.save()
    return result


def test_extension_offline_rebuild_load_preserves_base(bundle: Bundle, base: list[Site]) -> None:
    first = bundle.rebuild(base)
    loaded = cohort.load_merimee_extension(base, bundle.directory)
    assert loaded[: len(base)] == base
    assert first["counts"]["added"] == 5
    assert first["counts"]["decisions"] == {"include": 5, "existing": 1, "component": 1, "hold": 1}
    assert first["counts"]["adopted_reference_points"] == 3
    assert first["counts"]["missing_reference_points"] == 2
    expected = {
        name: (bundle.directory / name).read_bytes()
        for name in (cohort.SITES_FILE, cohort.MANIFEST_FILE)
    }
    assert cohort.rebuild_merimee_extension(bundle.directory, base=base) == first
    assert {name: (bundle.directory / name).read_bytes() for name in expected} == expected
    assert cohort.verify_source_cache(bundle.cache, bundle.directory) == 6
    assert cohort.new_country_labels(bundle.directory)["PM"] == "Saint Pierre and Miquelon"


def test_source_literal_projection_and_geography_are_separate(bundle: Bundle) -> None:
    sites = {site.id: site for site in cohort.compile_merimee_extension(bundle.model())}
    first = sites[old.project_id("PA00000001")]
    assert first.repr_point == (-52, 5)
    assert first.location_precision is None
    assert first.description.startswith(
        "Commune_forme_editoriale:\nCommune A, Commune B\n\nRegion:\nGuyane"
    )
    payload = json.loads(first.details.removeprefix(old.DETAILS_PREFIX))
    assert payload["source_record"] == bundle.roster["records"][0]["raw_fields"]
    assert list(payload["source_record"]) == list(old.SOURCE_FIELDS)
    assert payload["scope"]["literal"] == "Façades et toitures uniquement"
    assert "AUDITONLYSENTINEL" not in build_document(first)
    assert old.project_id("PA00000005") not in sites
    for site in sites.values():
        assert not site.names and not site.chronology.phases and site.location_precision is None
    pm = sites[old.project_id("PA00000003")]
    assert pm.repr_point is None and pm.geography is not None
    assert pm.geography.countries == ["PM"] and pm.geography.regions == ["europe-north-america"]


@pytest.mark.parametrize(
    "mutation",
    [
        "area_hierarchy",
        "area_label",
        "old_area",
        "cog",
        "department",
        "source_cog",
        "scope",
        "duplicate",
        "missing",
        "point",
        "component_self",
        "component_hold",
    ],
)
def test_strict_extension_scope_area_join_and_targets_reject_mutation(
    bundle: Bundle, mutation: str
) -> None:
    if mutation == "area_hierarchy":
        bundle.review["areas"][2]["source_m49_cells"][4:8] = [
            "419",
            "Latin America and the Caribbean",
            "029",
            "Caribbean",
        ]
    elif mutation == "area_label":
        bundle.review["areas"][0]["name"] = "France"
    elif mutation == "old_area":
        bundle.review["decisions"][0]["area_code"] = "GP"
    elif mutation == "cog":
        bundle.review["area_crosswalk"][0]["current_cog_evidence"][0]["current_commune"]["COM"] = (
            "97399"
        )
    elif mutation == "department":
        bundle.review["area_crosswalk"][2]["current_cog_evidence"][0]["current_overseas_area"][
            "COMER"
        ] = "977"
    elif mutation == "source_cog":
        bundle.review["area_crosswalk"][0]["source_cog_literal"] = "97399"
        bundle.review["area_crosswalk"][0]["current_cog_evidence"][0]["original_code"] = "97399"
        bundle.review["area_crosswalk"][0]["current_cog_evidence"][0]["current_commune"]["COM"] = (
            "97399"
        )
    elif mutation == "scope":
        bundle.review["decisions"][0]["supported_scope_literal"] = "Whole estate (invented)"
    elif mutation == "duplicate":
        bundle.review["decisions"].append(copy.deepcopy(bundle.review["decisions"][0]))
    elif mutation == "missing":
        bundle.review["area_crosswalk"].pop()
    elif mutation == "point":
        bundle.review["decisions"][2]["point_adoption"] = "provider_reference"
    else:
        target = "PA00000005" if mutation == "component_self" else "PA00000006"
        bundle.review["decisions"][4]["target_id"] = old.project_id(target)
    with pytest.raises((cohort.MerimeeExtensionError, ValidationError)):
        cohort.compile_merimee_extension(bundle.model())


@pytest.mark.parametrize(
    "pin",
    [
        "RAW_SOURCE_SHA256",
        "METADATA_SHA256",
        "LICENCE_SHA256",
        "CANDIDATES_SHA256",
        "HANDOFF_SHA256",
        "INDEPENDENT_REVIEW_SHA256",
        "SOURCE_FACTS_SHA256",
        "SOURCE_ROSTER_SHA256",
        "SPEC_SHA256",
    ],
)
def test_extension_pins_are_independent_and_fail_closed(bundle: Bundle, pin: str) -> None:
    bundle.monkeypatch.setattr(cohort, pin, "e" * 64)
    with pytest.raises(cohort.MerimeeExtensionError):
        cohort.new_country_labels(bundle.directory)


def test_unapproved_extension_writes_nothing(bundle: Bundle) -> None:
    bundle.monkeypatch.setattr(cohort, "SPEC_SHA256", "CLOSED")
    with pytest.raises(cohort.MerimeeExtensionError, match="not configured"):
        cohort.rebuild_merimee_extension(bundle.directory)
    assert not (bundle.directory / cohort.SITES_FILE).exists()


@pytest.mark.parametrize(
    "mutation", ["base_field", "base_order", "sites", "manifest", "source", "target"]
)
def test_tampered_base_derivative_or_original_source_fails(
    bundle: Bundle, base: list[Site], mutation: str
) -> None:
    bundle.rebuild(base)
    changed = base
    if mutation == "base_field":
        changed = [base[0].model_copy(update={"details": "changed"}), *base[1:]]
    elif mutation == "base_order":
        changed = list(reversed(base))
    elif mutation == "target":
        bundle.review["decisions"][6]["target_id"] = "auth:fixture:missing"
        bundle.save()
    elif mutation == "source":
        (bundle.cache / "source.csv").write_bytes(b"changed")
        with pytest.raises(cohort.MerimeeExtensionError):
            cohort.verify_source_cache(bundle.cache, bundle.directory)
        return
    elif mutation == "sites":
        path = bundle.directory / cohort.SITES_FILE
        path.write_bytes(path.read_bytes() + b" ")
    else:
        path = bundle.directory / cohort.MANIFEST_FILE
        value = json.loads(path.read_bytes())
        value["counts"]["added"] += 1
        path.write_bytes(encoded(value))
    with pytest.raises(cohort.MerimeeExtensionError):
        cohort.load_merimee_extension(changed, bundle.directory)


def test_source_replay_rejects_changed_rows_even_with_matching_artifact_hash(
    bundle: Bundle,
) -> None:
    path = bundle.cache / "source.csv"
    changed = path.read_bytes().replace(b"Original Copyright", b"Altered Copyright")
    path.write_bytes(changed)
    bundle.roster["source_artifact"]["sha256"] = digest(changed)
    bundle.monkeypatch.setattr(cohort, "RAW_SOURCE_SHA256", digest(changed))
    bundle.save()
    with pytest.raises(cohort.MerimeeExtensionError, match="physical CSV record"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)


def test_offline_paths_and_api_page_parsing_are_bounded(
    bundle: Bundle, base: list[Site], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("offline extension attempted networking")

    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    bundle.rebuild(base)
    assert len(cohort.load_merimee_extension(base, bundle.directory)) == len(base) + 5
    calls = []
    previous = old._read_bounded

    def counted(directory: Path, filename: str) -> bytes:
        calls.append(filename)
        return previous(directory, filename)

    monkeypatch.setattr(old, "_read_bounded", counted)
    assert cohort.verify_source_cache(bundle.cache, bundle.directory) == 6
    assert calls.count(cohort.CACHE_PREFIX + "api-pages/fixture.json") == 1
    with pytest.raises(old.MerimeeError, match="escapes"):
        old._read_bounded(bundle.directory, "../escaped.json")


def test_shared_projector_keeps_old449_exact_and_old_guards_closed() -> None:
    hashes = {
        old.ROSTER_FILE: "a7b8e79d64bf184b870607fc83435a4f1c7fb021eb312211b56daed6962f7623",
        old.SPEC_FILE: "f6b41e4368d1b31082502bf501f93e576cb6718c22a0c9e807b49480a64c9709",
        old.SITES_FILE: "d0a462744555ded18bd8df628ca8200552e4ed463356189ed2ddc683de715845",
        old.MANIFEST_FILE: "863b74cba801fa60a975b759a2818d1dec989418c963605638aee0ae98bf8960",
    }
    assert {name: digest((old.DATA_DIR / name).read_bytes()) for name in hashes} == hashes
    spec = old._spec(old.DATA_DIR)
    payload = encoded([site.model_dump(mode="json") for site in old.compile_merimee(spec)])
    assert digest(payload) == hashes[old.SITES_FILE]
    complete = old.load_merimee(load_pre_merimee_corpus())
    assert base_contract(complete) == {
        "base_count": 3775,
        "base_ids_sha256": "87fb14327abb2a6d9e720687f53099485211b8f5426aadc941fe5c4c404546af",
        "base_sites_sha256": "4622fb2d263291b1e527fcf29c7321c8e84cc2e3e13961bd673dadfa13b261c3",
    }
    documents = [[site.id, build_document(site)] for site in complete]
    assert (
        old.compact_hash(documents)
        == "e4c61e5c8d0c935fa7b3e811b5232a01f9d92c56e289474c3be7afaeac2e3c31"
    )
    for code in ["GF", "YT", "PM"]:
        candidate = spec.review.areas[0].model_dump(mode="json")
        candidate["code"] = code
        with pytest.raises(ValidationError):
            old.MerimeeArea.model_validate(candidate)
