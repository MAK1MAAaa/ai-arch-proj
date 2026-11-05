"""Synthetic register contracts test offline gates; no fixture approves real source facts."""

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

from archsearch import minas_data as cohort
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
        "title": "Synthetic source",
        "uri": "https://example.org/base",
        "publisher": "Synthetic fixture",
    }
    return [
        Site.model_validate(
            {
                "id": f"auth:fixture:{index}",
                "title": f"Original place {index}",
                "description": "Original description",
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

    def model(self) -> cohort.MinasSpec:
        return cohort.MinasSpec.model_validate({"roster": self.roster, "review": self.review})

    def save(self) -> None:
        for filename, value, pin in [
            (cohort.ROSTER_FILE, self.roster, "SOURCE_ROSTER_SHA256"),
            (cohort.SPEC_FILE, self.review, "SPEC_SHA256"),
        ]:
            raw = encoded(value)
            (self.directory / filename).write_bytes(raw)
            self.monkeypatch.setattr(cohort, pin, digest(raw))
        facts = {
            "roster": self.roster,
            "review": {
                key: value
                for key, value in self.review.items()
                if key not in {"candidates_sha256", "handoff_sha256", "independent_report_sha256"}
            },
        }
        self.monkeypatch.setattr(cohort, "SOURCE_FACTS_SHA256", digest(encoded(facts)))

    def compile(self) -> dict[str, Any]:
        self.save()
        additions = cohort.compile_minas(self.model())
        self.monkeypatch.setattr(
            cohort,
            "SITES_SHA256",
            digest(encoded([site.model_dump(mode="json") for site in additions])),
        )
        return cohort.rebuild_minas(self.directory)

    def replace_csv(self, raw: bytes) -> None:
        artifact = self.roster["source_artifact"]
        (self.cache / artifact["filename"]).write_bytes(raw)
        artifact["sha256"] = digest(raw)
        self.monkeypatch.setattr(cohort, "RAW_SOURCE_SHA256", digest(raw))
        self.save()


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base: list[Site]) -> Bundle:
    cache = tmp_path / "cache"
    cache.mkdir()

    def evidence(key: str, uri: str) -> dict[str, Any]:
        raw = ("Synthetic evidence, not real source approval: " + key).encode()
        filename = key + ".txt"
        (cache / filename).write_bytes(raw)
        return {
            "source": {
                "id": "fixture:" + key,
                "title": "Synthetic source",
                "uri": uri,
                "publisher": "Synthetic fixture",
                "license": "CC BY 4.0",
                "excerpt": "Synthetic original cultural qualification.",
            },
            "artifact": {"filename": filename, "uri": uri, "sha256": digest(raw)},
        }

    metadata = evidence("metadata", cohort.METADATA_URI)
    package = evidence("package", cohort.DATAPACKAGE_URI)
    country = evidence("country", cohort.COUNTRY_CONTEXT_URI)
    rows = []
    for index, (process, short_name, scope, category, classification) in enumerate(
        [
            ("PTE001/1979", "Capela A", "Capela A e Praça B", "BI", "Edificação; templo"),
            ("PTE001/1979", "Praça B", "Capela A e Praça B", "BI", "Edificação; templo"),
            ("PTE058/1984", "Igreja", "Igreja C e Praça", "BI", "Edificação; templo"),
            ("PTE058/1984", "Casarão", "Conjunto D com Casarão", "BI", "Edificação; templo"),
            ("PTE005/1984", "Acervo", "Acervo E", "BM", "Bem móvel ou integrado"),
            ("PTE006/1984", "Serra", "Serra F", "CP", "Patrimônio Natural"),
            ("PTE007/1984", "Conjunto", "Conjunto G", "CH", "Conjunto urbano"),
            ("PTE008/1984", "Unknown", "Ambiguous H", "BI", "Edificação"),
        ],
        start=1,
    ):
        fields = {
            "processo_ano": process,
            "denominacao": short_name,
            "denominacao_completa": scope,
            "categoria": category,
            "classe_subclasse": classification,
            "municipio": "Town A, Town B",
            "distrito": "0",
            "ato_legal": "Portaria fixture, 2022",
            "livro_de_tombo": "0",
        }
        rows.append(
            {
                "record_index": index,
                "raw_fields": fields,
                "raw_fields_compact_sha256": cohort.compact_hash(fields),
            }
        )
    csv_stream = io.StringIO(newline="")
    writer = csv.DictWriter(csv_stream, fieldnames=cohort.SOURCE_FIELDS, delimiter=";")
    writer.writeheader()
    writer.writerows(row["raw_fields"] for row in rows)
    raw_csv = csv_stream.getvalue().encode("utf-8-sig")
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
        "records": rows,
    }
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        fields = row["raw_fields"]
        groups.setdefault(
            cohort.scope_key(fields["processo_ano"], fields["denominacao_completa"]), []
        ).append(row)
    decisions = []
    identity = {
        "status": "approved",
        "reviewer": "Synthetic test fixture",
        "method": "Not a real source approval",
        "reviewed_at": "2026-11-05",
    }
    for key, members in groups.items():
        index = members[0]["record_index"]
        disposition = {5: "exclude", 6: "hold", 7: "component", 8: "hold"}.get(index, "include")
        qualification = {
            5: "movable",
            6: "natural_only",
            7: "existing_overlap",
            8: "uncertain",
        }.get(index, "immovable_cultural")
        decisions.append(
            {
                "scope_key": key,
                "source_record_indices": [member["record_index"] for member in members],
                "disposition": disposition,
                "qualification": qualification,
                "scope_kind": "single_record_scope"
                if len(members) == 1
                else "composite_source_scope",
                "supported_scope_literal": members[0]["raw_fields"]["denominacao_completa"],
                "target_id": cohort.project_id(key)
                if disposition == "include"
                else base[0].id
                if disposition == "component"
                else None,
                "reason": "AUDITONLYSENTINEL synthetic scope decision",
                "independent_review": identity,
                "evidence": [package],
            }
        )
    review = {
        "schema_version": 1,
        "cohort_version": cohort.COHORT_VERSION,
        "corpus_version": cohort.CORPUS_VERSION,
        **base_contract(base),
        "candidates_sha256": digest(b"synthetic candidates"),
        "handoff_sha256": digest(b"synthetic handoff"),
        "independent_report_sha256": digest(b"synthetic review"),
        "metadata": {
            "evidence": metadata,
            "data_package": package,
            "csv_last_modified": "2025-11-04T11:31:28.932619",
            "metadata_created": "2023-08-30T11:12:41.879954",
            "metadata_modified": "2025-11-04T11:31:31.937661",
            "datapackage_version": 0.1,
            "update_frequency_literal": "por evento",
            "missing_values": ["0"],
        },
        "licence": {
            "name": "CC BY 4.0",
            "uri": cohort.LICENCE_URI,
            "attribution": "Synthetic "
            + cohort.DATASET_URI
            + " "
            + cohort.LICENCE_URI
            + " 2026-11-05",
            "accessed": "2026-11-05",
            "evidence": package,
        },
        "country": {"code": "BR", "region": "latin-america-caribbean", "evidence": country},
        "decisions": decisions,
    }
    monkeypatch.setattr(cohort, "SOURCE_COUNT", len(rows))
    for key, value in {
        "RAW_SOURCE_SHA256": digest(raw_csv),
        "METADATA_SHA256": metadata["artifact"]["sha256"],
        "DATAPACKAGE_SHA256": package["artifact"]["sha256"],
        "CANDIDATES_SHA256": review["candidates_sha256"],
        "HANDOFF_SHA256": review["handoff_sha256"],
        "INDEPENDENT_REVIEW_SHA256": review["independent_report_sha256"],
        "SITES_SHA256": "f" * 64,
    }.items():
        monkeypatch.setattr(cohort, key, value)
    normalized = cohort.MinasSpec.model_validate({"roster": roster, "review": review})
    result = Bundle(
        tmp_path,
        cache,
        normalized.roster.model_dump(mode="json"),
        normalized.review.model_dump(mode="json"),
        monkeypatch,
    )
    result.compile()
    return result


def test_scope_identity_preserves_exact_full_scope_and_unicode() -> None:
    assert cohort.scope_key("PTE058/1984", "Igreja C") != cohort.scope_key(
        "PTE058/1984", "Igreja D"
    )
    assert cohort.scope_key("PTE1", "Capela A") != cohort.scope_key("PTE1", "Capela A ")
    assert cohort.scope_key("PTE1", "é") != cohort.scope_key("PTE1", "e\u0301")
    expected = digest(b'["process","whole"]')
    assert (
        cohort.project_id(cohort.scope_key("process", "whole"))
        == "auth:br-iepha-mg:scope-" + expected
    )
    with pytest.raises(ValueError):
        cohort.project_id("../source")


def test_projection_groups_whole_and_retains_missing_ambiguity(
    bundle: Bundle, base: list[Site]
) -> None:
    sites = cohort.load_minas(base, bundle.directory)
    additions = sites[len(base) :]
    assert len(additions) == 3 and sites[: len(base)] == base
    composite = next(site for site in additions if site.title == "Capela A e Praça B")
    assert composite.names == []
    assert '"denominacao": "Capela A"' in composite.details
    assert '"denominacao": "Praça B"' in composite.details
    church = next(site for site in additions if site.title == "Igreja C e Praça")
    assert church.names == [] and '"denominacao": "Igreja"' in church.details
    landscape = next(site for site in additions if site.title == "Conjunto D com Casarão")
    assert landscape.names == [] and '"denominacao": "Casarão"' in landscape.details
    assert '"distrito": "0"' in composite.details and '"livro_de_tombo": "0"' in composite.details
    assert "Town A, Town B" in composite.details
    for site in additions:
        assert site.names == [] and site.repr_point is None and site.location_precision is None
        assert site.chronology.status == "not_reviewed" and not site.chronology.phases
        assert site.geography and site.geography.point_count == 0
        assert site.geography.countries == ["BR"]
        assert site.description == site.description_zh == ""
        document = build_document(site)
        assert "AUDITONLYSENTINEL" not in document
        assert "Acervo E" not in document and "Ambiguous H" not in document
    assert {site.title for site in additions} == {
        "Capela A e Praça B",
        "Igreja C e Praça",
        "Conjunto D com Casarão",
    }


def test_rebuild_is_deterministic_and_does_not_need_source_cache(
    bundle: Bundle, base: list[Site]
) -> None:
    before = {
        name: (bundle.directory / name).read_bytes()
        for name in [cohort.SITES_FILE, cohort.MANIFEST_FILE]
    }
    for path in bundle.cache.iterdir():
        path.unlink()
    cohort.rebuild_minas(bundle.directory, base=base)
    assert before == {name: (bundle.directory / name).read_bytes() for name in before}
    assert cohort.load_minas(base, bundle.directory)[len(base) :]


@pytest.mark.parametrize(
    "pin",
    [
        "RAW_SOURCE_SHA256",
        "METADATA_SHA256",
        "DATAPACKAGE_SHA256",
        "CANDIDATES_SHA256",
        "HANDOFF_SHA256",
        "INDEPENDENT_REVIEW_SHA256",
        "SOURCE_FACTS_SHA256",
        "SOURCE_ROSTER_SHA256",
        "SPEC_SHA256",
        "SITES_SHA256",
    ],
)
def test_each_external_gate_must_be_activated(bundle: Bundle, pin: str, base: list[Site]) -> None:
    bundle.monkeypatch.setattr(cohort, pin, "CLOSED")
    with pytest.raises(cohort.MinasError, match="not configured"):
        cohort.load_minas(base, bundle.directory)


@pytest.mark.parametrize(
    "filename", [cohort.ROSTER_FILE, cohort.SPEC_FILE, cohort.SITES_FILE, cohort.MANIFEST_FILE]
)
def test_tampered_production_file_is_rejected(
    bundle: Bundle, filename: str, base: list[Site]
) -> None:
    path = bundle.directory / filename
    payload = json.loads(path.read_bytes())
    if isinstance(payload, list):
        payload[0]["repr_point"] = [0, 0]
    else:
        payload["unexpected"] = "unreviewed"
    path.write_bytes(encoded(payload))
    with pytest.raises(cohort.MinasError):
        cohort.load_minas(base, bundle.directory)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_row",
        "index_duplicate",
        "fields_missing",
        "row_hash",
        "row_numeric0",
        "scope_renamed",
        "scope_member_missing",
        "scope_member_duplicate",
        "scope_decision_missing",
        "scope_decision_duplicate",
        "scope_short_name",
        "wrong_composite_kind",
        "fake_point",
        "unapproved",
        "wrong_target",
        "bad_country",
        "missing_licence",
    ],
)
def test_revalidated_structural_failures(bundle: Bundle, mutation: str, base: list[Site]) -> None:
    if mutation == "missing_row":
        bundle.roster["records"].pop()
    elif mutation == "index_duplicate":
        bundle.roster["records"][1]["record_index"] = 1
    elif mutation == "fields_missing":
        bundle.roster["fields"].pop()
    elif mutation == "row_hash":
        bundle.roster["records"][0]["raw_fields"]["municipio"] = "Changed city"
    elif mutation == "row_numeric0":
        bundle.roster["records"][0]["raw_fields"]["distrito"] = 0
    elif mutation == "scope_renamed":
        bundle.review["decisions"][0]["scope_key"] = "f" * 64
    elif mutation == "scope_member_missing":
        bundle.review["decisions"][0]["source_record_indices"] = [1]
    elif mutation == "scope_member_duplicate":
        bundle.review["decisions"][0]["source_record_indices"] = [1, 1, 2]
    elif mutation == "scope_decision_missing":
        bundle.review["decisions"].pop()
    elif mutation == "scope_decision_duplicate":
        bundle.review["decisions"].append(copy.deepcopy(bundle.review["decisions"][0]))
    elif mutation == "scope_short_name":
        bundle.review["decisions"][0]["supported_scope_literal"] = "Capela A"
    elif mutation == "wrong_composite_kind":
        bundle.review["decisions"][0]["scope_kind"] = "single_record_scope"
    elif mutation == "fake_point":
        bundle.review["decisions"][0]["point"] = [0, 0]
    elif mutation == "unapproved":
        bundle.review["decisions"][0]["independent_review"]["status"] = "pending"
    elif mutation == "wrong_target":
        bundle.review["decisions"][0]["target_id"] = base[0].id
    elif mutation == "bad_country":
        bundle.review["country"]["code"] = "SG"
    else:
        bundle.review["licence"]["uri"] = "https://example.org/licence"
    bundle.save()
    with pytest.raises(cohort.MinasError):
        cohort.load_minas(base, bundle.directory)


