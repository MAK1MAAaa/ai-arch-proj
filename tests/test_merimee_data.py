"""Synthetic offline contracts exercise failures without approving real source notices."""

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

from archsearch import merimee_data as cohort
from archsearch.corpus import build_document
from archsearch.domain import Site
from archsearch.supplement_data import base_contract


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def base() -> list[Site]:
    source = {
        "id": "synthetic:base",
        "title": "Synthetic unchanged source",
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

    def model(self) -> cohort.MerimeeSpec:
        return cohort.MerimeeSpec.model_validate({"roster": self.roster, "review": self.review})

    def save(self) -> None:
        spec = self.model()
        for filename, value, pin in (
            (cohort.ROSTER_FILE, spec.roster.model_dump(mode="json"), "SOURCE_ROSTER_SHA256"),
            (cohort.SPEC_FILE, spec.review.model_dump(mode="json"), "SPEC_SHA256"),
        ):
            raw = encoded(value)
            (self.directory / filename).write_bytes(raw)
            self.monkeypatch.setattr(cohort, pin, digest(raw))
        self.monkeypatch.setattr(
            cohort, "SOURCE_FACTS_SHA256", digest(encoded(cohort._source_facts(spec)))
        )

    def compile(self, base: list[Site] | None = None) -> dict[str, Any]:
        self.save()
        additions = cohort.compile_merimee(self.model())
        self.monkeypatch.setattr(
            cohort,
            "SITES_SHA256",
            digest(encoded([site.model_dump(mode="json") for site in additions])),
        )
        return cohort.rebuild_merimee(self.directory, base=base)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base: list[Site]) -> Bundle:
    cache = tmp_path / "cache"
    cache.mkdir()

    def evidence(key: str, uri: str) -> dict[str, Any]:
        raw = ("Synthetic evidence only, not source approval: " + key).encode()
        (cache / (key + ".txt")).write_bytes(raw)
        return {
            "source": {
                "id": "fixture:" + key,
                "title": "Synthetic original source",
                "uri": uri,
                "publisher": "Synthetic fixture",
                "license": cohort.LICENCE,
                "excerpt": "Synthetic original cultural and source evidence.",
            },
            "artifact": {"filename": key + ".txt", "uri": uri, "sha256": digest(raw)},
        }

    metadata = evidence("metadata", cohort.METADATA_URI)
    licence = evidence("licence", cohort.LICENCE_URI)
    geography = evidence("m49", "https://example.org/current-m49")
    axis = evidence("axis", "https://pop.culture.gouv.fr/notice/merimee/PA00000001")
    definitions = [
        ("GP", "97101", "15,-61", "specified_parts", "include"),
        ("BL", "97701", "17,-62", "whole_notice_scope", "include"),
        ("MF", "97801", "", "whole_notice_scope", "include"),
        ("RE", "97411;97408", "-20,55", "composite_protected_scope", "include"),
        ("RE", "97408", "", "whole_notice_scope", "component"),
        ("MQ", "97201", "14,-61", "whole_notice_scope", "include"),
        ("GP", "97102", "16,-61", "whole_notice_scope", "include"),
        ("RE", "97401", "-21,55", "whole_notice_scope", "hold"),
    ]
    source_rows: list[dict[str, str]] = []
    page_rows: list[dict[str, Any]] = []
    decisions, mappings = [], []
    identity = {
        "status": "approved",
        "reviewer": "Synthetic independent fixture",
        "method": "Synthetic test contract only",
        "reviewed_at": "2026-11-05",
    }
    for index, (area, cog, point, scope, disposition) in enumerate(definitions, start=1):
        reference = f"PA{index:08d}"
        fields = dict.fromkeys(cohort.SOURCE_FIELDS, "")
        fields.update(
            {
                "Reference": reference,
                "Titre_editorial_de_la_notice": f"Édifice {index}",
                "COG_Insee_lors_de_la_protection": cog,
                "Commune_forme_index": "Ville A;Ville B",
                "Commune_forme_editoriale": "Ville A, Ville B",
                "Region": "Guadeloupe"
                if area in {"GP", "BL", "MF"}
                else "La Réunion"
                if area == "RE"
                else "Martinique",
                "coordonnees_au_format_WGS84": point,
                "Precision_de_la_protection": "Façades et toitures uniquement"
                if index == 1
                else "Voir commune de : Saint-Denis"
                if disposition == "component"
                else "Édifice et dépendances : arrêté de protection de 1993",
                "Observations": "Protection annulée : objet historique" if index == 6 else "",
                "Autre_appellation_de_l_edifice": "Component short name, not a whole alias",
                "Datation_de_l_edifice": "1720",
                "Date_et_typologie_de_la_protection": "1993/07/05",
                "Copyright": "Original Copyright retained",
                "Historique": "Texte original intégral.",
            }
        )
        source_rows.append(fields)
        page_rows.append({"__id": index, **{k: v if v else None for k, v in fields.items()}})
        decisions.append(
            {
                "reference": reference,
                "disposition": disposition,
                "qualification": "uncertain" if disposition == "hold" else "immovable_cultural",
                "scope_kind": scope,
                "supported_scope_field": "Observations"
                if index == 6
                else "Precision_de_la_protection",
                "supported_scope_literal": fields["Observations"]
                if index == 6
                else fields["Precision_de_la_protection"],
                "target_id": None
                if disposition == "hold"
                else cohort.project_id("PA00000004")
                if disposition == "component"
                else cohort.project_id(reference),
                "reason": "AUDITONLYSENTINEL reviewed synthetic identity decision",
                "independent_review": identity,
                "evidence": [metadata],
                "area_code": area,
                "point_adoption": "unavailable"
                if not point
                else "withheld"
                if index in {7, 8}
                else "provider_reference",
            }
        )
        joins = []
        for code in cog.split(";"):
            if area in {"BL", "MF"}:
                joins.append(
                    {
                        "original_code": code,
                        "current_overseas_commune": {"COM_COMER": code, "COMER": code[:3]},
                        "current_overseas_area": {"COMER": code[:3], "LIBELLE": "Area"},
                    }
                )
            else:
                joins.append(
                    {
                        "original_code": code,
                        "current_commune": {"COM": code, "TYPECOM": "COM", "DEP": code[:3]},
                        "current_department": {"DEP": code[:3], "LIBELLE": "Area"},
                    }
                )
        mappings.append(
            {
                "reference": reference,
                "source_cog_literal": cog,
                "source_commune_literal": fields["Commune_forme_index"],
                "source_region": fields["Region"],
                "current_statistical_area": area,
                "current_cog_evidence": joins,
            }
        )
    api_uri = (
        "https://tabular-api.data.gouv.fr/api/resources/"
        "3a52af4a-f9da-4dcc-8110-b07774dfb3bc/data/?page=1"
    )
    api_filename = "api-pages/fixture.json"
    api_path = cache / "merimee-source-candidate" / api_filename
    api_path.parent.mkdir(parents=True)
    api_raw = encoded({"data": page_rows})
    api_path.write_bytes(api_raw)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=cohort.SOURCE_FIELDS, delimiter="|")
    writer.writeheader()
    writer.writerows(source_rows)
    raw_csv = stream.getvalue().encode("utf-8-sig")
    (cache / "source.csv").write_bytes(raw_csv)
    roster = {
        "schema_version": 1,
        "dataset_id": cohort.DATASET_ID,
        "source_artifact": {
            "filename": "source.csv",
            "uri": cohort.CSV_URI,
            "sha256": digest(raw_csv),
        },
        "fields": list(cohort.SOURCE_FIELDS),
        "records": [
            {
                "original_record_index": index,
                "raw_fields": fields,
                "raw_fields_compact_sha256": cohort.compact_hash(fields),
                "api_receipt": {
                    "api_row_compact_sha256": cohort.compact_hash(page_rows[index - 1]),
                    "array_index": index - 1,
                    "filename": api_filename,
                    "page_sha256": digest(api_raw),
                    "provider_row_index_not_business_id": index,
                    "uri": api_uri,
                },
            }
            for index, fields in enumerate(source_rows, start=1)
        ],
    }
    areas = []
    for area, name in [
        ("GP", "Guadeloupe"),
        ("BL", "Saint Barthélemy"),
        ("MF", "Saint Martin (French Part)"),
        ("MQ", "Martinique"),
        ("RE", "Réunion"),
    ]:
        hierarchy = (
            ["002", "Africa", "202", "Sub-Saharan Africa", "014", "Eastern Africa"]
            if area == "RE"
            else ["019", "Americas", "419", "Latin America and the Caribbean", "029", "Caribbean"]
        )
        areas.append(
            {
                "code": area,
                "name": name,
                "project_region": "africa" if area == "RE" else "latin-america-caribbean",
                "source_m49_cells": [
                    "001",
                    "World",
                    *hierarchy,
                    name,
                    "123",
                    area,
                    "AAA",
                    "",
                    "",
                    "",
                ],
                "evidence": [geography],
            }
        )
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
            "name": cohort.LICENCE,
            "uri": cohort.LICENCE_URI,
            "attribution": f"Synthetic {cohort.DATASET_URI} {cohort.LICENCE_URI} 2026-11-05",
            "accessed": "2026-11-05",
            "evidence": licence,
        },
        "areas": areas,
        "area_crosswalk": mappings,
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
    monkeypatch.setattr(cohort, "SOURCE_COUNT", len(source_rows))
    monkeypatch.setattr(cohort, "FULL_SOURCE_COUNT", len(source_rows))
    result = Bundle(tmp_path, cache, roster, review, monkeypatch)
    result.save()
    return result


