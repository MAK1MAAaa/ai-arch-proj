"""Small synthetic provider pages preserve source polygons and isolate source failures."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from archsearch import hong_kong_areas as areas
from archsearch import hong_kong_data as cohort
from archsearch.registered_areas import AreaSourceGroup, RegisteredArea, RegisteredAreasIndex


def encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def evidence(key: str, uri: str, license_name: str | None = None) -> dict[str, Any]:
    return {
        "source": {
            "id": "fixture:" + key,
            "title": "Synthetic short fact",
            "uri": uri,
            "publisher": "Synthetic authority",
            "excerpt": "Synthetic whole identity.",
            "license": license_name,
        },
        "artifact": {"filename": key + ".txt", "uri": uri, "sha256": "b" * 64},
    }


@dataclass
class Bundle:
    directory: Path
    cache: Path
    spec: cohort.HongKongSpec
    monkeypatch: pytest.MonkeyPatch

    def publish(self) -> dict[str, Any]:
        raw = areas._bytes(self.spec.model_dump(mode="json", by_alias=True))
        self.monkeypatch.setattr(cohort, "SPEC_SHA256", digest(raw))
        self.monkeypatch.setattr(cohort, "_spec", lambda _: self.spec)
        self.monkeypatch.setattr(areas, "SOURCE_REVIEW_SHA256", self.spec.independent_report_sha256)
        self.monkeypatch.setattr(areas, "SOURCE_ROSTER_SHA256", areas._roster_hash(self.spec))
        value = areas.compile_hong_kong_areas(
            self.spec,
            self.cache,
            review_sha256=cohort.SPEC_SHA256,
        )
        self.monkeypatch.setattr(areas, "AREA_SHA256", digest(areas._bytes(value)))
        sites = encode([{"id": row.whole.project_id} for row in self.spec.records])
        self.monkeypatch.setattr(cohort, "SITES_SHA256", digest(sites))
        (self.directory / cohort.SITES_FILE).write_bytes(sites)
        (self.directory / cohort.MANIFEST_FILE).write_bytes(b"{}")
        areas.rebuild_hong_kong_areas(self.cache, self.directory)
        return value

    def changed_page(self, filename: str, value: dict[str, Any]) -> cohort.HongKongSpec:
        raw = encode(value)
        (self.cache / filename).write_bytes(raw)
        contract = self.spec.model_dump(mode="json", by_alias=True)

        def resign(item: Any) -> None:
            if isinstance(item, list):
                for child in item:
                    resign(child)
            elif isinstance(item, dict):
                if item.get("filename") == filename and "sha256" in item:
                    item["sha256"] = digest(raw)
                for child in item.values():
                    resign(child)

        resign(contract)
        return cohort.HongKongSpec.model_validate(contract)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Bundle:
    cache = tmp_path / "cache"
    cache.mkdir()
    field_names = [field.alias or name for name, field in cohort.CsdiSourceRow.model_fields.items()]
    rows = []
    for identifier in range(1, 4):
        row = {name: None for name in field_names}
        row.update(
            {
                "OBJECTID": identifier,
                "FILE_REF": f"SYN-{identifier}",
                "NAME": f"Synthetic component {identifier}",
                "NAME_TC": f"测试部件{identifier}",
                "Shape__Length": 1.0,
                "Shape__Area": 1,
            }
        )
        rows.append(row)
    first_ring = [[114, 22], [114.2, 22], [114.2, 22.2], [114, 22]]
    second_ring = [[114.02, 22.02], [114.03, 22.02], [114.03, 22.03], [114.02, 22.02]]
    features = [
        {"attributes": row, "geometry": {"rings": [copy.deepcopy(first_ring)]}} for row in rows
    ]
    features[0]["geometry"]["rings"].append(second_ring)
    bindings = []
    artifacts = []
    for page_index, group in enumerate([features[:2], features[2:]]):
        filename = f"page-{page_index}.json"
        page = {
            "geometryType": "esriGeometryPolygon",
            "spatialReference": {"wkid": 4326, "latestWkid": 4326},
            "fields": [{"name": name} for name in field_names],
            "features": group,
            "exceededTransferLimit": page_index == 0,
        }
        raw = encode(page)
        (cache / filename).write_bytes(raw)
        uri = (
            cohort.QUERY_URI + "?where=1%3D1&outFields=*&orderByFields=OBJECTID"
            f"&resultOffset={page_index * 2}&resultRecordCount=2&returnGeometry=true"
            "&outSR=4326&returnZ=false&returnM=false&f=json"
        )
        artifact = {"filename": filename, "uri": uri, "sha256": digest(raw)}
        artifacts.append(artifact)
        for feature_index, feature in enumerate(group):
            row = feature["attributes"]
            bindings.append(
                {
                    "source_row_id": f"{cohort.DATASET_ID}/{cohort.LAYER_NAME}/"
                    f"{row['OBJECTID']}/{row['FILE_REF']}",
                    "source_row": row,
                    "artifact": artifact,
                    "page_index": page_index,
                    "feature_index": feature_index,
                    "feature_sha256": cohort.feature_hash(feature),
                    "source_crs": 2326,
                    "spatial_reference": 4326,
                    "geometry_type": "esriGeometryPolygon",
                    "ring_count": len(feature["geometry"]["rings"]),
                    "coordinate_records": sum(len(ring) for ring in feature["geometry"]["rings"]),
                }
            )
    proof = evidence("whole", "https://www.amo.gov.hk/en/synthetic")
    decisions = []
    records = []
    for number, indices, disposition in [
        (1, [0, 1], "include"),
        (139, [], "include"),
        (3, [2], "existing"),
    ]:
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
            "source_features": [bindings[index] for index in indices],
            "scope_evidence": [proof],
            "scope_relations": [
                {
                    "feature_id": bindings[index]["source_row"]["OBJECTID"],
                    "relation": "component_of_whole",
                    "evidence": [proof],
                }
                for index in indices
            ],
        }
        decisions.append(
            {
                "whole": whole,
                "disposition": disposition,
                "target_id": f"auth:hk-amo:monuments-{number}"
                if disposition == "include"
                else "auth:fixture:existing",
                "reason": "Independent synthetic whole fixture.",
                "evidence": [proof],
            }
        )
        if disposition == "include":
            records.append(
                {
                    "whole": whole,
                    "independent_review": {
                        "status": "approved",
                        "reviewer": "Synthetic independent agent",
                        "method": "Original whole and component fixture comparison.",
                        "reviewed_at": "2026-11-05",
                    },
                    "evidence": [proof],
                    "provenance": {},
                }
            )
    metadata = evidence("metadata", cohort.METADATA_URI)
    metadata["source"]["excerpt"] = "Declared monuments in Hong Kong."
    country = evidence("country", cohort.UN_M49_URI)
    country["source"]["excerpt"] = "China, Hong Kong Special Administrative Region; HK."
    country["artifact"]["sha256"] = cohort.UN_M49_SHA256
    spec = cohort.HongKongSpec.model_validate(
        {
            "schema_version": 1,
            "cohort_version": cohort.COHORT_VERSION,
            "corpus_version": cohort.CORPUS_VERSION,
            "base_count": cohort.BASE_COUNT,
            "base_ids_sha256": "a" * 64,
            "base_sites_sha256": "a" * 64,
            "candidates_sha256": "c" * 64,
            "handoff_sha256": "d" * 64,
            "independent_report_sha256": "e" * 64,
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
                "csdi_terms": evidence("terms", cohort.TERMS_URI, cohort.CSDI_LICENSE),
                "amo_rights": evidence("rights", "https://www.amo.gov.hk/en/important-notices/"),
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
            "source_artifacts": artifacts,
            "decisions": decisions,
            "records": records,
        }
    )
    return Bundle(tmp_path, cache, spec, monkeypatch)


def test_complete_source_rows_and_multi_rings_preserve_original_values(bundle: Bundle) -> None:
    value = bundle.publish()
    first = value["sites"]["auth:hk-amo:monuments-1"]
    assert [area["provider_object_id"] for area in first] == [1, 2]
    assert [area["source_index"] for area in first] == [0, 1]
    assert len(first[0]["rings"]) == 2
    assert type(first[0]["rings"][0][0][0]) is int
    assert first[0]["rings"][0][0] == [114, 22]
    assert first[0]["source"]["sha256"] == bundle.spec.source_feature_roster[0].artifact.sha256
    assert first[0]["source"]["license"] == cohort.CSDI_LICENSE
    assert "Government of the Hong Kong Special Administrative Region" in first[0]["source"]["name"]
    assert first[0]["source"]["license_uri"] == cohort.TERMS_URI
    assert value["counts"]["source_features"] == 3
    assert value["counts"]["adopted_features"] == 2
    assert value["counts"]["source_rings"] == 4
    assert set(value["sites"]) == {"auth:hk-amo:monuments-1"}
    assert "auth:hk-amo:monuments-139" in value["site_ids"]
    assert "代表点" in value["note"] and "未提供几何" in value["note"]


@pytest.mark.parametrize(
    "mutation",
    ["missing", "unknown", "reordered", "attribute", "crs", "geometry", "fields", "truncated"],
)
def test_resigning_a_page_cannot_hide_incomplete_or_changed_source_facts(
    bundle: Bundle,
    mutation: str,
) -> None:
    value = json.loads((bundle.cache / "page-0.json").read_bytes())
    if mutation == "missing":
        value["features"].pop()
    elif mutation == "unknown":
        value["features"].append(copy.deepcopy(value["features"][0]))
    elif mutation == "reordered":
        value["features"].reverse()
    elif mutation == "attribute":
        value["features"][0]["attributes"]["NAME"] = "Changed source title"
    elif mutation == "crs":
        value["spatialReference"]["wkid"] = 2326
    elif mutation == "geometry":
        value["features"][0]["geometry"]["centroid"] = [114, 22]
    elif mutation == "fields":
        value["fields"].reverse()
    else:
        value["exceededTransferLimit"] = False
    spec = bundle.changed_page("page-0.json", value)
    with pytest.raises(areas.HongKongAreasError):
        areas.compile_hong_kong_areas(spec, bundle.cache)


def test_original_hash_and_closed_rings_are_required(bundle: Bundle) -> None:
    raw = (bundle.cache / "page-0.json").read_bytes()
    (bundle.cache / "page-0.json").write_bytes(raw + b" ")
    with pytest.raises(areas.HongKongAreasError, match="SHA"):
        areas.compile_hong_kong_areas(bundle.spec, bundle.cache)
    with pytest.raises(ValueError, match="closed"):
        RegisteredArea.validate_rings([[[114, 22], [115, 22], [115, 23], [114, 23]]])


def test_even_a_new_feature_hash_cannot_admit_an_open_source_ring(bundle: Bundle) -> None:
    value = json.loads((bundle.cache / "page-0.json").read_bytes())
    value["features"][0]["geometry"]["rings"][0][-1] = [114.5, 22]
    spec = bundle.changed_page("page-0.json", value)
    contract = spec.model_dump(mode="json", by_alias=True)

    def update_feature_hash(item: Any) -> None:
        if isinstance(item, dict):
            if item.get("source_row", {}).get("OBJECTID") == 1:
                item["feature_sha256"] = cohort.feature_hash(value["features"][0])
            for child in item.values():
                update_feature_hash(child)
        elif isinstance(item, list):
            for child in item:
                update_feature_hash(child)

    update_feature_hash(contract)
    with pytest.raises(areas.HongKongAreasError, match="closed"):
        areas.compile_hong_kong_areas(cohort.HongKongSpec.model_validate(contract), bundle.cache)


def test_source_query_cannot_add_simplification_or_change_the_original_offset(
    bundle: Bundle,
) -> None:
    for suffix in ["&maxAllowableOffset=10", "&resultOffset=1"]:
        contract = bundle.spec.model_dump(mode="json", by_alias=True)

        def change_uri(item: Any, addition: str = suffix) -> None:
            if isinstance(item, dict):
                if item.get("filename") == "page-0.json" and "uri" in item:
                    item["uri"] += addition
                for child in item.values():
                    change_uri(child, addition)
            elif isinstance(item, list):
                for child in item:
                    change_uri(child, addition)

        change_uri(contract)
        with pytest.raises(areas.HongKongAreasError, match="查询"):
            areas.compile_hong_kong_areas(
                cohort.HongKongSpec.model_validate(contract), bundle.cache
            )


def test_full_roster_omissions_and_order_changes_are_rejected(bundle: Bundle) -> None:
    for roster in [
        bundle.spec.source_feature_roster[:-1],
        list(reversed(bundle.spec.source_feature_roster)),
    ]:
        spec = bundle.spec.model_copy(update={"source_feature_roster": roster})
        with pytest.raises(areas.HongKongAreasError):
            areas.compile_hong_kong_areas(spec, bundle.cache)


@pytest.mark.parametrize("disposition", ["existing", "component", "hold", "held-feature"])
def test_unadopted_decisions_are_verified_without_inheriting_their_geometry(
    bundle: Bundle,
    disposition: str,
) -> None:
    contract = bundle.spec.model_dump(mode="json", by_alias=True)
    decision = contract["decisions"][-1]
    if disposition == "held-feature":
        held = decision["whole"]["source_features"].pop()
        decision["whole"]["scope_relations"] = []
        decision["disposition"] = "hold"
        decision["target_id"] = None
        contract["held_features"] = [
            {
                "feature": held,
                "reason": "Synthetic unresolved source.",
                "evidence": decision["evidence"],
            }
        ]
    else:
        decision["disposition"] = disposition
        if disposition == "hold":
            decision["target_id"] = None
    spec = cohort.HongKongSpec.model_validate(contract)
    value = areas.compile_hong_kong_areas(spec, bundle.cache)
    assert value["counts"]["source_features"] == 3
    assert value["counts"]["adopted_features"] == 2
    assert set(value["sites"]) == {"auth:hk-amo:monuments-1"}
    (bundle.cache / "page-1.json").write_bytes(b"damaged unadopted source")
    with pytest.raises(areas.HongKongAreasError, match="SHA"):
        areas.compile_hong_kong_areas(spec, bundle.cache)


def test_valid_runtime_never_reads_raw_cache_and_unmapped_wholes_succeed(bundle: Bundle) -> None:
    bundle.publish()
    for path in bundle.cache.iterdir():
        path.unlink()
    bundle.monkeypatch.setattr(areas, "_source_features", lambda *_: pytest.fail("read raw cache"))
    group = areas.load_hong_kong_area_group(bundle.directory)
    assert group is not None and group.ready
    assert group.site_ids == {"auth:hk-amo:monuments-1", "auth:hk-amo:monuments-139"}
    index = RegisteredAreasIndex(bundle.directory, sources=[group])
    empty = index.response("auth:hk-amo:monuments-139", "fixture-v1")
    assert empty.ready and not empty.features and empty.label == "来源古迹多边形"
    assert index.response("auth:hk-amo:monuments-1", "fixture-v1").features


@pytest.mark.parametrize("failure", ["missing", "corrupt", "deep", "unconfigured", "facts"])
def test_sidecar_failure_retains_all_known_hk_contexts_and_another_source(
    bundle: Bundle,
    failure: str,
) -> None:
    value = bundle.publish()
    if failure == "missing":
        (bundle.directory / areas.AREAS_FILE).unlink()
    elif failure == "corrupt":
        (bundle.directory / areas.AREAS_FILE).write_bytes(b"invalid")
    elif failure == "deep":
        raw = b"[" * 2000 + b"0" + b"]" * 2000
        (bundle.directory / areas.AREAS_FILE).write_bytes(raw)
        bundle.monkeypatch.setattr(areas, "AREA_SHA256", digest(raw))
    elif failure == "unconfigured":
        bundle.monkeypatch.setattr(areas, "AREA_SHA256", "")
    else:
        bundle.monkeypatch.setattr(areas, "SOURCE_ROSTER_SHA256", "f" * 64)
    group = areas.load_hong_kong_area_group(bundle.directory)
    assert group is not None and not group.ready and group.reason and "--rebuild" in group.reason
    assert group.site_ids == set(value["site_ids"])
    other = AreaSourceGroup(
        "other-v1",
        "现代遗产登记范围",
        "Synthetic other source.",
        frozenset({"auth:fixture:other"}),
        {
            "auth:fixture:other": [
                RegisteredArea.model_validate(value["sites"]["auth:hk-amo:monuments-1"][0])
            ]
        },
    )
    index = RegisteredAreasIndex(bundle.directory, sources=[other, group])
    assert index.response("auth:fixture:other", "fixture-v1").ready
    assert index.response("auth:fixture:other", "fixture-v1").features
    assert not index.response("auth:hk-amo:monuments-1", "fixture-v1").ready


@pytest.mark.parametrize("mutation", ["rings", "source", "order", "unknown-site", "binding"])
def test_a_resigned_sidecar_still_needs_original_rings_and_scope(
    bundle: Bundle,
    mutation: str,
) -> None:
    value = bundle.publish()
    rows = value["sites"]["auth:hk-amo:monuments-1"]
    if mutation == "rings":
        rows[0]["rings"][0][1][0] = 114.5
    elif mutation == "source":
        rows[0]["source"]["license"] = "CC0"
    elif mutation == "order":
        rows.reverse()
    elif mutation == "unknown-site":
        value["sites"]["auth:fixture:existing"] = rows
    else:
        value["source_review_sha256"] = "f" * 64
    raw = areas._bytes(value)
    (bundle.directory / areas.AREAS_FILE).write_bytes(raw)
    bundle.monkeypatch.setattr(areas, "AREA_SHA256", digest(raw))
    result = areas.load_hong_kong_area_group(bundle.directory)
    assert result is not None and not result.ready and not result.features


def test_review_failure_recovers_only_pinned_site_ids_and_absent_cohort_is_optional(
    bundle: Bundle,
) -> None:
    assert areas.load_hong_kong_area_group(bundle.directory) is None
    value = bundle.publish()

    def fail(_: Path) -> cohort.HongKongSpec:
        raise cohort.HongKongError("damaged source review")

    bundle.monkeypatch.setattr(cohort, "_spec", fail)
    group = areas.load_hong_kong_area_group(bundle.directory)
    assert group is not None and not group.ready and group.site_ids == set(value["site_ids"])


def test_rebuild_is_deterministic_and_bounded(bundle: Bundle) -> None:
    bundle.publish()
    before = (bundle.directory / areas.AREAS_FILE).read_bytes()
    assert areas.rebuild_hong_kong_areas(bundle.cache, bundle.directory)["source_features"] == 3
    assert (bundle.directory / areas.AREAS_FILE).read_bytes() == before
    assert areas.verify_hong_kong_area_cache(bundle.spec, bundle.cache)["source_coordinates"] == 16
    bundle.monkeypatch.setattr(areas, "MAX_SOURCE_BYTES", 4)
    with pytest.raises(areas.HongKongAreasError, match="容量"):
        areas.compile_hong_kong_areas(bundle.spec, bundle.cache)
