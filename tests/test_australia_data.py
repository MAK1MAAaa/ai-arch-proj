"""Synthetic offline NHL contracts; fixtures assert no real cultural-source facts."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from archsearch import australia_data as cohort
from archsearch.corpus import build_document
from archsearch.domain import Site
from archsearch.supplement_data import base_contract


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def reference(identifier: str, uri: str | None = None) -> dict[str, Any]:
    return {
        "id": "qualification:" + identifier,
        "title": "Synthetic cultural qualification",
        "uri": uri or "https://example.org/fixture/" + identifier,
        "publisher": "Synthetic authority",
        "license": None,
        "excerpt": "Synthetic immovable cultural place only.",
    }


def synthetic_site(identifier: str) -> dict[str, Any]:
    source = reference(identifier)
    return {
        "id": identifier,
        "title": "Synthetic base place " + identifier,
        "description": "Synthetic fixture, not an actual source assertion.",
        "description_zh": "",
        "details": "Original content must remain.",
        "names": ["Original alias"],
        "types": ["historic-site"],
        "periods": [],
        "period_evidence": [],
        "repr_point": [140.0, -30.0],
        "location_precision": None,
        "source_kind": "supplement",
        "source_uri": source["uri"],
        "source_refs": [source],
        "contributors": ["Synthetic authority"],
        "chronology": {"status": "not_reviewed", "phases": [], "default_phase_id": None},
        "geography": {
            "authority_id": "supplement:" + identifier,
            "countries": ["AU"],
            "regions": ["asia-pacific"],
            "point_count": 1,
            "source": source,
            "note": "Original source note, including previously approved associations.",
        },
    }


def feature(pid: int, oid: int, state: str) -> dict[str, Any]:
    return {
        "OBJECTID": oid,
        "PLACE_ID": pid,
        "FILE_": f"1/02/003/{pid:04d}",
        "NAME": f"Synthetic registered place {pid}",
        "CLASS": "Historic",
        "STATUS": "Listed place",
        "STATE": state,
        "SOURCE": "Synthetic source",
        "AREA_HA": 1,
        "UPDATED": 123456,
        "REGISTER_DATE": 987654,
        "URL": f"https://www.dcceew.gov.au/parks-heritage/heritage/places/national/fixture-{pid}",
        "ADDRESS": "Synthetic address, not an actual place",
        "Shape__Area": 0.1,
        "Shape__Length": 1,
    }


def geometry_uri(pid: int) -> str:
    return (
        "https://gis.environment.gov.au/gispubmap/rest/services/ogc_services/"
        f"National_Heritage_List/FeatureServer/0/query?where=PLACE_ID%3D{pid}&outSR=4326&returnGeometry=true"
    )


@pytest.fixture(scope="module")
def base1940() -> list[Site]:
    sites = [Site.model_validate(synthetic_site(f"auth:fixture:{index}")) for index in range(1940)]
    first = sites[0]
    assert first.geography
    sites[0] = first.model_copy(
        update={
            "geography": first.geography.model_copy(
                update={
                    "countries": ["AU", "AS"],
                    "regions": ["asia-pacific", "nps-pacific"],
                }
            ),
            "source_refs": [
                *first.source_refs,
                first.source_refs[0].model_copy(
                    update={
                        "id": "association:nps:fixture",
                        "excerpt": "",
                    }
                ),
            ],
        }
    )
    return sites


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
        roster = [
            {"place_id": row["place_id"], "source_features": row["source_features"]}
            for row in sorted(self.spec["decisions"], key=lambda row: row["place_id"])
        ]
        self.monkeypatch.setattr(cohort, "SOURCE_ROSTER_SHA256", digest(encoded(roster)))

    def compile(self) -> dict[str, Any]:
        self.pin_spec()
        rows = sorted(
            self.spec["records"],
            key=lambda row: (
                digest((cohort.COHORT_VERSION + ":" + row["site"]["id"]).encode()),
                row["site"]["id"],
            ),
        )
        sites = [Site.model_validate(row["site"]).model_dump(mode="json") for row in rows]
        self.monkeypatch.setattr(cohort, "SITES_SHA256", digest(encoded(sites)))
        return cohort.rebuild_australia(self.directory)


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base1940: list[Site]) -> Bundle:
    cache = tmp_path / "source-cache"
    cache.mkdir()
    un_payload = b"Synthetic UN M49 fixture: AU Australia; NF Norfolk Island."
    (cache / "un-m49.txt").write_bytes(un_payload)
    monkeypatch.setattr(cohort, "UN_M49_SHA256", digest(un_payload))
    un_artifact = {"filename": "un-m49.txt", "uri": cohort.UN_M49_URI, "sha256": digest(un_payload)}
    labels = []
    for code in ["AU", "NF"]:
        evidence = reference("un-m49-" + code, cohort.UN_M49_URI)
        evidence["excerpt"] = cohort.COUNTRY_LABELS[code] + " " + code
        labels.append(
            {
                "code": code,
                "label": cohort.COUNTRY_LABELS[code],
                "source_code_literal": code,
                "source_label_literal": cohort.COUNTRY_LABELS[code],
                "source": evidence,
                "artifact": un_artifact,
            }
        )
    decisions = []
    records = []
    for pid, oid, states, disposition in [
        (101, 1, ["SA", "QLD"], "include"),
        (106167, 3, ["EXT"], "include"),
        (103, 4, ["NSW"], "existing"),
        (104, 5, ["NSW"], "component"),
        (105, 6, ["TAS"], "hold"),
    ]:
        features = [feature(pid, oid + offset, state) for offset, state in enumerate(states)]
        evidence = reference(f"nhl-{pid}", features[0]["URL"])
        metadata_bytes = encoded({"synthetic_fixture": True, "features": features})
        filename = f"metadata-{pid}.json"
        (cache / filename).write_bytes(metadata_bytes)
        artifact = {"filename": filename, "uri": evidence["uri"], "sha256": digest(metadata_bytes)}
        target = (
            f"auth:au-nhl:{pid}"
            if disposition == "include"
            else (
                None
                if disposition == "hold"
                else base1940[0 if disposition == "existing" else 1].id
            )
        )
        refs = [evidence]
        if pid == 106167:
            evidence["excerpt"] = "Synthetic Norfolk Island place-level fixture."
            refs.append(labels[1]["source"])
        decisions.append(
            {
                "place_id": pid,
                "source_features": features,
                "disposition": disposition,
                "target_id": target,
                "country_code": None if disposition == "hold" else "AU",
                "additional_country_codes": ["NF"] if pid == 106167 else [],
                "reason": "Synthetic independent identity/scope decision, not a real approval.",
                "evidence": refs,
                "source_files": [artifact],
            }
        )
        if disposition != "include":
            continue
        point_source = reference(f"range-{pid}", geometry_uri(pid))
        point_source.update(license="CC BY 3.0 Australia", excerpt="")
        range_bytes = encoded(
            {"synthetic_fixture": True, "geometry_type": "polygon", "not_converted_to_point": True}
        )
        range_filename = f"range-{pid}.json"
        (cache / range_filename).write_bytes(range_bytes)
        range_artifact = {
            "filename": range_filename,
            "uri": geometry_uri(pid),
            "sha256": digest(range_bytes),
        }
        registered_range = {
            "artifact": range_artifact,
            "role": "modern_public_registered_heritage_range",
            "geometry_type": "esriGeometryPolygon",
            "source_crs": 4283,
            "spatial_reference": 4326,
            "feature_ids": [r["OBJECTID"] for r in features],
            "source_rows": features,
            "feature_count": len(features),
            "ring_count": len(features),
            "coordinate_records": 4 * len(features),
            "per_record_generalisation_status": "not_identified_by_provider",
        }
        site = synthetic_site(str(target))
        site.update(
            title=features[0]["NAME"],
            description="",
            description_zh="",
            names=[],
            details="Source country association: Australia (AU).",
            repr_point=None,
            source_uri=evidence["uri"],
            source_refs=[*refs, point_source],
        )
        site["geography"].update(
            point_count=0, source=evidence, countries=["AU", "NF"] if pid == 106167 else ["AU"]
        )
        records.append(
            {
                "site": site,
                "country_label": "Australia",
                "source_features": features,
                "registered_range": registered_range,
                "coordinate": {
                    "method": "unknown",
                    "point": None,
                    "source_uri": None,
                    "note": "Only a public modern range; no source-defined point. "
                    "Not a claim that the real location is unknown.",
                },
                "independent_review": {
                    "status": "approved",
                    "reviewer": "Synthetic reviewer",
                    "method": "Synthetic fixture only, not expert approval.",
                    "reviewed_at": "2026-11-04",
                },
                "source_files": [artifact, range_artifact],
                "provenance": {
                    "synthetic_fixture": True,
                    "administrative_dates_not_phases": True,
                    "source_row_attributes": features,
                },
            }
        )
    monkeypatch.setattr(cohort, "CANDIDATES_SHA256", "1" * 64)
    monkeypatch.setattr(cohort, "HANDOFF_SHA256", "2" * 64)
    monkeypatch.setattr(cohort, "INDEPENDENT_REVIEW_SHA256", "3" * 64)
    spec = {
        "schema_version": 1,
        "cohort_version": cohort.COHORT_VERSION,
        "corpus_version": cohort.CORPUS_VERSION,
        **base_contract(base1940),
        "candidates_sha256": "1" * 64,
        "handoff_sha256": "2" * 64,
        "independent_report_sha256": "3" * 64,
        "selection": cohort.SELECTION,
        "countries": labels,
        "decisions": decisions,
        "records": records,
    }
    result = Bundle(tmp_path, cache, spec, monkeypatch)
    result.pin_roster()
    result.compile()
    return result


def test_closed_pending_pins_fail_before_any_file_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cohort, "INDEPENDENT_REVIEW_SHA256", "")
    with pytest.raises(cohort.AustraliaError, match="not configured"):
        cohort.rebuild_australia(tmp_path)
    assert not list(tmp_path.iterdir())


def test_complete_decisions_append_only_and_preserve_all_original_fields(
    bundle: Bundle,
    base1940: list[Site],
) -> None:
    before = [site.model_dump(mode="json") for site in base1940]
    documents = [build_document(site) for site in base1940]
    loaded = cohort.load_australia(base1940, bundle.directory)
    assert len(loaded) == len({site.id for site in loaded}) == 1942
    assert all(old is new for old, new in zip(base1940, loaded[:1940], strict=True))
    assert [site.model_dump(mode="json") for site in loaded[:1940]] == before
    assert [build_document(site) for site in loaded[:1940]] == documents
    assert [site.model_dump(mode="json") for site in base1940] == before
    assert all(site.repr_point is None and site.chronology.phases == [] for site in loaded[1940:])
    manifest = json.loads((bundle.directory / cohort.MANIFEST_FILE).read_bytes())
    assert manifest["counts"] == {
        "base": 1940,
        "added": 2,
        "total": 1942,
        "source_business_ids": 5,
        "source_features": 6,
        "decisions": {"include": 2, "existing": 1, "component": 1, "hold": 1},
        "registered_ranges": 2,
        "registered_range_features": 3,
        "adopted_representative_points": 0,
    }
    assert len(manifest["catalogue_associations"]) == 2
    assert "not precise geometry" in manifest["range_semantics"]


def test_repeat_compilation_and_input_record_order_are_deterministic(bundle: Bundle) -> None:
    paths = [bundle.directory / name for name in [cohort.SITES_FILE, cohort.MANIFEST_FILE]]
    before = [path.read_bytes() for path in paths]
    for _ in range(2):
        cohort.rebuild_australia(bundle.directory)
        assert [path.read_bytes() for path in paths] == before
    bundle.spec["records"].reverse()
    bundle.spec["decisions"].reverse()
    bundle.compile()
    assert paths[0].read_bytes() == before[0]


def test_original_gis_keys_values_and_repeated_state_rows_are_preserved(bundle: Bundle) -> None:
    spec = cohort._spec(bundle.directory)
    record = next(row for row in spec.records if row.source_features[0].place_id == 101)
    original = next(
        row for row in bundle.spec["records"] if row["source_features"][0]["PLACE_ID"] == 101
    )
    assert [
        row.model_dump(mode="json", by_alias=True) for row in record.source_features
    ] == original["source_features"]
    assert isinstance(record.source_features[0].area_ha, int)
    assert isinstance(record.source_features[0].shape_area, float)
    assert record.registered_range.feature_ids == [1, 2]
    assert [row.state for row in record.registered_range.source_rows] == ["SA", "QLD"]
    assert record.registered_range.source_crs == 4283
    assert record.registered_range.spatial_reference == 4326


def test_only_reviewed_nf_label_added_while_original_au_is_retained(bundle: Bundle) -> None:
    labels = cohort.new_country_labels(bundle.directory)
    assert labels == {"NF": "Norfolk Island"} and "AU" not in labels
    with pytest.raises(TypeError):
        labels["AU"] = "Overwrite"  # type: ignore[index]
    site = next(
        row.site
        for row in cohort._spec(bundle.directory).records
        if row.source_features[0].place_id == 106167
    )
    assert site.geography and site.geography.countries == ["AU", "NF"]
    assert site.details == "Source country association: Australia (AU)."


@pytest.mark.parametrize("kind", ["candidate", "handoff", "report"])
def test_external_review_bindings_cannot_be_self_resigned(bundle: Bundle, kind: str) -> None:
    field = {
        "candidate": "candidates_sha256",
        "handoff": "handoff_sha256",
        "report": "independent_report_sha256",
    }[kind]
    bundle.spec[field] = "4" * 64
    bundle.pin_spec()
    with pytest.raises(cohort.AustraliaError, match="binding"):
        cohort.rebuild_australia(bundle.directory)


@pytest.mark.parametrize(
    "field,value",
    [
        ("OBJECTID", 11),
        ("PLACE_ID", 999),
        ("FILE_", "9/99/999/9999"),
        ("STATE", "WA"),
        ("ADDRESS", "Altered source address"),
    ],
)
def test_original_feature_roster_pin_survives_spec_resigning(
    bundle: Bundle,
    field: str,
    value: Any,
) -> None:
    bundle.spec["decisions"][-1]["source_features"][0][field] = value
    bundle.pin_spec()
    with pytest.raises(cohort.AustraliaError):
        cohort.rebuild_australia(bundle.directory)


@pytest.mark.parametrize(
    "mutation", ["duplicate_business", "duplicate_feature", "drop_hold", "drop_state"]
)
def test_complete_source_roster_cannot_drop_or_duplicate_rows(
    bundle: Bundle, mutation: str
) -> None:
    if mutation == "duplicate_business":
        bundle.spec["decisions"].append(copy.deepcopy(bundle.spec["decisions"][-1]))
    elif mutation == "duplicate_feature":
        bundle.spec["decisions"][-1]["source_features"][0]["OBJECTID"] = 1
    elif mutation == "drop_hold":
        bundle.spec["decisions"].pop()
    else:
        bundle.spec["decisions"][0]["source_features"].pop()
    bundle.pin_spec()
    with pytest.raises(cohort.AustraliaError):
        cohort.rebuild_australia(bundle.directory)


@pytest.mark.parametrize(
    "mutation",
    [
        "inferred_point",
        "phase",
        "prose",
        "translated_title",
        "partial_range",
        "drop_range",
        "wrong_crs",
        "wrong_source_crs",
        "false_ancient_role",
        "bad_geometry_uri",
        "unbound_range",
    ],
)
def test_range_only_source_and_unknown_chronology_cannot_be_upgraded(
    bundle: Bundle,
    mutation: str,
) -> None:
    row = bundle.spec["records"][0]
    if mutation == "inferred_point":
        row["site"]["repr_point"] = [140, -30]
        row["site"]["geography"]["point_count"] = 1
        row["coordinate"].update(
            method="authority",
            point=[140, -30],
            source_uri=row["registered_range"]["artifact"]["uri"],
        )
    elif mutation == "phase":
        row["site"]["periods"] = ["synthetic-listing-year"]
    elif mutation == "prose":
        row["site"]["description"] = "Unsupported historical summary."
    elif mutation == "translated_title":
        row["site"]["title"] = "项目生成中文名称"
    elif mutation == "partial_range":
        row["registered_range"]["source_rows"].pop()
        row["registered_range"].update(feature_ids=[1], feature_count=1)
    elif mutation == "drop_range":
        row["registered_range"] = None
    elif mutation == "wrong_crs":
        row["registered_range"]["spatial_reference"] = 3857
    elif mutation == "wrong_source_crs":
        row["registered_range"]["source_crs"] = 4326
    elif mutation == "false_ancient_role":
        row["registered_range"]["role"] = "ancient_excavation_boundary"
    elif mutation == "bad_geometry_uri":
        row["registered_range"]["artifact"]["uri"] = "https://example.org/centroid"
    else:
        row["source_files"] = row["source_files"][:1]
    bundle.pin_spec()
    with pytest.raises(cohort.AustraliaError):
        cohort.rebuild_australia(bundle.directory)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_record",
        "unmatched_record",
        "swap_target",
        "hold_target",
        "hold_country",
        "no_nf_place_evidence",
        "no_nf_un_evidence",
        "infer_nf_from_ext",
        "replace_au",
    ],
)
def test_approved_targets_and_country_association_need_exact_reviewed_scope(
    bundle: Bundle,
    mutation: str,
) -> None:
    if mutation == "missing_record":
        bundle.spec["records"].pop()
    elif mutation == "unmatched_record":
        bundle.spec["records"].append(copy.deepcopy(bundle.spec["records"][0]))
    elif mutation == "swap_target":
        a, b = bundle.spec["decisions"][:2]
        a["target_id"], b["target_id"] = b["target_id"], a["target_id"]
    elif mutation == "hold_target":
        bundle.spec["decisions"][-1]["target_id"] = "auth:fixture:2"
    elif mutation == "hold_country":
        bundle.spec["decisions"][-1]["country_code"] = "AU"
    elif mutation == "no_nf_place_evidence":
        bundle.spec["decisions"][1]["evidence"] = bundle.spec["decisions"][1]["evidence"][1:]
    elif mutation == "no_nf_un_evidence":
        bundle.spec["decisions"][1]["evidence"].pop()
    elif mutation == "infer_nf_from_ext":
        bundle.spec["decisions"][0]["additional_country_codes"] = ["NF"]
    else:
        bundle.spec["records"][1]["site"]["geography"]["countries"] = ["NF"]
    bundle.pin_spec()
    with pytest.raises(cohort.AustraliaError):
        cohort.rebuild_australia(bundle.directory)


@pytest.mark.parametrize("mutation", ["label", "code", "non_un_source", "wrong_un_snapshot"])
def test_country_labels_need_literal_frozen_un_source(bundle: Bundle, mutation: str) -> None:
    row = bundle.spec["countries"][1]
    if mutation == "label":
        row["label"] = "Australia"
    elif mutation == "code":
        row["source_code_literal"] = "AU"
    elif mutation == "non_un_source":
        row["source"]["uri"] = "https://example.org/guessed-code"
    else:
        row["artifact"]["sha256"] = "9" * 64
    bundle.pin_spec()
    with pytest.raises(cohort.AustraliaError):
        cohort.rebuild_australia(bundle.directory)


@pytest.mark.parametrize("mutation", ["country", "source", "document", "id", "order", "count"])
def test_complete_base_contract_rejects_any_old_object_change(
    bundle: Bundle,
    base1940: list[Site],
    mutation: str,
) -> None:
    base = list(base1940)
    if mutation == "country":
        assert base[0].geography
        base[0] = base[0].model_copy(
            update={
                "geography": base[0].geography.model_copy(update={"countries": ["US"]}),
            }
        )
    elif mutation == "source":
        base[0] = base[0].model_copy(update={"source_refs": []})
    elif mutation == "document":
        base[0] = base[0].model_copy(update={"description": "Changed old content"})
    elif mutation == "id":
        base[0] = base[0].model_copy(update={"id": "auth:changed:0"})
    elif mutation == "order":
        base.reverse()
    else:
        base.pop()
    with pytest.raises(cohort.AustraliaError, match="1940"):
        cohort.load_australia(base, bundle.directory)


def test_existing_and_component_targets_must_be_in_the_frozen_base(
    bundle: Bundle,
    base1940: list[Site],
) -> None:
    bundle.spec["decisions"][2]["target_id"] = "auth:fixture:absent"
    bundle.compile()
    with pytest.raises(cohort.AustraliaError, match="target is absent"):
        cohort.load_australia(base1940, bundle.directory)


@pytest.mark.parametrize("filename", ["sites", "manifest", "review"])
def test_mutated_compiled_artifacts_are_not_trusted(
    bundle: Bundle,
    base1940: list[Site],
    filename: str,
) -> None:
    name = {
        "sites": cohort.SITES_FILE,
        "manifest": cohort.MANIFEST_FILE,
        "review": cohort.SPEC_FILE,
    }[filename]
    path = bundle.directory / name
    path.write_bytes(path.read_bytes().replace(b"Australia", b"Alteredland"))
    with pytest.raises(cohort.AustraliaError):
        cohort.load_australia(base1940, bundle.directory)


def test_optional_source_cache_validation_and_tamper_detection(bundle: Bundle) -> None:
    assert cohort.verify_source_cache(bundle.cache, bundle.directory) == 8
    path = bundle.cache / "range-101.json"
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(cohort.AustraliaError, match="snapshot differs"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)


def test_source_filename_conflicts_and_traversal_are_rejected(bundle: Bundle) -> None:
    bundle.spec["decisions"][0]["source_files"][0]["filename"] = "../escape.txt"
    bundle.pin_spec()
    with pytest.raises(cohort.AustraliaError):
        cohort.rebuild_australia(bundle.directory)
    bad = copy.deepcopy(bundle.spec["records"][0])
    bad["source_features"][0]["OBJECTID"] = True
    with pytest.raises(ValidationError):
        cohort.AustraliaRecord.model_validate(bad)


def test_conflicting_source_artifact_filename_is_rejected(bundle: Bundle) -> None:
    artifact = bundle.spec["decisions"][-1]["source_files"][0]
    artifact["filename"] = bundle.spec["decisions"][0]["source_files"][0]["filename"]
    bundle.pin_spec()
    with pytest.raises(cohort.AustraliaError, match="conflicting source contracts"):
        cohort.rebuild_australia(bundle.directory)


def test_range_cannot_replace_original_source_rows_even_with_same_ids(bundle: Bundle) -> None:
    row = json.loads(encoded(bundle.spec["records"][0]))
    row["registered_range"]["source_rows"][0]["ADDRESS"] = "Silently changed original row"
    with pytest.raises(ValidationError, match="source rows differ"):
        cohort.AustraliaRecord.model_validate(row)


def test_nf_mapping_sources_must_remain_public_in_detail_sources(bundle: Bundle) -> None:
    record = bundle.spec["records"][1]
    record["site"]["source_refs"] = [
        ref for ref in record["site"]["source_refs"] if ref["uri"] != cohort.UN_M49_URI
    ]
    bundle.pin_spec()
    with pytest.raises(cohort.AustraliaError, match="public site sources"):
        cohort.rebuild_australia(bundle.directory)


def test_base_duplicate_ids_cannot_be_hidden_by_resigning_base_contract(
    bundle: Bundle,
    base1940: list[Site],
) -> None:
    base = list(base1940)
    base[-1] = base[-2]
    bundle.spec.update(base_contract(base))
    bundle.compile()
    with pytest.raises(cohort.AustraliaError, match="base IDs duplicate"):
        cohort.load_australia(base, bundle.directory)


def test_nf_country_label_cannot_overwrite_an_existing_base_association(
    bundle: Bundle,
    base1940: list[Site],
) -> None:
    base = list(base1940)
    assert base[1].geography
    base[1] = base[1].model_copy(
        update={
            "geography": base[1].geography.model_copy(update={"countries": ["AU", "NF"]}),
        }
    )
    bundle.spec.update(base_contract(base))
    bundle.compile()
    with pytest.raises(cohort.AustraliaError, match="cannot overwrite"):
        cohort.load_australia(base, bundle.directory)