def test_offline_rebuild_load_and_original_contract(bundle: Bundle, base: list[Site]) -> None:
    manifest = bundle.compile(base)
    result = cohort.load_merimee(base, bundle.directory)
    assert result[: len(base)] == base
    assert manifest["counts"]["added"] == 6
    assert manifest["counts"]["adopted_reference_points"] == 4
    assert manifest["counts"]["decisions"] == {"component": 1, "hold": 1, "include": 6}
    first_bytes = (bundle.directory / cohort.SITES_FILE).read_bytes()
    assert cohort.rebuild_merimee(bundle.directory, base=base) == manifest
    assert (bundle.directory / cohort.SITES_FILE).read_bytes() == first_bytes
    assert cohort.verify_source_cache(bundle.cache, bundle.directory) == 6
    assert cohort.new_country_labels(bundle.directory)["BL"] == "Saint Barthélemy"


def test_literal_scope_missing_points_and_no_generated_claims(bundle: Bundle) -> None:
    sites = {site.id: site for site in cohort.compile_merimee(bundle.model())}
    partial = sites[cohort.project_id("PA00000001")]
    details = json.loads(partial.details.removeprefix(cohort.DETAILS_PREFIX))
    assert details["scope"]["literal"] == "Façades et toitures uniquement"
    assert len(details["source_record"]) == 78
    assert list(details["source_record"]) == list(cohort.SOURCE_FIELDS)
    assert details["source_record"] == bundle.roster["records"][0]["raw_fields"]
    assert partial.repr_point == (-61.0, 15.0)
    assert partial.location_precision is None
    assert "AUDITONLYSENTINEL" not in build_document(partial)
    assert sites[cohort.project_id("PA00000003")].repr_point is None
    assert sites[cohort.project_id("PA00000007")].repr_point is None
    assert cohort.project_id("PA00000005") not in sites
    for site in sites.values():
        assert not site.names and not site.periods and not site.chronology.phases
        assert site.chronology.status == "not_reviewed"
        assert site.geography is not None
        assert site.geography.point_count == int(site.repr_point is not None)
    historical = json.loads(
        sites[cohort.project_id("PA00000006")].details.removeprefix(cohort.DETAILS_PREFIX)
    )
    assert historical["scope"]["source_field"] == "Observations"


