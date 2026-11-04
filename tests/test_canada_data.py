"""Synthetic complete-source contracts; no fixture asserts real cultural approval."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from pydantic import ValidationError

from archsearch import canada_data as cohort
from archsearch.corpus import build_document
from archsearch.domain import Site
from archsearch.supplement_data import base_contract

PIN_NAMES = [
    "POOL_SHA256",
    "HANDOFF_SHA256",
    "SOURCE_CONTRACT_SHA256",
    "FINAL_SOURCE_REVIEW_SHA256",
    "DEDUP_REVIEW_SHA256",
    "POINT_SOURCE_REVIEW_SHA256",
    "SCOPE_SOURCE_REVIEW_SHA256",
    "SCOPE_RELATIONS_SHA256",
    "SOURCE_ROSTER_SHA256",
    "SPEC_SHA256",
    "SITES_SHA256",
]


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def qualification_uri(identifier: str) -> str:
    return "https://open.canada.ca/data/api/3/action/datastore_search?" + urlencode(
        {
            "resource_id": cohort.SOURCE_RESOURCE_ID,
            "filters": json.dumps(
                {"Directory of Federal Heritage Designations Identifier": identifier}
            ),
            "limit": 1,
        }
    )


def reference(identifier: str, uri: str, excerpt: str = "") -> dict[str, Any]:
    return {
        "id": identifier,
        "uri": uri,
        "title": "Synthetic source, no actual historical facts",
        "publisher": "Synthetic authority",
        "license": cohort.OGL,
        "excerpt": excerpt,
    }


def source_row(identifier: int) -> dict[str, Any]:
    return {
        "_id": identifier,
        "Directory of Federal Heritage Designations Identifier": str(identifier),
        "Designation name": f"Synthetic Fort {identifier}",
        "Other names": f"Original alias {identifier} | Autre nom {identifier}",
        "Designation type": cohort.DESIGNATION_TYPE,
        "Designation statute": "Synthetic statutory text, not an actual designation",
        "Designation date": "1980-01-01",
        "Research report number": "Synthetic-123",
        "Highlight": "This designation has been identified for review"
        if identifier == 1
        else "Synthetic source highlight, not project approval.",
        "Designation description type": "Statement of significance",
        "Designation description": "Synthetic original government text. " * 20,
        "Commemorative inscription": "Texte original de la plaque; no fixture historical claim.",
        "Language of inscription": "English;French",
        "Street address": None,
        "Local area": "Synthetic locality",
        "Province or territory": "Ontario",
        "Country": "Canada",
        "Custodian": None,
        "Birth year": "1710",
        "Death year": "1790",
        "Construction start date": "about 1750",
        "Construction end date": "late eighteenth century",
        "Associated Persons/Organizations/Architect/Builder": None,
        "Railway Station Number": None,
        "Heritage Lighthouse Number": None,
        "FHRO Number": None,
        "DFRP Property Number": None,
        "CIHB Geographic Code": "fixture",
    }


def base_site(identifier: str) -> dict[str, Any]:
    evidence = reference(
        "qualification:" + identifier,
        "https://example.org/" + identifier,
        "Synthetic cultural fixture only.",
    )
    return {
        "id": identifier,
        "title": "Synthetic original " + identifier,
        "description": "Original fixture document, unchanged.",
        "description_zh": "",
        "details": "Original details.",
        "names": ["Original multilingual alias"],
        "types": ["historic-site"],
        "periods": [],
        "period_evidence": [],
        "repr_point": [-80.0, 45.0],
        "location_precision": None,
        "source_kind": "supplement",
        "source_uri": evidence["uri"],
        "source_refs": [evidence],
        "contributors": ["Synthetic source"],
        "chronology": {"status": "not_reviewed", "phases": [], "default_phase_id": None},
        "geography": {
            "authority_id": "supplement:" + identifier,
            "countries": ["CA"],
            "regions": [cohort.REGION],
            "point_count": 1,
            "source": evidence,
            "note": "Original geographic source note.",
        },
    }


def provider_receipt(identifier: str) -> dict[str, Any]:
    uri = (
        "https://maps-cartes.services.geo.ca/server_serveur/rest/services/NRCan/"
        "canadian_geographical_names_en/MapServer/5/query?"
        + urlencode(
            {
                "where": "CGNDB_ID='ABCDE'",
                "returnGeometry": "true",
                "outSR": 4326,
            }
        )
    )
    artifact = {"filename": "provider-point.json", "sha256": digest(b"provider"), "uri": uri}
    identity = {
        "filename": "provider-identity.json",
        "sha256": digest(b"identity"),
        "uri": "https://geogratis.gc.ca/services/geoname/en/geonames.json?q=synthetic",
    }
    return {
        "kind": "provider_outsr4326",
        "dfhd_id": identifier,
        "artifact": artifact,
        "identity_artifact": identity,
        "provider_attributes": {
            "OBJECTID": 1,
            "CGNDB_ID": "ABCDE",
            "GEONAME": f"Synthetic Fort {identifier} National Historic Site of Canada",
            "LANG_CODE": "und",
            "LANGUAGE": "Undetermined",
            "SYLLABIC": " ",
            "GENERIC": "National Historic Site",
            "CATEGORY": "Administrative Area",
            "CONCISE": "PARK",
            "FEATURE_ID": "abcdef123456",
            "LOCATION": "Synthetic location",
            "PROV_TERR": "Ontario",
            "REL_SCALE": "1000000",
            "DECISION": "2001-01-12",
            "SOURCE": "Parks Canada",
        },
        "reference_point": [-80.00001, 45.00001],
        "output_crs": 4326,
        "map_layer_source_crs": 3978,
        "raw_api_position_nad83": [-80, 45],
        "api_geographic_datum": "NAD83",
        "api_geographic_crs": 4269,
        "raw_api_accuracy": 100,
        "accuracy_role": "uninterpreted_source_value_no_precision_claim",
        "official_name_status": "O",
        "generic_code": "538",
        "geometry_role": "provider_geographical_name_reference_point_not_legal_boundary",
        "wikidata_identity_bridge": None,
    }


def wikidata_receipt(identifier: str, rank: str = "normal") -> dict[str, Any]:
    qid = "Q900002"
    selected = {
        "id": qid + "$coordinate-1",
        "rank": rank,
        "mainsnak": {
            "property": "P625",
            "snaktype": "value",
            "datatype": "globe-coordinate",
            "datavalue": {
                "type": "globecoordinate",
                "value": {
                    "longitude": -80.2,
                    "latitude": 45.2,
                    "altitude": None,
                    "precision": 0.0001,
                    "globe": "http://www.wikidata.org/entity/Q2",
                },
            },
        },
        "references": [{"synthetic_reference": True}],
    }
    return {
        "kind": "wikidata_earth",
        "dfhd_id": identifier,
        "qid": qid,
        "revision": 123456,
        "artifact": {
            "filename": "wikidata-entity.json",
            "sha256": digest(b"entity"),
            "uri": f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json",
        },
        "identity_artifact": {
            "filename": "wikidata-roster.json",
            "sha256": digest(b"roster"),
            "uri": "https://query.wikidata.org/sparql?query=synthetic",
        },
        "p2526_statement": {
            "id": qid + "$identity-1",
            "rank": "normal",
            "mainsnak": {
                "property": "P2526",
                "snaktype": "value",
                "datatype": "external-id",
                "datavalue": {"type": "string", "value": identifier},
            },
        },
        "p625_statements": [selected],
        "selected_statement_id": selected["id"],
        "selection_rule": "single_active_preferred_earth"
        if rank == "preferred"
        else "single_normal_earth",
        "selection_evidence": [],
        "adoption_reason": "Synthetic exact-ID single-Earth statement; not actual scope approval.",
        "reference_point": [-80.2, 45.2],
        "precision_role": "original_angular_precision_not_metres",
        "precision_status": "valid_original_angular_precision",
    }


@pytest.fixture(scope="module")
def base1999() -> list[Site]:
    result = [Site.model_validate(base_site(f"auth:fixture:{i}")) for i in range(1999)]
    first = result[0]
    assert first.geography
    result[0] = first.model_copy(
        update={
            "geography": first.geography.model_copy(
                update={
                    "countries": ["CA", "AS"],
                    "regions": [cohort.REGION, "nps-pacific"],
                }
            ),
            "source_refs": [
                *first.source_refs,
                first.source_refs[0].model_copy(
                    update={
                        "id": "association:previous-cohort",
                        "excerpt": "",
                    }
                ),
            ],
        }
    )
    return result


def record_for(row: dict[str, Any], countries: list[dict[str, Any]], receipt: dict | None) -> dict:
    identifier = row["Directory of Federal Heritage Designations Identifier"]
    aliases = list(
        dict.fromkeys(n.strip() for n in (row["Other names"] or "").split("|") if n.strip())
    )
    title = row["Designation name"] if row["Designation name"] is not None else aliases[0]
    evidence = reference(
        "qualification:ca-dfhd:" + identifier,
        qualification_uri(identifier),
        cohort.DESIGNATION_TYPE,
    )
    country = row["Country"]
    association = next(c for c in countries if c["source_country"] == country)
    refs = [evidence, association["source"]]
    point = receipt["reference_point"] if receipt else None
    coordinate: dict[str, Any] = {
        "method": "unknown",
        "point": None,
        "source_uri": None,
        "note": "No adopted same-object point; not a claim actual location is unknown.",
    }
    files = [
        {
            "filename": "master.json",
            "sha256": digest(b"master"),
            "uri": "https://open.canada.ca/data/api/3/action/datastore_search?synthetic=1",
        }
    ]
    notice = {
        "source_highlight": row["Highlight"],
        "state": "source_admin_review"
        if "identified for review" in (row["Highlight"] or "")
        else "no_source_admin_review_flag",
        "scope": "designation_reasons_or_plaque_review_not_project_approval",
    }
    if notice["state"] == "source_admin_review":
        uri = "https://parks.canada.ca/culture/designation/revue-review"
        refs.append(reference("administrative:source-review", uri))
        files.append({"filename": "admin-faq.txt", "sha256": digest(b"admin-faq"), "uri": uri})
    if receipt:
        files += [receipt["artifact"], receipt["identity_artifact"]]
        if receipt["kind"] == "provider_outsr4326" and receipt["wikidata_identity_bridge"]:
            bridge = cohort.ProviderWikidataIdentityBridge.model_validate(
                receipt["wikidata_identity_bridge"]
            )
            files.append(receipt["wikidata_identity_bridge"]["artifact"])
            bridge_ref = reference("identity:synthetic-provider", bridge.artifact.uri)
            bridge_ref["license"] = "CC0-1.0"
            refs.append(bridge_ref)
            coordinate["note"] += "\n" + cohort.source_provider_identity_note(bridge)
        point_ref = reference("coordinate:synthetic", receipt["artifact"]["uri"])
        coordinate.update(method="authority", point=point, source_uri=receipt["artifact"]["uri"])
        if receipt["kind"] == "wikidata_earth":
            for selection in receipt["selection_evidence"]:
                files.append(selection["artifact"])
                refs.append(selection["source"])
            statement = next(
                s for s in receipt["p625_statements"] if s["id"] == receipt["selected_statement_id"]
            )
            value = statement["mainsnak"]["datavalue"]["value"]
            point_ref["license"] = "CC0-1.0"
            coordinate.update(
                method="wikidata",
                statement_id=statement["id"],
                globe=value["globe"],
                rank=statement["rank"],
                precision=(
                    value.get("precision")
                    if value.get("precision") is None or value["precision"] >= 0
                    else None
                ),
            )
            precision_note = cohort.source_wikidata_precision_note(
                cohort.WikidataPointReceipt.model_validate(receipt)
            )
            if precision_note:
                coordinate["note"] += "\n" + precision_note
        refs.append(point_ref)
    code = cohort.COUNTRY_CODES[country]
    site = base_site("auth:ca-dfhd:" + identifier)
    site.update(
        title=title,
        description=row["Designation description"] or "",
        description_zh="",
        details=cohort.source_details(cohort.DfhdSourceRow.model_validate(row)),
        names=[n for n in aliases if n != title],
        repr_point=point,
        source_uri=evidence["uri"],
        source_refs=refs,
    )
    site["geography"].update(countries=[code], point_count=int(point is not None), source=evidence)
    if receipt and receipt["kind"] == "wikidata_earth" and precision_note:
        site["geography"]["note"] += "\n" + precision_note
    if (receipt and receipt["kind"] == "provider_outsr4326"
            and receipt["wikidata_identity_bridge"]):
        site["geography"]["note"] += "\n" + cohort.source_provider_identity_note(bridge)
    if notice["state"] == "source_admin_review":
        site["geography"]["note"] += "\n" + cohort.source_administrative_note(
            cohort.AdministrativeReview.model_validate(notice),
        )
    return {
        "site": site,
        "country_label": country,
        "source_row": row,
        "coordinate": coordinate,
        "source_files": files,
        "title_source": "designation_name"
        if row["Designation name"] is not None
        else "first_other_name",
        "administrative_review": notice,
        "point_receipt": receipt,
        "independent_review": {
            "status": "approved",
            "reviewer": "Synthetic independent agent",
            "method": "Fixture only, no real expert/source approval.",
            "reviewed_at": "2026-11-04",
        },
        "provenance": {
            "source_record": row, "point_receipt": receipt,
            "scope_relations": [], "synthetic_fixture": True,
        },
    }


@dataclass
class Bundle:
    directory: Path
    cache: Path
    spec: dict[str, Any]
    monkeypatch: pytest.MonkeyPatch

    def pin_spec(self) -> None:
        payload = encoded(self.spec)
        (self.directory / cohort.SPEC_FILE).write_bytes(payload)
        self.monkeypatch.setattr(cohort, "SPEC_SHA256", digest(payload))

    def pin_roster(self) -> None:
        rows = [
            {
                "dfhd_id": r["source_row"]["Directory of Federal Heritage Designations Identifier"],
                **cohort.CanadaDecision.model_validate(r).model_dump(mode="json", by_alias=True),
            }
            for r in sorted(
                self.spec["decisions"],
                key=lambda r: (
                    int(r["source_row"]["Directory of Federal Heritage Designations Identifier"]),
                    r["source_row"]["Directory of Federal Heritage Designations Identifier"],
                ),
            )
        ]
        self.monkeypatch.setattr(cohort, "SOURCE_ROSTER_SHA256", digest(encoded(rows)))

    def pin_scope(self) -> None:
        relationships = [
            cohort.CanadaScopeRelation.model_validate(row).model_dump(mode="json")
            for row in self.spec["scope_relations"]
        ]
        self.monkeypatch.setattr(cohort, "SCOPE_RELATIONS_SHA256", digest(encoded(relationships)))

    def compile(self) -> dict[str, Any]:
        self.pin_spec()
        ordered = sorted(
            self.spec["records"],
            key=lambda r: (
                digest((cohort.COHORT_VERSION + ":" + r["site"]["id"]).encode()),
                r["site"]["id"],
            ),
        )
        payload = encoded([Site.model_validate(r["site"]).model_dump(mode="json") for r in ordered])
        self.monkeypatch.setattr(cohort, "SITES_SHA256", digest(payload))
        return cohort.rebuild_canada(self.directory)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base1999: list[Site]) -> Bundle:
    cache = tmp_path / "cache"
    cache.mkdir()
    for name, body in [
        ("master.json", b"master"),
        ("provider-point.json", b"provider"),
        ("provider-identity.json", b"identity"),
        ("wikidata-entity.json", b"entity"),
        ("wikidata-roster.json", b"roster"),
        ("admin-faq.txt", b"admin-faq"),
    ]:
        (cache / name).write_bytes(body)
    countries = []
    for country, code in [("Canada", "CA"), ("France", "FR")]:
        uri = f"https://whc.unesco.org/en/statesparties/{code.lower()}/"
        data = ("Synthetic region " + country).encode()
        filename = f"region-{code}.txt"
        (cache / filename).write_bytes(data)
        countries.append(
            {
                "source_country": country,
                "code": code,
                "label": country,
                "region": cohort.REGION,
                "source": reference(
                    "region:unesco:" + code,
                    uri,
                    "Europe and North America, World Heritage Convention Regional Contact",
                ),
                "artifact": {"filename": filename, "sha256": digest(data), "uri": uri},
            }
        )
    decisions, records = [], []
    for identifier in range(1, 1015):
        row = source_row(identifier)
        if identifier == 2:
            row.update(
                {
                    "Designation name": None,
                    "Designation description": None,
                    "Designation description type": None,
                }
            )
        if identifier in {3, 6}:
            row.update({"Country": "France", "Province or territory": "Hauts-de-France"})
        disposition = (
            "include"
            if identifier <= 3
            else "existing"
            if identifier == 4
            else "component"
            if identifier == 5
            else "hold"
        )
        receipt = provider_receipt("1") if identifier == 1 else None
        target = (
            f"auth:ca-dfhd:{identifier}"
            if disposition == "include"
            else (base1999[0 if identifier == 4 else 1].id if identifier in {4, 5} else None)
        )
        decisions.append(
            {
                "source_row": row,
                "disposition": disposition,
                "target_id": target,
                "reason": "Synthetic independent disposition; no real cultural statement.",
                "evidence": [
                    reference(
                        "qualification:fixture",
                        qualification_uri(str(identifier)),
                        cohort.DESIGNATION_TYPE,
                    )
                ],
                "source_files": [
                    {
                        "filename": "master.json",
                        "sha256": digest(b"master"),
                        "uri": "https://open.canada.ca/data/api/3/action/datastore_search?synthetic=1",
                    }
                ],
                "point_receipt": receipt,
            }
        )
        if disposition == "include":
            records.append(record_for(row, countries, receipt))
    for name, value in [
        ("POOL_SHA256", "1"),
        ("HANDOFF_SHA256", "2"),
        ("SOURCE_CONTRACT_SHA256", "3"),
        ("FINAL_SOURCE_REVIEW_SHA256", "4"),
        ("DEDUP_REVIEW_SHA256", "5"),
        ("POINT_SOURCE_REVIEW_SHA256", "6"),
        ("SCOPE_SOURCE_REVIEW_SHA256", "7"),
    ]:
        monkeypatch.setattr(cohort, name, value * 64)
    spec = {
        "schema_version": 1,
        "cohort_version": cohort.COHORT_VERSION,
        "corpus_version": cohort.CORPUS_VERSION,
        **base_contract(base1999),
        "pool_sha256": "1" * 64,
        "handoff_sha256": "2" * 64,
        "source_contract_report_sha256": "3" * 64,
        "final_source_report_sha256": "4" * 64,
        "dedup_report_sha256": "5" * 64,
        "point_review_report_sha256": "6" * 64,
        "source_scope_report_sha256": "7" * 64,
        "scope_relations": [],
        "selection": cohort.SELECTION,
        "countries": countries,
        "decisions": decisions,
        "records": records,
    }
    result = Bundle(tmp_path, cache, spec, monkeypatch)
    result.pin_roster()
    result.pin_scope()
    result.compile()
    return result


@pytest.mark.parametrize("missing_pin", PIN_NAMES)
def test_unconfigured_external_approval_fails_before_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_pin: str,
) -> None:
    for name in PIN_NAMES:
        monkeypatch.setattr(cohort, name, "a" * 64)
    monkeypatch.setattr(cohort, missing_pin, "")
    with pytest.raises(cohort.CanadaError, match="not configured"):
        cohort.rebuild_canada(tmp_path)
    assert not list(tmp_path.iterdir())


def test_complete_roster_append_only_preserves_1999_original_objects_and_documents(
    bundle: Bundle,
    base1999: list[Site],
) -> None:
    before = [s.model_dump(mode="json") for s in base1999]
    documents = [build_document(s) for s in base1999]
    loaded = cohort.load_canada(base1999, bundle.directory)
    assert len(loaded) == len({s.id for s in loaded}) == 2002
    assert all(a is b for a, b in zip(base1999, loaded[:1999], strict=True))
    assert [s.model_dump(mode="json") for s in loaded[:1999]] == before
    assert [build_document(s) for s in loaded[:1999]] == documents
    assert [s.model_dump(mode="json") for s in base1999] == before
    manifest = json.loads((bundle.directory / cohort.MANIFEST_FILE).read_bytes())
    assert manifest["counts"] == {
        "base": 1999,
        "source_designations": 1014,
        "added": 3,
        "total": 2002,
        "decisions": {"include": 3, "existing": 1, "component": 1, "hold": 1009},
        "adopted_reference_points": 1,
        "provider_reference_points": 1,
        "wikidata_reference_points": 0,
        "no_adopted_representative": 2,
        "source_admin_review_notices": 1,
        "scope_relations": 0,
    }
    assert len(manifest["catalogue_associations"]) == 2


def test_outputs_deterministic_and_source_aliases_nulls_original_text_retained(
    bundle: Bundle,
) -> None:
    before = {
        name: (bundle.directory / name).read_bytes()
        for name in [cohort.SITES_FILE, cohort.MANIFEST_FILE]
    }
    cohort.rebuild_canada(bundle.directory)
    cohort.rebuild_canada(bundle.directory)
    assert before == {name: (bundle.directory / name).read_bytes() for name in before}
    bundle.spec["records"].reverse()
    bundle.spec["decisions"].reverse()
    bundle.compile()
    assert (bundle.directory / cohort.SITES_FILE).read_bytes() == before[cohort.SITES_FILE]
    spec = cohort._spec(bundle.directory)
    for record in spec.records:
        raw = record.source_row.model_dump(mode="json", by_alias=True)
        assert len(raw) == 28 and raw == record.provenance["source_record"]
        assert record.site.description == (raw["Designation description"] or "")
        assert record.site.chronology.phases == [] and record.site.periods == []
    missing = next(r for r in spec.records if r.source_row.designation_id == "2")
    assert missing.source_row.name is None and missing.source_row.description is None
    assert missing.site.title == "Original alias 2" and missing.title_source == "first_other_name"
    assert missing.site.description == "" and missing.site.description_zh == ""
    assert missing.provenance["source_record"]["Commemorative inscription"].startswith(
        "Texte original"
    )


def test_highlight_review_not_project_approval_and_not_qualification(bundle: Bundle) -> None:
    record = cohort._spec(bundle.directory).records[0]
    assert record.administrative_review.state == "source_admin_review"
    assert record.independent_review.status == "approved"
    assert record.site.source_refs[0].excerpt == cohort.DESIGNATION_TYPE
    assert record.provenance["source_record"]["Highlight"] == record.source_row.highlight
    assert record.site.geography
    assert (
        cohort.source_administrative_note(record.administrative_review)
        in record.site.geography.note
    )
    assert "身份审批" in record.site.geography.note and "历史断代" in record.site.geography.note


@pytest.mark.parametrize("mutation", ["hide_note", "drop_reference", "drop_artifact"])
def test_official_review_notice_must_be_visible_and_traceable(
    bundle: Bundle, mutation: str
) -> None:
    record = json.loads(encoded(bundle.spec["records"][0]))
    if mutation == "hide_note":
        record["site"]["geography"]["note"] = "Administrative source state hidden."
    elif mutation == "drop_reference":
        record["site"]["source_refs"] = [
            ref
            for ref in record["site"]["source_refs"]
            if not ref["id"].startswith("administrative:")
        ]
    else:
        record["source_files"] = [
            a for a in record["source_files"] if a["filename"] != "admin-faq.txt"
        ]
    bundle.spec["records"][0] = record
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError, match="visible"):
        cohort.rebuild_canada(bundle.directory)


def test_france_country_and_source_province_are_not_replaced_by_canadian_publisher(
    bundle: Bundle,
) -> None:
    record = next(
        r for r in cohort._spec(bundle.directory).records if r.source_row.country == "France"
    )
    assert record.site.geography and record.site.geography.countries == ["FR"]
    assert record.source_row.province_territory == "Hauts-de-France"
    assert record.country_label == "France"


@pytest.mark.parametrize(
    "field",
    [
        "pool_sha256",
        "handoff_sha256",
        "source_contract_report_sha256",
        "final_source_report_sha256",
        "dedup_report_sha256",
        "point_review_report_sha256",
    ],
)
def test_external_report_bindings_survive_resigned_spec(bundle: Bundle, field: str) -> None:
    bundle.spec[field] = "7" * 64
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError, match="binding"):
        cohort.rebuild_canada(bundle.directory)


@pytest.mark.parametrize(
    "field,value",
    [
        ("Highlight", "Changed administrative metadata"),
        ("Construction start date", "1900"),
        ("Commemorative inscription", None),
        ("Designation name", "Changed name"),
        ("Street address", "Changed source location"),
        ("_id", 99999),
    ],
)
def test_original_source_field_roster_cannot_be_self_resigned(
    bundle: Bundle,
    field: str,
    value: Any,
) -> None:
    bundle.spec["decisions"][-1]["source_row"][field] = value
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError, match="external pin"):
        cohort.rebuild_canada(bundle.directory)


@pytest.mark.parametrize(
    "mutation", ["drop_row", "duplicate_row", "duplicate_internal_id", "extra_row"]
)
def test_complete_1014_source_business_roster_is_mandatory(bundle: Bundle, mutation: str) -> None:
    if mutation == "drop_row":
        bundle.spec["decisions"].pop()
    elif mutation == "extra_row":
        bundle.spec["decisions"].append(copy.deepcopy(bundle.spec["decisions"][-1]))
    elif mutation == "duplicate_row":
        bundle.spec["decisions"][-1] = copy.deepcopy(bundle.spec["decisions"][-2])
    else:
        bundle.spec["decisions"][-1]["source_row"]["_id"] = 1
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError):
        cohort.rebuild_canada(bundle.directory)


@pytest.mark.parametrize(
    "mutation",
    [
        "description",
        "chinese_summary",
        "alias",
        "title",
        "title_source",
        "country",
        "province",
        "highlight_qualification",
        "fake_admin_state",
        "hide_highlight",
        "drop_source_field",
        "phase",
        "date_as_period",
        "fake_precision",
        "range_as_point",
    ],
)
def test_projection_cannot_rewrite_government_facts_or_infer_lifetimes(
    bundle: Bundle,
    mutation: str,
) -> None:
    record = json.loads(encoded(bundle.spec["records"][0]))
    if mutation == "description":
        record["site"]["description"] = "Wikidata or generated substitute description"
    elif mutation == "chinese_summary":
        record["site"]["description_zh"] = "项目生成的中文历史摘要"
    elif mutation == "alias":
        record["site"]["names"].append("Unlicensed generated alias")
    elif mutation == "title":
        record["site"]["title"] = "Generated title"
    elif mutation == "title_source":
        record["title_source"] = "first_other_name"
    elif mutation == "country":
        record["site"]["geography"]["countries"] = ["FR"]
    elif mutation == "province":
        record["point_receipt"]["provider_attributes"]["PROV_TERR"] = "Quebec"
    elif mutation == "highlight_qualification":
        record["site"]["source_refs"][0]["excerpt"] = record["source_row"]["Highlight"]
    elif mutation == "fake_admin_state":
        record["administrative_review"]["state"] = "approved"
    elif mutation == "hide_highlight":
        record["administrative_review"]["source_highlight"] = None
    elif mutation == "drop_source_field":
        record["provenance"]["source_record"].pop("Commemorative inscription")
    elif mutation == "phase":
        record["site"]["chronology"]["status"] = "insufficient"
    elif mutation == "date_as_period":
        record["site"]["periods"] = [record["source_row"]["Designation date"]]
    elif mutation == "fake_precision":
        record["coordinate"]["precision"] = 100
    else:
        record["registered_range"] = {"derived_centroid": [-80, 45]}
    bundle.spec["records"][0] = record
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError):
        cohort.rebuild_canada(bundle.directory)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_outsr",
        "nad83_as_projected",
        "wrong_key",
        "wrong_point",
        "missing_receipt",
        "raw_nad83_point",
        "raw_accuracy_as_precision",
        "provider_as_wikidata",
    ],
)
def test_provider_receipt_requires_its_actual_wgs84_role(bundle: Bundle, mutation: str) -> None:
    record = json.loads(encoded(bundle.spec["records"][0]))
    receipt = record["point_receipt"]
    if mutation == "wrong_outsr":
        receipt["output_crs"] = 4269
    elif mutation == "nad83_as_projected":
        receipt["api_geographic_crs"] = 3978
    elif mutation == "wrong_key":
        receipt["provider_attributes"]["CGNDB_ID"] = "FGHIJ"
    elif mutation == "wrong_point":
        record["site"]["repr_point"] = [-79, 44]
        record["coordinate"]["point"] = [-79, 44]
    elif mutation == "missing_receipt":
        record["point_receipt"] = None
    elif mutation == "raw_nad83_point":
        record["site"]["repr_point"] = receipt["raw_api_position_nad83"]
        record["coordinate"]["point"] = receipt["raw_api_position_nad83"]
    elif mutation == "raw_accuracy_as_precision":
        record["coordinate"]["precision"] = receipt["raw_api_accuracy"]
    else:
        record["coordinate"].update(
            method="wikidata",
            statement_id="Q1$fake",
            rank="normal",
            globe="http://www.wikidata.org/entity/Q2",
        )
    bundle.spec["records"][0] = record
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError):
        cohort.rebuild_canada(bundle.directory)


def add_wikidata_record(bundle: Bundle, rank: str = "normal") -> None:
    old = bundle.spec["records"][1]
    receipt = wikidata_receipt("2", rank)
    bundle.spec["records"][1] = record_for(old["source_row"], bundle.spec["countries"], receipt)
    bundle.spec["decisions"][1]["point_receipt"] = receipt
    bundle.pin_roster()
    bundle.compile()


@pytest.mark.parametrize("rank", ["normal", "preferred"])
def test_wikidata_exact_p2526_earth_claim_preserves_metadata_and_government_text(
    bundle: Bundle,
    base1999: list[Site],
    rank: str,
) -> None:
    add_wikidata_record(bundle, rank)
    records = cohort._spec(bundle.directory).records
    record = next(r for r in records if r.source_row.designation_id == "2")
    assert isinstance(record.point_receipt, cohort.WikidataPointReceipt)
    assert record.coordinate.method == "wikidata"
    assert record.coordinate.precision == 0.0001 and record.site.location_precision is None
    assert record.coordinate.rank == rank
    assert record.site.title == "Original alias 2" and record.site.description == ""
    assert record.provenance["point_receipt"]["p625_statements"][0]["references"]
    assert len(cohort.load_canada(base1999, bundle.directory)) == 2002
    counts = json.loads((bundle.directory / cohort.MANIFEST_FILE).read_bytes())["counts"]
    assert counts["adopted_reference_points"] == 2
    assert counts["provider_reference_points"] == 1
    assert counts["wikidata_reference_points"] == 1
    assert counts["no_adopted_representative"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_external_property",
        "wrong_external_id",
        "deprecated_identity",
        "wrong_entity",
        "non_earth",
        "temporal",
        "conflicting",
        "two_normal",
        "two_preferred",
        "precision_bool",
        "precision_nan",
        "precision_infinity",
        "precision_text",
        "invalid_longitude",
        "latitude_bool",
        "false_precision_status",
        "point_not_claim",
    ],
)
def test_wikidata_receipt_rejects_ambiguous_or_unrelated_claims(mutation: str) -> None:
    receipt = wikidata_receipt("52")
    claim = receipt["p625_statements"][0]
    value = claim["mainsnak"]["datavalue"]["value"]
    if mutation == "wrong_external_property":
        receipt["p2526_statement"]["mainsnak"]["property"] = "P477"
    elif mutation == "wrong_external_id":
        receipt["p2526_statement"]["mainsnak"]["datavalue"]["value"] = "66"
    elif mutation == "deprecated_identity":
        receipt["p2526_statement"]["rank"] = "deprecated"
    elif mutation == "wrong_entity":
        receipt["qid"] = "Q99999"
    elif mutation == "non_earth":
        value["globe"] = "http://www.wikidata.org/entity/Q405"
    elif mutation == "temporal":
        claim["qualifiers"] = {"P580": [{"snaktype": "value"}]}
    elif mutation in {"conflicting", "two_normal", "two_preferred"}:
        other = copy.deepcopy(claim)
        other["id"] = "Q900002$coordinate-2"
        if mutation == "conflicting":
            other["mainsnak"]["datavalue"]["value"]["longitude"] = -81
        if mutation == "two_preferred":
            claim["rank"] = other["rank"] = "preferred"
            receipt["selection_rule"] = "single_active_preferred_earth"
        receipt["p625_statements"].append(other)
    elif mutation == "precision_bool":
        value["precision"] = True
    elif mutation == "precision_nan":
        value["precision"] = float("nan")
    elif mutation == "precision_infinity":
        value["precision"] = float("inf")
    elif mutation == "precision_text":
        value["precision"] = "0.0001"
    elif mutation == "invalid_longitude":
        value["longitude"] = 181
    elif mutation == "latitude_bool":
        value["latitude"] = True
    elif mutation == "false_precision_status":
        receipt["precision_status"] = "negative_source_precision_not_adopted"
    else:
        receipt["reference_point"] = [-81, 45]
    with pytest.raises(ValidationError):
        cohort.WikidataPointReceipt.model_validate(receipt)


def test_unique_preferred_retains_different_normal_without_selecting_it() -> None:
    receipt = wikidata_receipt("2", "preferred")
    normal = copy.deepcopy(receipt["p625_statements"][0])
    normal["id"] = "q900002$coordinate-normal"
    normal["rank"] = "normal"
    normal["mainsnak"]["datavalue"]["value"]["longitude"] = -81.5
    receipt["p625_statements"].insert(0, normal)
    approved = cohort.WikidataPointReceipt.model_validate(receipt)
    assert approved.reference_point == (-80.2, 45.2)
    assert approved.p625_statements == receipt["p625_statements"]
    receipt["selected_statement_id"] = normal["id"]
    receipt["reference_point"] = [-81.5, 45.2]
    with pytest.raises(ValidationError, match="one original eligible statement"):
        cohort.WikidataPointReceipt.model_validate(receipt)


def source_selected_receipt(identifier: str = "2") -> dict[str, Any]:
    receipt = wikidata_receipt(identifier)
    selected = receipt["p625_statements"][0]
    selected["references"] = [{"hash": "a" * 40, "snaks": {"synthetic": []}}]
    other = copy.deepcopy(selected)
    other["id"] = "q900002$another-normal-location"
    other["mainsnak"]["datavalue"]["value"]["longitude"] = -81.5
    other["references"] = [{"hash": "b" * 40, "snaks": {"synthetic": []}}]
    receipt["p625_statements"].insert(0, other)
    uri = "https://www.historicplaces.ca/en/rep-reg/place-lieu.aspx?id=synthetic"
    receipt["selection_rule"] = "independently_reviewed_source_reference"
    receipt["selection_evidence"] = [
        cohort.WikidataSelectionEvidence.model_validate({
            "reference_hash": "a" * 40,
            "source": reference("selection:synthetic", uri),
            "artifact": {
                "filename": "selection-source.html",
                "sha256": digest(b"selection-source"),
                "uri": uri,
            },
        }).model_dump(mode="json")
    ]
    return receipt


def test_reviewed_reference_selects_its_original_claim_without_choosing_first(
    bundle: Bundle,
) -> None:
    receipt = source_selected_receipt()
    old = bundle.spec["records"][1]
    record = record_for(old["source_row"], bundle.spec["countries"], receipt)
    typed = cohort.CanadaRecord.model_validate(record)
    assert typed.point_receipt and typed.point_receipt.model_dump(mode="json") == receipt
    assert typed.coordinate.point == (-80.2, 45.2)
    assert typed.coordinate.statement_id != receipt["p625_statements"][0]["id"]
    selection = typed.point_receipt.selection_evidence[0]
    assert selection.artifact in typed.source_files and selection.source in typed.site.source_refs
    for field in ["source_files", "source_refs"]:
        mutated = copy.deepcopy(record)
        if field == "source_files":
            mutated[field].remove(selection.artifact.model_dump(mode="json"))
        else:
            mutated["site"][field].remove(selection.source.model_dump(mode="json"))
        with pytest.raises(ValidationError, match="public and pinned"):
            cohort.CanadaRecord.model_validate(mutated)


@pytest.mark.parametrize("mutation", [
    "wrong_hash", "other_claim_hash", "missing_evidence", "nonactive_selected", "preferred",
    "single_claim", "wrong_selected", "source_uri_mismatch", "old_rule_with_evidence",
])
def test_reviewed_reference_needs_the_selected_original_normal_claim(mutation: str) -> None:
    receipt = source_selected_receipt()
    selected = receipt["p625_statements"][1]
    if mutation == "wrong_hash":
        receipt["selection_evidence"][0]["reference_hash"] = "c" * 40
    elif mutation == "other_claim_hash":
        receipt["selection_evidence"][0]["reference_hash"] = "b" * 40
    elif mutation == "missing_evidence":
        receipt["selection_evidence"] = []
    elif mutation == "nonactive_selected":
        selected["rank"] = "deprecated"
    elif mutation == "preferred":
        selected["rank"] = "preferred"
    elif mutation == "single_claim":
        receipt["p625_statements"].pop(0)
    elif mutation == "wrong_selected":
        receipt["selected_statement_id"] = "Q900002$not-in-original-claims"
    elif mutation == "source_uri_mismatch":
        receipt["selection_evidence"][0]["artifact"]["uri"] += "-different"
    else:
        receipt["p625_statements"].pop(0)
        receipt["selection_rule"] = "single_normal_earth"
    with pytest.raises(ValidationError):
        cohort.WikidataPointReceipt.model_validate(receipt)


def test_reviewed_reference_artifact_is_cached_and_cannot_bypass_external_roster(
    bundle: Bundle,
) -> None:
    receipt = source_selected_receipt()
    old = bundle.spec["records"][1]
    bundle.spec["records"][1] = record_for(old["source_row"], bundle.spec["countries"], receipt)
    bundle.spec["decisions"][1]["point_receipt"] = copy.deepcopy(receipt)
    (bundle.cache / "selection-source.html").write_bytes(b"selection-source")
    bundle.pin_roster()
    bundle.compile()
    assert cohort.verify_source_cache(bundle.cache, bundle.directory) == 9
    mutated = copy.deepcopy(receipt)
    mutated["selection_evidence"][0]["artifact"]["sha256"] = "c" * 64
    bundle.spec["records"][1] = record_for(old["source_row"], bundle.spec["countries"], mutated)
    bundle.spec["decisions"][1]["point_receipt"] = mutated
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError, match="external pin"):
        bundle.compile()


def scope_relation(bundle: Bundle, source: str = "1", target: str = "3") -> dict[str, Any]:
    rows = {row["source_row"]["Directory of Federal Heritage Designations Identifier"]: row
            for row in bundle.spec["decisions"]}

    def row_hash(identifier: str) -> str:
        return digest(json.dumps(rows[identifier]["source_row"], ensure_ascii=False,
                                 sort_keys=True, separators=(",", ":")).encode())

    return {
        "source_dfhd_id": source, "target_dfhd_id": target,
        "source_record_sha256": row_hash(source), "target_record_sha256": row_hash(target),
        "kind": "contains", "note": "Synthetic source-defined relation; no actual scope claim.",
        "evidence": [{
            "dfhd_id": identifier, "field": "Designation description",
            "field_sha256": digest(
                rows[identifier]["source_row"]["Designation description"].encode()
            ),
            "source_record_sha256": row_hash(identifier), "source_page_sha256": digest(b"master"),
            "source_uri": qualification_uri(identifier),
            "normalized_excerpt": " ".join(
                rows[identifier]["source_row"]["Designation description"].split()
            ),
        } for identifier in [source, target]],
        "source_files": copy.deepcopy(rows[source]["source_files"]),
    }


def publish_scope(bundle: Bundle, relations: list[dict[str, Any]]) -> None:
    bundle.spec["scope_relations"] = relations
    rows = {row["source_row"]["Directory of Federal Heritage Designations Identifier"]:
            row["source_row"] for row in bundle.spec["decisions"]}
    for record in bundle.spec["records"]:
        identifier = record["source_row"]["Directory of Federal Heritage Designations Identifier"]
        related = [row for row in relations
                   if identifier in {row["source_dfhd_id"], row["target_dfhd_id"]}]
        record["provenance"]["scope_relations"] = copy.deepcopy(related)
        for relation in related:
            peer = (relation["target_dfhd_id"] if identifier == relation["source_dfhd_id"]
                    else relation["source_dfhd_id"])
            record["site"]["geography"]["note"] += "\n" + cohort.source_scope_note(
                cohort.CanadaScopeRelation.model_validate(relation), rows[peer]["Designation name"]
            )
    bundle.pin_scope()


def test_scope_relations_preserve_incoming_outgoing_notes_and_unchanged_old_sites(
    bundle: Bundle, base1999: list[Site],
) -> None:
    before = [site.model_dump(mode="json") for site in base1999]
    relations = [scope_relation(bundle), scope_relation(bundle, "3", "4")]
    publish_scope(bundle, relations)
    manifest = bundle.compile()
    assert manifest["scope_relations"] == relations and manifest["counts"]["scope_relations"] == 2
    spec = cohort._spec(bundle.directory)
    middle = next(row for row in spec.records if row.source_row.designation_id == "3")
    assert middle.provenance["scope_relations"] == relations
    assert middle.site.geography and all(
        cohort.source_scope_note(
            relation, "Synthetic Fort 1" if relation.source_dfhd_id == "1" else "Synthetic Fort 4"
        ) in middle.site.geography.note for relation in spec.scope_relations
    )
    assert "DFHD 1 包含 DFHD 3" in middle.site.geography.note
    assert "DFHD 3 包含 DFHD 1" not in middle.site.geography.note
    within = spec.scope_relations[0].model_copy(update={"kind": "within"})
    assert "DFHD 1 位于 DFHD 3 的来源对象范围内" in cohort.source_scope_note(
        within, "Synthetic Fort 1"
    )
    loaded = cohort.load_canada(base1999, bundle.directory)
    assert [site.model_dump(mode="json") for site in loaded[:1999]] == before
    assert len(loaded) == 2002


@pytest.mark.parametrize("mutation", [
    "source_row_hash", "target_row_hash", "field_hash", "evidence_row_hash", "page_hash",
    "excerpt", "wrong_field", "source_uri", "source_file", "unknown_endpoint", "duplicate_edge",
])
def test_scope_relations_require_both_original_source_rows_and_actual_page_bindings(
    bundle: Bundle, mutation: str,
) -> None:
    relations = [scope_relation(bundle)]
    publish_scope(bundle, relations)
    bundle.compile()
    relation = relations[0]
    if mutation == "source_row_hash":
        relation["source_record_sha256"] = "f" * 64
    elif mutation == "target_row_hash":
        relation["target_record_sha256"] = "f" * 64
    elif mutation == "field_hash":
        relation["evidence"][0]["field_sha256"] = "f" * 64
    elif mutation == "evidence_row_hash":
        relation["evidence"][0]["source_record_sha256"] = "f" * 64
    elif mutation == "page_hash":
        relation["evidence"][0]["source_page_sha256"] = "f" * 64
    elif mutation == "excerpt":
        relation["evidence"][0]["normalized_excerpt"] = "Generated relationship absent from source."
    elif mutation == "wrong_field":
        relation["evidence"][0]["field"] = "Highlight"
    elif mutation == "source_uri":
        relation["evidence"][0]["source_uri"] = qualification_uri("3")
    elif mutation == "source_file":
        relation["source_files"][0]["filename"] = "different-page.json"
    elif mutation == "unknown_endpoint":
        relation["target_dfhd_id"] = relation["evidence"][1]["dfhd_id"] = "1015"
    else:
        relations.append(copy.deepcopy(relation))
    with pytest.raises((ValidationError, cohort.CanadaError)):
        bundle.pin_scope()
        bundle.compile()


@pytest.mark.parametrize("field", ["incoming_provenance", "outgoing_provenance", "incoming_note",
                                  "outgoing_note", "external_relation_pin", "external_report_pin"])
def test_scope_relations_cannot_disappear_from_public_incoming_or_outgoing_context(
    bundle: Bundle, field: str,
) -> None:
    relations = [scope_relation(bundle)]
    publish_scope(bundle, relations)
    bundle.compile()
    if field in {"incoming_provenance", "outgoing_provenance"}:
        bundle.spec["records"][2 if field.startswith("incoming") else 0]["provenance"][
            "scope_relations"
        ] = []
    elif field in {"incoming_note", "outgoing_note"}:
        bundle.spec["records"][2 if field.startswith("incoming") else 0]["site"]["geography"][
            "note"
        ] = "Suppressed relationship."
    elif field == "external_relation_pin":
        bundle.spec["scope_relations"][0]["kind"] = "partial_overlap"
    else:
        bundle.spec["source_scope_report_sha256"] = "f" * 64
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError):
        bundle.compile()


def test_guid_entity_prefix_casefold_preserves_original_identity_and_coordinate_strings(
    bundle: Bundle,
) -> None:
    receipt = wikidata_receipt("2")
    receipt["p2526_statement"]["id"] = "q900002$original-Identity-MixedCase"
    receipt["p625_statements"][0]["id"] = "q900002$original-Coordinate-MixedCase"
    receipt["selected_statement_id"] = receipt["p625_statements"][0]["id"]
    old = bundle.spec["records"][1]
    record = record_for(old["source_row"], bundle.spec["countries"], receipt)
    result = cohort.CanadaRecord.model_validate(record)
    assert result.coordinate.statement_id == "q900002$original-Coordinate-MixedCase"
    assert result.point_receipt and result.point_receipt.model_dump(
        mode="json", by_alias=True
    ) == receipt
    for field in ["p2526_statement", "p625_statements"]:
        mutated = copy.deepcopy(receipt)
        claim = mutated[field] if field == "p2526_statement" else mutated[field][0]
        claim["id"] = "q9000020$other-entity"
        with pytest.raises(ValidationError):
            cohort.WikidataPointReceipt.model_validate(mutated)
    duplicate = copy.deepcopy(receipt["p625_statements"][0])
    duplicate["id"] = duplicate["id"].replace("q900002$", "Q900002$")
    receipt["p625_statements"].append(duplicate)
    with pytest.raises(ValidationError, match="unique original entity GUIDs"):
        cohort.WikidataPointReceipt.model_validate(receipt)


@pytest.mark.parametrize("precision", [None, 0, -0.0001, -1])
def test_selected_precision_status_preserves_raw_value_and_discloses_negative(
    bundle: Bundle,
    precision: float | None,
) -> None:
    receipt = wikidata_receipt("2")
    receipt["p625_statements"][0]["mainsnak"]["datavalue"]["value"]["precision"] = precision
    receipt["precision_status"] = (
        "source_precision_missing"
        if precision is None
        else "negative_source_precision_not_adopted"
        if precision < 0
        else "valid_original_angular_precision"
    )
    old = bundle.spec["records"][1]
    record = record_for(old["source_row"], bundle.spec["countries"], receipt)
    typed = cohort.CanadaRecord.model_validate(record)
    assert typed.coordinate.point == (-80.2, 45.2)
    assert typed.coordinate.precision == (
        precision if precision is None or precision >= 0 else None
    )
    assert typed.point_receipt and typed.point_receipt.model_dump(mode="json") == receipt
    assert typed.provenance["point_receipt"] == receipt
    if precision is not None and precision < 0:
        assert typed.site.geography
        note = cohort.source_wikidata_precision_note(typed.point_receipt)
        assert str(precision) in note
        assert note in typed.coordinate.note and note in typed.site.geography.note
        for field in ["coordinate_note", "geography_note", "absolute_value", "fake_status"]:
            mutated = copy.deepcopy(record)
            if field == "coordinate_note":
                mutated["coordinate"]["note"] = "Hidden source precision."
            elif field == "geography_note":
                mutated["site"]["geography"]["note"] = "Hidden source precision."
            elif field == "absolute_value":
                mutated["coordinate"]["precision"] = abs(precision)
            else:
                mutated["point_receipt"]["precision_status"] = "source_precision_missing"
            with pytest.raises(ValidationError):
                cohort.CanadaRecord.model_validate(mutated)


def test_bc_wikidata_not_rejected_by_old_provider_limit_and_hold_never_auto_imports(
    bundle: Bundle,
    base1999: list[Site],
) -> None:
    with pytest.raises(ValidationError, match="BC raw NAD83"):
        cohort.ProviderPointReceipt.model_validate(provider_receipt("52"))
    receipt = wikidata_receipt("52")
    cohort.WikidataPointReceipt.model_validate(receipt)
    decision = bundle.spec["decisions"][51]
    assert decision["source_row"]["Directory of Federal Heritage Designations Identifier"] == "52"
    decision["point_receipt"] = receipt
    bundle.pin_roster()
    bundle.compile()
    loaded = cohort.load_canada(base1999, bundle.directory)
    assert len(loaded) == 2002 and not any(s.id == "auth:ca-dfhd:52" for s in loaded)


def bridged_provider_receipt() -> dict[str, Any]:
    receipt = provider_receipt("1")
    receipt["provider_attributes"]["GEONAME"] = "Different Official NHS Name"
    wd = wikidata_receipt("1")
    key_claim = copy.deepcopy(wd["p2526_statement"])
    key_claim["id"] = "q900002$original-cgn-key"
    key_claim["mainsnak"]["property"] = "P821"
    key_claim["mainsnak"]["datavalue"]["value"] = "ABCDE"
    receipt["wikidata_identity_bridge"] = {
        "dfhd_id": "1", "qid": wd["qid"], "revision": wd["revision"],
        "artifact": wd["artifact"], "p2526_statement": wd["p2526_statement"],
        "p821_statement": key_claim,
    }
    return receipt


def test_provider_bridge_uses_exact_original_identifiers_without_generating_names(
    bundle: Bundle,
) -> None:
    receipt = bridged_provider_receipt()
    row = bundle.spec["records"][0]["source_row"]
    record = record_for(row, bundle.spec["countries"], receipt)
    result = cohort.CanadaRecord.model_validate(record)
    assert result.point_receipt and result.point_receipt.model_dump(
        mode="json", by_alias=True
    ) == receipt
    assert result.site.title == row["Designation name"]
    assert result.site.names == ["Original alias 1", "Autre nom 1"]
    assert "Different Official NHS Name" not in result.site.names
    assert result.coordinate.method == "authority" and result.coordinate.precision is None
    assert isinstance(result.point_receipt, cohort.ProviderPointReceipt)
    bridge = result.point_receipt.wikidata_identity_bridge
    assert bridge and bridge.artifact in result.source_files
    assert result.site.geography and cohort.source_provider_identity_note(bridge) in (
        result.site.geography.note
    )
    for field in ["artifact", "public_source", "coordinate_note", "geography_note"]:
        mutated = copy.deepcopy(record)
        if field == "artifact":
            mutated["source_files"].remove(bridge.artifact.model_dump(mode="json"))
        elif field == "public_source":
            mutated["site"]["source_refs"] = [ref for ref in mutated["site"]["source_refs"]
                                             if ref["uri"] != bridge.artifact.uri]
        elif field == "coordinate_note":
            mutated["coordinate"]["note"] = "Bridge omitted."
        else:
            mutated["site"]["geography"]["note"] = record["site"]["geography"]["note"].replace(
                cohort.source_provider_identity_note(bridge), ""
            )
        with pytest.raises(ValidationError, match="bridge must remain public and pinned"):
            cohort.CanadaRecord.model_validate(mutated)


@pytest.mark.parametrize("mutation", [
    "wrong_dfhd", "wrong_key", "deprecated_identity", "deprecated_key", "other_entity",
    "wrong_key_property", "no_bridge", "wrong_province", "not_canada",
])
def test_provider_bridge_does_not_relax_general_names_country_province_or_claims(
    bundle: Bundle, mutation: str,
) -> None:
    receipt = bridged_provider_receipt()
    row = copy.deepcopy(bundle.spec["records"][0]["source_row"])
    bridge = receipt["wikidata_identity_bridge"]
    if mutation == "wrong_dfhd":
        bridge["dfhd_id"] = "2"
        bridge["p2526_statement"]["mainsnak"]["datavalue"]["value"] = "2"
    elif mutation == "wrong_key":
        bridge["p821_statement"]["mainsnak"]["datavalue"]["value"] = "FGHIJ"
    elif mutation == "deprecated_identity":
        bridge["p2526_statement"]["rank"] = "deprecated"
    elif mutation == "deprecated_key":
        bridge["p821_statement"]["rank"] = "deprecated"
    elif mutation == "other_entity":
        bridge["p821_statement"]["id"] = "Q900003$other-key"
    elif mutation == "wrong_key_property":
        bridge["p821_statement"]["mainsnak"]["property"] = "P477"
    elif mutation == "no_bridge":
        receipt["wikidata_identity_bridge"] = None
    elif mutation == "wrong_province":
        receipt["provider_attributes"]["PROV_TERR"] = "Quebec"
    else:
        row["Country"] = "France"
    with pytest.raises(ValidationError):
        cohort.CanadaRecord.model_validate(record_for(row, bundle.spec["countries"], receipt))


def test_provider_bridge_snapshot_is_verified_and_bound_to_external_roster(bundle: Bundle) -> None:
    receipt = bridged_provider_receipt()
    old = bundle.spec["records"][0]
    bundle.spec["records"][0] = record_for(old["source_row"], bundle.spec["countries"], receipt)
    bundle.spec["decisions"][0]["point_receipt"] = copy.deepcopy(receipt)
    bundle.pin_roster()
    bundle.compile()
    assert cohort.verify_source_cache(bundle.cache, bundle.directory) == 7
    receipt["wikidata_identity_bridge"]["artifact"]["sha256"] = "b" * 64
    bundle.spec["records"][0] = record_for(old["source_row"], bundle.spec["countries"], receipt)
    bundle.spec["decisions"][0]["point_receipt"] = receipt
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError, match="external pin"):
        bundle.compile()


def test_receipt_changes_cannot_be_hidden_by_resigning_spec_and_sites(bundle: Bundle) -> None:
    record = bundle.spec["records"][0]
    point = [-79.8, 45.1]
    record["point_receipt"]["reference_point"] = point
    record["coordinate"]["point"] = point
    record["site"]["repr_point"] = point
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError, match="external pin"):
        bundle.compile()


def test_hold_cannot_be_promoted_by_only_resigning_spec_and_sites(bundle: Bundle) -> None:
    original_pin = cohort.SOURCE_ROSTER_SHA256
    decision = bundle.spec["decisions"][6]
    assert decision["disposition"] == "hold"
    row = decision["source_row"]
    identifier = row["Directory of Federal Heritage Designations Identifier"]
    decision.update(disposition="include", target_id="auth:ca-dfhd:" + identifier)
    bundle.spec["records"].append(record_for(row, bundle.spec["countries"], None))
    with pytest.raises(cohort.CanadaError, match="external pin"):
        bundle.compile()
    assert cohort.SOURCE_ROSTER_SHA256 == original_pin


def test_existing_target_cannot_be_rebound_to_another_real_base_id_by_resigning_outputs(
    bundle: Bundle,
    base1999: list[Site],
) -> None:
    original_pin = cohort.SOURCE_ROSTER_SHA256
    decision = bundle.spec["decisions"][3]
    assert decision["disposition"] == "existing" and decision["target_id"] == base1999[0].id
    decision["target_id"] = base1999[10].id
    with pytest.raises(cohort.CanadaError, match="external pin"):
        bundle.compile()
    assert cohort.SOURCE_ROSTER_SHA256 == original_pin


@pytest.mark.parametrize("field", ["reason", "evidence", "source_files"])
def test_scope_reason_and_source_bindings_are_externally_pinned(bundle: Bundle, field: str) -> None:
    decision = bundle.spec["decisions"][-1]
    if field == "reason":
        decision[field] = "A different scope interpretation without independent approval."
    elif field == "evidence":
        decision[field] = [
            reference(
                "qualification:replacement", qualification_uri("1014"), cohort.DESIGNATION_TYPE
            )
        ]
    else:
        decision[field] = [
            {
                "filename": "different-source.json",
                "sha256": "f" * 64,
                "uri": "https://open.canada.ca/data/changed-source",
            }
        ]
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError, match="external pin"):
        cohort.rebuild_canada(bundle.directory)


@pytest.mark.parametrize(
    "mutation", ["scope_target", "missing_record", "duplicate_record", "hold_target"]
)
def test_full_scope_decisions_cannot_be_inferred_from_names_or_points(
    bundle: Bundle,
    mutation: str,
) -> None:
    if mutation == "scope_target":
        bundle.spec["decisions"][0]["target_id"] = "auth:ca-dfhd:2"
    elif mutation == "missing_record":
        bundle.spec["records"].pop()
    elif mutation == "duplicate_record":
        bundle.spec["records"].append(copy.deepcopy(bundle.spec["records"][0]))
    else:
        bundle.spec["decisions"][-1]["target_id"] = "auth:fixture:10"
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError):
        cohort.rebuild_canada(bundle.directory)


@pytest.mark.parametrize(
    "mutation", ["country", "description", "source_ref", "id", "order", "count"]
)
def test_unchanged_base_contract_includes_all_old_fields_and_order(
    bundle: Bundle,
    base1999: list[Site],
    mutation: str,
) -> None:
    base = list(base1999)
    if mutation == "country":
        assert base[0].geography
        base[0] = base[0].model_copy(
            update={
                "geography": base[0].geography.model_copy(update={"countries": ["FR"]}),
            }
        )
    elif mutation == "description":
        base[0] = base[0].model_copy(update={"description": "Changed old document"})
    elif mutation == "source_ref":
        base[0] = base[0].model_copy(update={"source_refs": []})
    elif mutation == "id":
        base[0] = base[0].model_copy(update={"id": "auth:changed:0"})
    elif mutation == "order":
        base.reverse()
    else:
        base.pop()
    with pytest.raises(cohort.CanadaError, match="1999"):
        cohort.load_canada(base, bundle.directory)


def test_existing_component_targets_must_be_in_original_base(
    bundle: Bundle, base1999: list[Site]
) -> None:
    bundle.spec["decisions"][4]["target_id"] = "auth:fixture:absent"
    bundle.pin_roster()
    bundle.compile()
    with pytest.raises(cohort.CanadaError, match="target is absent"):
        cohort.load_canada(base1999, bundle.directory)


def test_optional_source_cache_hash_and_path_guards(bundle: Bundle) -> None:
    assert cohort.verify_source_cache(bundle.cache, bundle.directory) == 6
    (bundle.cache / "provider-point.json").write_bytes(b"tamper")
    with pytest.raises(cohort.CanadaError, match="snapshot differs"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)
    bundle.spec["decisions"][-1]["source_files"][0]["filename"] = "../escape"
    bundle.pin_spec()
    with pytest.raises(cohort.CanadaError):
        cohort.rebuild_canada(bundle.directory)


@pytest.mark.parametrize("filename", [cohort.SPEC_FILE, cohort.SITES_FILE, cohort.MANIFEST_FILE])
def test_compiled_artifacts_are_not_self_authenticating(
    bundle: Bundle,
    base1999: list[Site],
    filename: str,
) -> None:
    path = bundle.directory / filename
    path.write_bytes(path.read_bytes().replace(b"Synthetic", b"Tampered"))
    with pytest.raises(cohort.CanadaError):
        cohort.load_canada(base1999, bundle.directory)
