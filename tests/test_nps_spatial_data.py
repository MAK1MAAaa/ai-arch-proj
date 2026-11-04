"""Approved grouped provider points survive without inventing polygon centres."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from archsearch import nps_data
from archsearch import nps_spatial_data as spatial


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


@pytest.fixture
def spec(monkeypatch: pytest.MonkeyPatch) -> nps_data.NpsSpec:
    reference = "00000001"
    uri = "https://mapservices.nps.gov" + spatial.SERVICE_PATH + "?" + urlencode({
        "where": f"NRIS_Refnum='{reference}'", "outSR": "4326", "returnGeometry": "true",
        "orderByFields": "OBJECTID ASC",
    })
    artifact = {"filename": "geometry/0-00000001.json", "sha256": "2" * 64, "uri": uri}
    source = {"id": "qualification:fixture", "title": "Synthetic registration facts",
              "uri": "https://example.org/fixture", "publisher": "Synthetic fixture",
              "license": None, "excerpt": "Synthetic cultural qualification."}
    locations = [{
        "source_index": index, "coordinate": point, "name": "Synthetic wells",
        "ref": reference, "provider_layer": 0, "provider_source_index": index + 20,
        "provider_object_id": index + 1, "provider_feature_id": f"0:{index + 1}",
        "resource_id": "fixture-resource", "geometry_id": f"fixture-geometry-{index}",
        "geometry_type": "esriGeometryPoint", "source_uri": uri,
        "source_file": artifact["filename"], "source_sha256": artifact["sha256"],
        "spatial_reference": {"wkid": 4326, "latestWkid": 4326},
        "file_feature_index": index,
        "provider_attributes": {
            "NRIS_Refnum": reference, "PROPERTY_ID": reference, "OBJECTID": index + 1,
            "GEOM_ID": f"fixture-geometry-{index}", "CR_ID": "fixture-resource",
            "RESNAME": "Synthetic wells", "STATUS": "Listed", "State": "GUAM",
        },
    } for index, point in enumerate([[144.1, 13.1], [144.2, 13.2]])]
    site = {
        "id": "auth:nps-nris:" + reference, "title": "Synthetic wells",
        "description": "Synthetic fixture; not published source evidence.", "names": [],
        "types": ["historic-site"], "periods": [], "period_evidence": [],
        "repr_point": locations[0]["coordinate"], "location_precision": None,
        "source_kind": "supplement", "source_uri": source["uri"],
        "contributors": ["Synthetic fixture"], "source_refs": [source, {
            **source, "id": "point-fixture", "uri": uri, "excerpt": "",
        }], "chronology": {"status": "not_reviewed", "phases": [], "default_phase_id": None},
        "geography": {"authority_id": "supplement:auth:nps-nris:" + reference,
                      "countries": ["GU"], "regions": ["nps-pacific"],
                      "source": source, "point_count": 1},
    }
    decision = {
        "refnum": reference, "names": [site["title"]], "states": ["GUAM"],
        "resource_types": ["structure"], "source_feature_ids": ["0:1", "0:2"],
        "disposition": "include", "target_id": site["id"], "reason": "Synthetic fixture.",
        "evidence": [source], "source_files": [artifact],
    }
    value = nps_data.NpsSpec.model_validate({
        "schema_version": 1, "cohort_version": "nps-pacific-v1", "corpus_version": "global-v11",
        "base_count": 1807, "base_ids_sha256": "0" * 64, "base_sites_sha256": "0" * 64,
        "candidates_sha256": "0" * 64, "source_contract_report_sha256": "0" * 64,
        "independent_report_sha256": "0" * 64, "new_countries": {"GU": "Guam"},
        "selection": "Synthetic point fixtures only.", "decisions": [decision],
        "records": [{"site": site, "country_label": "Guam", "source_files": [artifact],
                     "location_disclosure": "public", "provenance": {
                         "source_locations": locations,
                         "source_records": [{**row["provider_attributes"], "source_layer": 0,
                                             "source_index": row["provider_source_index"]}
                                            for row in locations],
                     },
                     "coordinate": {"method": "authority", "point": site["repr_point"],
                                    "source_uri": uri, "note": "Synthetic provider reference."},
                     "independent_review": {"status": "approved", "reviewer": "fixture",
                                            "method": "Synthetic test only.",
                                            "reviewed_at": "2026-11-04"}}],
    })
    monkeypatch.setattr(nps_data, "_spec", lambda _: value)
    monkeypatch.setattr(nps_data, "SPEC_SHA256", "1" * 64)
    payload = encoded(spatial.location_payload(value))
    monkeypatch.setattr(spatial, "LOCATIONS_SHA256", hashlib.sha256(payload).hexdigest())
    return value


def test_two_source_points_keep_one_parent_and_first_representative(
    spec: nps_data.NpsSpec, tmp_path: Path,
) -> None:
    assert spatial.rebuild_nps_locations(tmp_path) == {"records": 1, "points": 2}
    first = (tmp_path / spatial.LOCATIONS_FILE).read_bytes()
    spatial.rebuild_nps_locations(tmp_path)
    assert (tmp_path / spatial.LOCATIONS_FILE).read_bytes() == first
    loaded = spatial.load_nps_locations(tmp_path)
    identifier = spec.records[0].site.id
    assert loaded.points[identifier] == ((144.1, 13.1), (144.2, 13.2))
    assert spec.records[0].site.repr_point == (144.1, 13.1)
    assert [row.source_index for row in loaded.records[identifier]] == [0, 1]
    assert "provider_source_index:21" in loaded.records[identifier][1].ref
    assert loaded.source["sha256"] == nps_data.SPEC_SHA256
    assert "derived" in loaded.source["name"]


@pytest.mark.parametrize("change", [
    "order", "duplicate", "null_coordinate", "boolean", "not_finite", "latitude", "index",
    "feature", "ref", "property", "geometry_id", "resource_id", "state", "sr", "query",
    "artifact", "polygon", "source_layer", "object_boolean", "representative", "missing",
    "provider_index", "file_index", "drop_second", "raw_index", "missing_originals",
])
def test_invalid_source_point_contract_rejected(spec: nps_data.NpsSpec, change: str) -> None:
    altered = copy.deepcopy(spec)
    rows = altered.records[0].provenance["source_locations"]
    if change == "order":
        rows.reverse()
    elif change == "duplicate":
        rows[1] = copy.deepcopy(rows[0])
        rows[1]["source_index"] = 1
    elif change == "representative":
        rows[0]["coordinate"] = [144.3, 13.3]
    elif change == "missing":
        del altered.records[0].provenance["source_locations"]
    elif change == "drop_second":
        rows.pop()
    elif change == "raw_index":
        altered.records[0].provenance["source_records"][0]["source_index"] = True
    elif change == "missing_originals":
        del altered.records[0].provenance["source_records"]
    else:
        field, value = {
            "null_coordinate": ("coordinate", [None, None]),
            "boolean": ("coordinate", [True, 13]),
            "not_finite": ("coordinate", [float("nan"), 13]),
            "latitude": ("coordinate", [144, 91]), "index": ("source_index", 5),
            "feature": ("provider_feature_id", "0:99"), "ref": ("ref", "00000002"),
            "sr": ("spatial_reference", {"wkid": 3857}),
            "query": ("source_uri", "https://example.org/changed"),
            "artifact": ("source_sha256", "3" * 64),
            "polygon": ("geometry_type", "esriGeometryPolygon"),
            "source_layer": ("provider_layer", 1), "object_boolean": ("provider_object_id", True),
            "geometry_id": ("geometry_id", "changed"), "resource_id": ("resource_id", "changed"),
            "provider_index": ("provider_source_index", 999999),
            "file_index": ("file_feature_index", 999999),
            "property": ("provider_attributes", {**rows[0]["provider_attributes"],
                                                  "PROPERTY_ID": "00000002"}),
            "state": ("provider_attributes", {**rows[0]["provider_attributes"], "State": "PALAU"}),
        }[change]
        rows[0][field] = value
    with pytest.raises((spatial.NpsSpatialError, ValueError)):
        spatial.location_payload(altered)


def test_changed_sidecar_cannot_self_sign_even_with_a_new_hash(
    spec: nps_data.NpsSpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    spatial.rebuild_nps_locations(tmp_path)
    path = tmp_path / spatial.LOCATIONS_FILE
    value = json.loads(path.read_bytes())
    value["sites"][0]["records"][1]["coordinate"] = [144.9, 13.9]
    changed = encoded(value)
    path.write_bytes(changed)
    monkeypatch.setattr(spatial, "LOCATIONS_SHA256", hashlib.sha256(changed).hexdigest())
    with pytest.raises(spatial.NpsSpatialError):
        spatial.load_nps_locations(tmp_path)


def test_missing_sidecar_has_no_invented_second_point(
    spec: nps_data.NpsSpec, tmp_path: Path,
) -> None:
    with pytest.raises(spatial.NpsSpatialError):
        spatial.load_nps_locations(tmp_path)
    assert spec.records[0].site.repr_point == (144.1, 13.1)


def test_unrequested_original_count_fields_remain_in_the_reviewed_contract(
    spec: nps_data.NpsSpec,
) -> None:
    for row in spec.records[0].provenance["source_records"]:
        row["NumCStru"] = 2
        row["MultiName"] = "Synthetic parent metadata only"
    assert len(spatial.location_payload(spec)["sites"][0]["records"]) == 2


def test_polygon_only_record_does_not_require_or_compute_a_point(
    spec: nps_data.NpsSpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = spec.model_dump(mode="json")
    record = value["records"][0]
    record["provenance"]["source_locations"] = []
    record["provenance"]["source_ranges"] = [{"geometry_type": "esriGeometryPolygon"}]
    record["provenance"]["source_records"] = [{
        "source_layer": 1, "source_index": 1, "OBJECTID": 1,
    }]
    value["decisions"][0]["source_feature_ids"] = ["1:1"]
    record["site"]["repr_point"] = None
    record["site"]["geography"]["point_count"] = 0
    record["coordinate"] = {"method": "unknown", "point": None, "source_uri": None,
                            "note": "No representative calculated from a range."}
    polygon = nps_data.NpsSpec.model_validate(value)
    monkeypatch.setattr(nps_data, "_spec", lambda _: polygon)
    expected = encoded(spatial.location_payload(polygon))
    monkeypatch.setattr(spatial, "LOCATIONS_SHA256", hashlib.sha256(expected).hexdigest())
    assert spatial.load_nps_locations(tmp_path).points == {}
    assert polygon.records[0].site.repr_point is None