def test_guadeloupe_source_group_does_not_override_modern_statistical_area(bundle: Bundle) -> None:
    sites = {site.id: site for site in cohort.compile_merimee(bundle.model())}
    for ref, area in [("PA00000001", "GP"), ("PA00000002", "BL"), ("PA00000003", "MF")]:
        site = sites[cohort.project_id(ref)]
        assert site.geography is not None and site.geography.countries == [area]
        assert (
            json.loads(site.details.removeprefix(cohort.DETAILS_PREFIX))["source_record"]["Region"]
            == "Guadeloupe"
        )


def test_description_retains_complete_labelled_fields_in_scope_first_order(bundle: Bundle) -> None:
    row = bundle.roster["records"][0]
    row["raw_fields"]["Description_de_l_edifice"] = "Corps complet.\nDeuxième paragraphe."
    row["raw_fields_compact_sha256"] = cohort.compact_hash(row["raw_fields"])

    def site() -> Site:
        return next(
            s
            for s in cohort.compile_merimee(bundle.model())
            if s.id == cohort.project_id("PA00000001")
        )

    assert site().description == (
        "Commune_forme_editoriale:\nVille A, Ville B\n\nRegion:\nGuadeloupe\n\n"
        "Precision_de_la_protection:\nFaçades et toitures uniquement\n\n"
        "Description_de_l_edifice:\nCorps complet.\nDeuxième paragraphe.\n\n"
        "Historique:\nTexte original intégral."
    )
    assert "Copyright:" not in site().description
    assert "Date_et_typologie_de_la_protection:" not in site().description
    decision = bundle.review["decisions"][0]
    decision["supported_scope_field"] = "Historique"
    decision["supported_scope_literal"] = row["raw_fields"]["Historique"]
    assert site().description.count("Historique:\n") == 1
    assert site().description.index("Historique:\n") < site().description.index(
        "Description_de_l_edifice:\n"
    )
    row["raw_fields"]["Commune_forme_editoriale"] = ""
    row["raw_fields_compact_sha256"] = cohort.compact_hash(row["raw_fields"])
    assert "Commune_forme_editoriale:" not in site().description