@pytest.mark.parametrize("row_index", [5, 6])
def test_source_movable_and_natural_guards_cannot_be_overridden(
    bundle: Bundle, row_index: int
) -> None:
    decision = next(
        row for row in bundle.review["decisions"] if row["source_record_indices"] == [row_index]
    )
    decision.update(
        disposition="include",
        qualification="immovable_cultural",
        target_id=cohort.project_id(decision["scope_key"]),
    )
    with pytest.raises(cohort.MinasError, match="movable or solely natural"):
        cohort.compile_minas(bundle.model())


def test_explicit_uncertain_qualification_cannot_be_included(bundle: Bundle) -> None:
    decision = bundle.review["decisions"][0]
    decision["qualification"] = "uncertain"
    with pytest.raises(ValidationError, match="independent cultural qualification"):
        bundle.model()


def test_invalid_base_order_and_fields_are_rejected(bundle: Bundle, base: list[Site]) -> None:
    changed = list(base)
    changed[0], changed[1] = changed[1], changed[0]
    with pytest.raises(cohort.MinasError, match="unchanged3193"):
        cohort.load_minas(changed, bundle.directory)
    changed = [base[0].model_copy(update={"description": "Changed"}), *base[1:]]
    with pytest.raises(cohort.MinasError, match="unchanged3193"):
        cohort.rebuild_minas(bundle.directory, base=changed)


