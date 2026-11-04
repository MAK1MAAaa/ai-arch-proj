"""Small synthetic receipts exercise offline contracts, not real cultural-source assertions."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from archsearch import hong_kong_data as cohort
from archsearch.corpus import build_document
from archsearch.domain import Site
from archsearch.supplement_data import base_contract


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@pytest.fixture(scope="module")
def base() -> list[Site]:
    source = {
        "id": "qualification:synthetic",
        "title": "Synthetic qualification",
        "uri": "https://example.org/synthetic",
        "publisher": "Synthetic authority",
        "excerpt": "Synthetic cultural fixture.",
    }
    return [
        Site.model_validate(
            {
                "id": f"auth:fixture:{index}",
                "title": f"Synthetic base {index}",
                "description": "Original source content",
                "details": "Original details",
                "names": ["Original alias"],
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
                    "countries": ["CN"],
                    "regions": ["asia-pacific"],
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
    spec: dict[str, Any]
    monkeypatch: pytest.MonkeyPatch

    def pin_spec(self) -> None:
        payload = encoded(self.spec)
        (self.directory / cohort.SPEC_FILE).write_bytes(payload)
        self.monkeypatch.setattr(cohort, "SPEC_SHA256", digest(payload))

    def pin_roster(self) -> None:
        self.monkeypatch.setattr(
            cohort, "SOURCE_ROSTER_SHA256", digest(encoded(self.spec["source_feature_roster"]))
        )

    def pin_facts(self) -> None:
        facts = cohort._source_facts(cohort.HongKongSpec.model_validate(self.spec))
        self.monkeypatch.setattr(cohort, "SOURCE_FACTS_SHA256", digest(encoded(facts)))

    def compile(self) -> dict[str, Any]:
        self.pin_spec()
        parsed = cohort.HongKongSpec.model_validate(self.spec)
        sites = cohort.compile_hong_kong(parsed)
        self.monkeypatch.setattr(
            cohort,
            "SITES_SHA256",
            digest(encoded([site.model_dump(mode="json") for site in sites])),
        )
        return cohort.rebuild_hong_kong(self.directory)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base: list[Site]) -> Bundle:
    cache = tmp_path / "cache"
    cache.mkdir()

    def evidence(
        key: str,
        uri: str,
        text: str = "Synthetic whole qualification.",
        license_name: str | None = None,
    ) -> dict[str, Any]:
        payload = f"Synthetic fixture only: {key}".encode()
        filename = key + ".txt"
        (cache / filename).write_bytes(payload)
        return {
            "source": {
                "id": "fixture:" + key,
                "title": "Synthetic source",
                "uri": uri,
                "publisher": "Synthetic authority",
                "license": license_name,
                "excerpt": text,
            },
            "artifact": {"filename": filename, "uri": uri, "sha256": digest(payload)},
        }

    metadata = evidence("metadata", cohort.METADATA_URI, "Synthetic Hong Kong source fixture.")
    terms = evidence("terms", cohort.TERMS_URI, license_name=cohort.CSDI_LICENSE)
    rights = evidence("rights", "https://www.amo.gov.hk/en/copyright/index.html")
    country = evidence(
        "country", cohort.UN_M49_URI, "China, Hong Kong Special Administrative Region"
    )
    monkeypatch.setattr(cohort, "UN_M49_SHA256", country["artifact"]["sha256"])
    rows = [
        {
            "FILE_REF": f"SYN-{index}",
            "NAME": f"Synthetic feature {index}",
            "NAME_TC": f"测试部件{index}",
            "ADDRESS": "Synthetic address",
            "ADDRESS_TC": "测试地址",
            "DISTRICT": "Synthetic district",
            "DATA_OWNER": "AMO",
            "DISTRIC_TC": "测试区",
            "DEC_YEAR": 2000,
            "DEC_YE_TC": 2000,
            "FILEREF_TC": f"SYN-{index}",
            "DETAIL": "https://www.amo.gov.hk/en/historic-buildings/monuments/"
            "hong-kong-island/monuments_01/index.html",
            "DETAIL_TC": "https://www.amo.gov.hk/tc/historic-buildings/monuments/"
            "hong-kong-island/monuments_01/index.html",
            "DATASET": "Synthetic source dataset",
            "DATASET_TC": "测试来源",
            "URL_IMAGE": "https://example.org/not-downloaded",
            "OBJECTID": index,
            "Shape__Length": 1.0,
            "Shape__Area": 1.0,
        }
        for index in range(1, 7)
    ]
    features = [
        {
            "attributes": row,
            "geometry": {
                "rings": [
                    [[114.0, 22.0], [114.1, 22.0], [114.1, 22.1], [114.0, 22.1], [114.0, 22.0]]
                ]
            },
        }
        for row in rows
    ]
    page = {
        "geometryType": "esriGeometryPolygon",
        "spatialReference": {"wkid": 4326},
        "features": features,
    }
    page_payload = encoded(page)
    (cache / "page.json").write_bytes(page_payload)
    uri = cohort.QUERY_URI + "?outFields=*&outSR=4326&returnGeometry=true"
    page_artifact = {"filename": "page.json", "uri": uri, "sha256": digest(page_payload)}
    bindings = [
        {
            "source_row_id": (
                f"{cohort.DATASET_ID}/{cohort.LAYER_NAME}/{row['OBJECTID']}/{row['FILE_REF']}"
            ),
            "source_row": row,
            "artifact": page_artifact,
            "page_index": 0,
            "feature_index": index,
            "feature_sha256": cohort.feature_hash(features[index]),
            "source_crs": 2326,
            "spatial_reference": 4326,
            "geometry_type": "esriGeometryPolygon",
            "ring_count": 1,
            "coordinate_records": 5,
        }
        for index, row in enumerate(rows)
    ]
    decisions = []
    records = []
    for number, feature_indices, disposition in [
        (1, [0, 1], "include"),
        (2, [], "include"),
        (3, [2], "existing"),
        (4, [3], "component"),
        (5, [4], "hold"),
    ]:
        source = evidence(f"whole-{number}", f"https://www.amo.gov.hk/en/synthetic-{number}")
        whole = {
            "official_list_number": number,
            "business_reference": number,
            "title_en": f"Synthetic whole {number}",
            "title_tc": f"测试整体{number}",
            "business_uri": "https://www.amo.gov.hk/en/historic-buildings/monuments/"
            f"hong-kong-island/monuments_{number:02d}/index.html",
            "business_uri_tc": "https://www.amo.gov.hk/tc/historic-buildings/monuments/"
            f"hong-kong-island/monuments_{number:02d}/index.html",
            "directory_area": "hong-kong-island",
            "source_features": [copy.deepcopy(bindings[index]) for index in feature_indices],
            "scope_evidence": [source],
            "scope_relations": [
                {
                    "feature_id": bindings[index]["source_row"]["OBJECTID"],
                    "relation": "same_whole" if index != 1 else "component_of_whole",
                    "evidence": [source],
                }
                for index in feature_indices
            ],
        }
        target = (
            f"auth:hk-amo:monuments-{number}"
            if disposition == "include"
            else None
            if disposition == "hold"
            else base[0 if disposition == "existing" else 1].id
        )
        decisions.append(
            {
                "whole": copy.deepcopy(whole),
                "disposition": disposition,
                "target_id": target,
                "reason": "Synthetic decision only.",
                "evidence": [source],
            }
        )
        if disposition == "include":
            records.append(
                {
                    "whole": copy.deepcopy(whole),
                    "evidence": [source],
                    "independent_review": {
                        "status": "approved",
                        "reviewer": "Synthetic reviewer",
                        "method": "Synthetic fixture, no real approval.",
                        "reviewed_at": "2026-11-05",
                    },
                    "provenance": {"synthetic_fixture": True},
                }
            )
    spec = {
        "schema_version": 1,
        "cohort_version": cohort.COHORT_VERSION,
        "corpus_version": cohort.CORPUS_VERSION,
        **base_contract(base),
        "candidates_sha256": "1" * 64,
        "handoff_sha256": "2" * 64,
        "independent_report_sha256": "3" * 64,
        "selection": cohort.SELECTION,
        "metadata": {
            "dataset_id": cohort.DATASET_ID,
            "layer_id": 0,
            "layer_name": cohort.LAYER_NAME,
            "source_crs": 2326,
            "provider_output_crs": 4326,
            "release_date": "2026-01-30",
            "evidence": metadata,
        },
        "rights": {
            "csdi_license": cohort.CSDI_LICENSE,
            "csdi_terms": terms,
            "amo_rights": rights,
            "reuse_scope": "short_structured_facts_only_no_photos_or_source_prose",
        },
        "countries": [
            {
                "code": "HK",
                "label": "Hong Kong",
                "region": "asia-pacific",
                "source_code_literal": "HK",
                "source_label_literal": "China, Hong Kong Special Administrative Region",
                "source_m49_cells": [
                    "001",
                    "World",
                    "142",
                    "Asia",
                    "030",
                    "Eastern Asia",
                    "",
                    "",
                    "China, Hong Kong Special Administrative Region",
                    "344",
                    "HK",
                    "HKG",
                    "",
                    "",
                    "",
                ],
                "evidence": [country, metadata],
            }
        ],
        "source_feature_roster": bindings,
        "source_artifacts": [page_artifact],
        "decisions": decisions,
        "records": records,
        "held_features": [
            {
                "feature": copy.deepcopy(bindings[-1]),
                "reason": "Unknown whole scope.",
                "evidence": [metadata],
            }
        ],
    }
    for name, pin in [
        ("CANDIDATES_SHA256", "1" * 64),
        ("HANDOFF_SHA256", "2" * 64),
        ("INDEPENDENT_REVIEW_SHA256", "3" * 64),
        ("SITES_SHA256", "4" * 64),
    ]:
        monkeypatch.setattr(cohort, name, pin)
    result = Bundle(tmp_path, cache, spec, monkeypatch)
    result.pin_roster()
    result.pin_facts()
    result.pin_spec()
    return result


def test_unapproved_production_contract_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cohort, "SPEC_SHA256", "")
    with pytest.raises(cohort.HongKongError, match="not configured"):
        cohort.rebuild_hong_kong(tmp_path)


def test_offline_compile_preserves_base_and_unknown_states(
    bundle: Bundle, base: list[Site]
) -> None:
    before = [site.model_dump(mode="json") for site in base]
    documents = [build_document(site) for site in base]
    manifest = bundle.compile()
    loaded = cohort.load_hong_kong(base, bundle.directory)
    assert [site.model_dump(mode="json") for site in loaded[: cohort.BASE_COUNT]] == before
    assert [build_document(site) for site in loaded[: cohort.BASE_COUNT]] == documents
    assert manifest["counts"]["added"] == 2
    assert manifest["counts"]["source_polygon_sites"] == 1
    assert manifest["counts"]["source_polygon_features"] == 2
    assert manifest["counts"]["held_features"] == 1
    assert manifest["counts"]["adopted_representative_points"] == 0
    assert manifest["counts"]["new_historical_phases"] == 0
    assert (
        manifest["independent_source_review"]["source_facts_sha256"] == cohort.SOURCE_FACTS_SHA256
    )
    assert cohort.new_country_labels(bundle.directory) == {"HK": "Hong Kong"}
    assert cohort.verify_source_cache(bundle.cache, bundle.directory) == 10
    for site in loaded[cohort.BASE_COUNT :]:
        assert site.repr_point is None and site.location_precision is None
        assert not site.periods and not site.period_evidence and not site.chronology.phases
        assert site.description == site.description_zh == ""
        assert site.geography and site.geography.point_count == 0
    compound = next(site for site in loaded if site.id == "auth:hk-amo:monuments-1")
    assert compound.names == ["测试整体1"]
    assert "测试部件2" in build_document(compound)
    assert "Synthetic feature 2" not in compound.names
    assert "来源要素事实（不增加遗址条目数）" in compound.details
    assert "现代法定古蹟宣布年份" in compound.details
    first = (bundle.directory / cohort.SITES_FILE).read_bytes()
    assert cohort.rebuild_hong_kong(bundle.directory) == manifest
    assert (bundle.directory / cohort.SITES_FILE).read_bytes() == first


def test_review_cannot_self_sign_changed_source(bundle: Bundle) -> None:
    changed = copy.deepcopy(bundle.spec)
    changed["candidates_sha256"] = "9" * 64
    (bundle.directory / cohort.SPEC_FILE).write_bytes(encoded(changed))
    with pytest.raises(cohort.HongKongError, match="independent pin"):
        cohort._spec(bundle.directory)
    bundle.spec = changed
    bundle.pin_spec()
    with pytest.raises(cohort.HongKongError, match="binding differs"):
        cohort._spec(bundle.directory)


def test_external_roster_pin_rejects_changed_original_attribute(bundle: Bundle) -> None:
    bundle.spec["source_feature_roster"][0]["source_row"]["ADDRESS"] = "Modified source attribute"
    bundle.pin_spec()
    with pytest.raises(cohort.HongKongError, match="source-roster binding"):
        cohort._spec(bundle.directory)


@pytest.mark.parametrize("mutation", ["title", "regroup"])
def test_resigning_projection_cannot_change_independently_approved_whole_facts(
    bundle: Bundle, base: list[Site], mutation: str
) -> None:
    bundle.compile()
    original_facts_pin = cohort.SOURCE_FACTS_SHA256
    if mutation == "title":
        bundle.spec["decisions"][0]["whole"]["title_en"] = "Unapproved replacement whole title"
    else:
        included = bundle.spec["decisions"][0]["whole"]
        existing = bundle.spec["decisions"][2]["whole"]
        included["source_features"][0], existing["source_features"][0] = (
            existing["source_features"][0],
            included["source_features"][0],
        )
        included["scope_relations"][0]["feature_id"] = 3
        existing["scope_relations"][0]["feature_id"] = 1
    bundle.spec["records"][0]["whole"] = copy.deepcopy(bundle.spec["decisions"][0]["whole"])
    cohort._validate_spec(cohort.HongKongSpec.model_validate(bundle.spec))
    with pytest.raises(cohort.HongKongError, match="complete approved source facts"):
        bundle.compile()
    assert cohort.SOURCE_FACTS_SHA256 == original_facts_pin
    with pytest.raises(cohort.HongKongError, match="complete approved source facts"):
        cohort.load_hong_kong(base, bundle.directory)


@pytest.mark.parametrize(
    "pin",
    [
        "CANDIDATES_SHA256",
        "HANDOFF_SHA256",
        "INDEPENDENT_REVIEW_SHA256",
        "SOURCE_ROSTER_SHA256",
        "SOURCE_FACTS_SHA256",
        "SPEC_SHA256",
        "SITES_SHA256",
    ],
)
def test_every_external_approval_pin_is_required(bundle: Bundle, pin: str) -> None:
    bundle.monkeypatch.setattr(cohort, pin, "")
    with pytest.raises(cohort.HongKongError, match="not configured"):
        cohort._spec(bundle.directory)


def test_base_and_existing_targets_cannot_be_rewritten(bundle: Bundle, base: list[Site]) -> None:
    bundle.compile()
    changed = [base[0].model_copy(update={"details": "Changed"}), *base[1:]]
    with pytest.raises(cohort.HongKongError, match="unchanged2976"):
        cohort.load_hong_kong(changed, bundle.directory)
    bundle.spec["decisions"][2]["target_id"] = "auth:fixture:absent"
    bundle.pin_facts()
    bundle.compile()
    with pytest.raises(cohort.HongKongError, match="target is absent"):
        cohort.load_hong_kong(base, bundle.directory)


def test_compiled_sites_and_manifest_tampering_fail(bundle: Bundle, base: list[Site]) -> None:
    bundle.compile()
    sites_path = bundle.directory / cohort.SITES_FILE
    sites_path.write_bytes(sites_path.read_bytes() + b" ")
    with pytest.raises(cohort.HongKongError, match="sites differ"):
        cohort.load_hong_kong(base, bundle.directory)
    bundle.compile()
    manifest_path = bundle.directory / cohort.MANIFEST_FILE
    manifest = json.loads(manifest_path.read_bytes())
    manifest["counts"]["new_historical_phases"] = 1
    manifest_path.write_bytes(encoded(manifest))
    with pytest.raises(cohort.HongKongError, match="manifest differs"):
        cohort.load_hong_kong(base, bundle.directory)


def test_cache_checks_original_bytes_and_feature_receipt(bundle: Bundle) -> None:
    bundle.compile()
    path = bundle.cache / "page.json"
    original = path.read_bytes()
    path.write_bytes(original + b" ")
    with pytest.raises(cohort.HongKongError, match="snapshot differs"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)
    path.write_bytes(original)
    bundle.spec["source_feature_roster"][0]["feature_sha256"] = "9" * 64
    bundle.spec["decisions"][0]["whole"]["source_features"][0]["feature_sha256"] = "9" * 64
    bundle.spec["records"][0]["whole"]["source_features"][0]["feature_sha256"] = "9" * 64
    bundle.pin_roster()
    bundle.pin_facts()
    bundle.pin_spec()
    with pytest.raises(cohort.HongKongError, match="binding differs"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)


def test_scope_and_unassigned_features_require_explicit_decisions(bundle: Bundle) -> None:
    whole = copy.deepcopy(bundle.spec["records"][0]["whole"])
    whole["scope_relations"].pop()
    with pytest.raises(ValidationError, match="exactly one reviewed"):
        cohort.HongKongWhole.model_validate(whole)
    bundle.spec["held_features"] = []
    bundle.pin_facts()
    bundle.pin_spec()
    with pytest.raises(cohort.HongKongError, match="every unchanged original feature"):
        cohort._spec(bundle.directory)


def test_business_page_identity_is_not_guessed_from_names_or_oid(bundle: Bundle) -> None:
    whole = copy.deepcopy(bundle.spec["records"][0]["whole"])
    whole["business_reference"] = 99
    with pytest.raises(ValidationError, match="business page"):
        cohort.HongKongWhole.model_validate(whole)
    row = copy.deepcopy(bundle.spec["source_feature_roster"][0]["source_row"])
    row["OBJECTID"] = True
    with pytest.raises(ValidationError):
        cohort.CsdiSourceRow.model_validate(row)
    row["OBJECTID"] = 1
    row["invented_field"] = "Unsupported source value"
    with pytest.raises(ValidationError):
        cohort.CsdiSourceRow.model_validate(row)


def test_custom_rights_are_not_relabelled_as_open_licence(bundle: Bundle) -> None:
    rights = copy.deepcopy(bundle.spec["rights"])
    rights["amo_rights"]["source"]["license"] = "CC BY 4.0"
    with pytest.raises(ValidationError, match="custom CSDI terms"):
        cohort.RightsReview.model_validate(rights)


def test_country_code_and_display_label_keep_separate_source_roles(bundle: Bundle) -> None:
    country = copy.deepcopy(bundle.spec["countries"][0])
    country["source_m49_cells"][10] = "CN"
    with pytest.raises(ValidationError, match="frozen M49 row"):
        cohort.CountryAssociation.model_validate(country)
    country = copy.deepcopy(bundle.spec["countries"][0])
    country["evidence"].pop()
    with pytest.raises(ValidationError, match="separate source Hong Kong literal"):
        cohort.CountryAssociation.model_validate(country)


def test_m49_legacy_comment_is_not_an_active_country_attribute(bundle: Bundle) -> None:
    country = copy.deepcopy(bundle.spec["countries"][0])
    assert len(country["source_m49_cells"]) == 15
    country["source_m49_cells"].append("Developing")
    with pytest.raises(ValidationError, match="at most 15"):
        cohort.CountryAssociation.model_validate(country)
    country["source_m49_cells"].pop()
    country["source_m49_cells"][-1] = "Developing"
    with pytest.raises(ValidationError, match="frozen M49 row"):
        cohort.CountryAssociation.model_validate(country)