@pytest.mark.parametrize("literal", ["NaN,1", "1,inf", "91,1", "1,181", "1", "1,2,3", " ", ",1"])
def test_invalid_source_reference_points_fail(literal: str) -> None:
    with pytest.raises(ValueError):
        cohort.parse_reference_point(literal)


def test_explicit_zero_is_not_missing_or_an_automatic_substitute() -> None:
    assert cohort.parse_reference_point("") is None
    assert cohort.parse_reference_point("0,0") == (0.0, 0.0)


@pytest.mark.parametrize("mutation", ["missing", "extra", "null", "number", "raw_hash", "index"])
def test_original_fields_are_strict_complete_and_hash_bound(bundle: Bundle, mutation: str) -> None:
    row = copy.deepcopy(bundle.roster["records"][0])
    if mutation == "missing":
        del row["raw_fields"]["Copyright"]
    elif mutation == "extra":
        row["raw_fields"]["Pays"] = "FR"
    elif mutation in {"null", "number"}:
        row["raw_fields"]["Historique"] = None if mutation == "null" else 1
    elif mutation == "raw_hash":
        row["raw_fields"]["Copyright"] = "modified"
    else:
        row["original_record_index"] = 0
    with pytest.raises(ValidationError):
        cohort.MerimeeOriginalRecord.model_validate(row)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "omitted",
        "scope",
        "area",
        "missing_point",
        "component_self",
        "component_hold",
        "component_chain",
    ],
)
def test_all_notices_require_exact_review_scope_area_and_target(
    bundle: Bundle, mutation: str
) -> None:
    if mutation == "duplicate":
        bundle.review["decisions"].append(copy.deepcopy(bundle.review["decisions"][0]))
    elif mutation == "omitted":
        bundle.review["decisions"].pop()
    elif mutation == "scope":
        bundle.review["decisions"][0]["supported_scope_literal"] = "Whole building (invented)"
    elif mutation == "area":
        bundle.review["decisions"][1]["area_code"] = "GP"
    elif mutation == "missing_point":
        bundle.review["decisions"][2]["point_adoption"] = "provider_reference"
    else:
        target = {
            "component_self": "PA00000005",
            "component_hold": "PA00000008",
            "component_chain": "PA99999999",
        }[mutation]
        bundle.review["decisions"][4]["target_id"] = cohort.project_id(target)
    with pytest.raises((cohort.MerimeeError, ValidationError)):
        cohort.compile_merimee(bundle.model())


@pytest.mark.parametrize("mutation", ["cog", "department", "m49", "missing_area"])
def test_geographic_mapping_replays_original_codes_and_active_rows(
    bundle: Bundle, mutation: str
) -> None:
    if mutation == "cog":
        bundle.review["area_crosswalk"][3]["source_cog_literal"] = "97411"
    elif mutation == "department":
        bundle.review["area_crosswalk"][1]["current_cog_evidence"][0]["current_overseas_area"][
            "COMER"
        ] = "978"
    elif mutation == "m49":
        bundle.review["areas"][1]["source_m49_cells"][8] = "France"
    else:
        bundle.review["areas"].pop()
    with pytest.raises((cohort.MerimeeError, ValidationError)):
        cohort.compile_merimee(bundle.model())


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
def test_independent_source_pins_cannot_be_replaced(bundle: Bundle, pin: str) -> None:
    bundle.monkeypatch.setattr(cohort, pin, "e" * 64)
    with pytest.raises(cohort.MerimeeError):
        cohort.new_country_labels(bundle.directory)