def test_existing_component_target_requires_unchanged_base(
    bundle: Bundle, base: list[Site]
) -> None:
    component = next(row for row in bundle.review["decisions"] if row["disposition"] == "component")
    component["target_id"] = "auth:fixture:missing"
    bundle.save()
    with pytest.raises(cohort.MinasError, match="target is absent"):
        cohort.load_minas(base, bundle.directory)


def test_complete_facts_pin_cannot_be_replaced_by_review_checksum(
    bundle: Bundle, base: list[Site]
) -> None:
    bundle.monkeypatch.setattr(cohort, "SOURCE_FACTS_SHA256", "0" * 64)
    with pytest.raises(cohort.MinasError, match="complete independent source facts differ"):
        cohort.load_minas(base, bundle.directory)


def test_optional_source_cache_reads_all_rows_and_raw0(bundle: Bundle) -> None:
    assert cohort.verify_source_cache(bundle.cache, bundle.directory) == 4
    (bundle.cache / "source.csv").write_bytes(b"corrupt")
    with pytest.raises(cohort.MinasError, match="source snapshot differs"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)


def test_optional_cache_rejects_reordered_csv_headers_even_with_rebound_raw_hash(
    bundle: Bundle,
) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(reversed(cohort.SOURCE_FIELDS)), delimiter=";")
    writer.writeheader()
    writer.writerows(row["raw_fields"] for row in bundle.roster["records"])
    bundle.replace_csv(stream.getvalue().encode("utf-8-sig"))
    with pytest.raises(cohort.MinasError, match="header/order differs"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)


def test_optional_cache_rejects_row_change_after_raw_pin_update(bundle: Bundle) -> None:
    original = (bundle.cache / "source.csv").read_bytes()
    bundle.replace_csv(original.replace(b"Town A", b"Town C", 1))
    with pytest.raises(cohort.MinasError, match="fields/order differ"):
        cohort.verify_source_cache(bundle.cache, bundle.directory)


def test_rebuild_failure_preserves_prior_derivatives(bundle: Bundle) -> None:
    original = (bundle.directory / cohort.SITES_FILE).read_bytes()
    bundle.monkeypatch.setattr(cohort, "SITES_SHA256", "0" * 64)
    with pytest.raises(cohort.MinasError, match="compiled Minas sites differ"):
        cohort.rebuild_minas(bundle.directory)
    assert (bundle.directory / cohort.SITES_FILE).read_bytes() == original


def test_artifact_filename_conflicts_are_rejected(bundle: Bundle) -> None:
    bundle.review["metadata"]["evidence"]["artifact"]["filename"] = "source.csv"
    with pytest.raises(cohort.MinasError, match="conflicting original artifact"):
        cohort.compile_minas(bundle.model())


def test_bounded_file_reads_reject_size_and_path_escape(bundle: Bundle) -> None:
    with pytest.raises(cohort.MinasError, match="escapes"):
        cohort._read_bounded(bundle.directory, "../outside")
    bundle.monkeypatch.setattr(cohort, "MAX_FILE_BYTES", 4)
    with pytest.raises(cohort.MinasError, match="bounded contract"):
        cohort._read_bounded(bundle.directory, cohort.ROSTER_FILE)