def test_closed_pins_refuse_activation(bundle: Bundle) -> None:
    bundle.monkeypatch.setattr(cohort, "SPEC_SHA256", "CLOSED")
    with pytest.raises(cohort.MerimeeError, match="not configured"):
        cohort.rebuild_merimee(bundle.directory)
    assert not (bundle.directory / cohort.SITES_FILE).exists()


@pytest.mark.parametrize("mutation", ["base_field", "base_order", "sites", "manifest", "source"])
def test_tampering_fails_before_loading(bundle: Bundle, base: list[Site], mutation: str) -> None:
    bundle.compile(base)
    modified = base
    if mutation == "base_field":
        modified = [base[0].model_copy(update={"details": "Changed"}), *base[1:]]
    elif mutation == "base_order":
        modified = list(reversed(base))
    elif mutation == "source":
        (bundle.cache / "source.csv").write_bytes(b"changed")
        with pytest.raises(cohort.MerimeeError, match="snapshot differs"):
            cohort.verify_source_cache(bundle.cache, bundle.directory)
        return
    else:
        filename = cohort.SITES_FILE if mutation == "sites" else cohort.MANIFEST_FILE
        path = bundle.directory / filename
        path.write_bytes(path.read_bytes().replace(b"original", b"tampered") + b" ")
        if mutation == "manifest":
            content = json.loads(path.read_bytes())
            content["counts"]["added"] += 1
            path.write_bytes(encoded(content))
    with pytest.raises(cohort.MerimeeError):
        cohort.load_merimee(modified, bundle.directory)


def test_invented_existing_target_is_rejected(bundle: Bundle, base: list[Site]) -> None:
    bundle.review["decisions"][4]["target_id"] = "auth:fixture:not-in-base"
    bundle.save()
    with pytest.raises(cohort.MerimeeError, match="component target"):
        bundle.compile(base)


def test_source_csv_replay_checks_rows_even_when_raw_hash_matches(bundle: Bundle) -> None:
    path = bundle.cache / "source.csv"
    changed = path.read_bytes().replace(
        b"Original Copyright retained", b"Altered Copyright retained"
    )
    path.write_bytes(changed)
    bundle.roster["source_artifact"]["sha256"] = digest(changed)
    bundle.monkeypatch.setattr(cohort, "RAW_SOURCE_SHA256", digest(changed))
    bundle.save()
    with pytest.raises(cohort.MerimeeError, match="physical record differs"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)


def test_api_replay_checks_row_fields_even_when_page_hash_matches(bundle: Bundle) -> None:
    path = bundle.cache / "merimee-source-candidate/api-pages/fixture.json"
    page = json.loads(path.read_bytes())
    page["data"][0]["Historique"] = "Changed original API value"
    raw = encoded(page)
    path.write_bytes(raw)
    for row in bundle.roster["records"]:
        row["api_receipt"]["page_sha256"] = digest(raw)
    bundle.save()
    with pytest.raises(cohort.MerimeeError, match="API corroboration differs"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)


def test_escape_paths_and_oversized_input_are_rejected(bundle: Bundle) -> None:
    with pytest.raises(cohort.MerimeeError, match="escapes"):
        cohort._read_bounded(bundle.directory, "../escape.json")
    bundle.monkeypatch.setattr(cohort, "MAX_FILE_BYTES", 8)
    with pytest.raises(cohort.MerimeeError, match="bounded"):
        cohort.new_country_labels(bundle.directory)


def test_no_network_is_needed_for_rebuild_load_or_cache_verification(
    bundle: Bundle,
    base: list[Site],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("offline compiler attempted networking")

    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    bundle.compile(base)
    assert len(cohort.load_merimee(base, bundle.directory)) == len(base) + 6
    assert cohort.verify_source_cache(bundle.cache, bundle.directory) == 6
