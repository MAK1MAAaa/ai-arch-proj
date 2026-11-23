"""Check the frozen corpus fingerprint and its scoped encoding reuse."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Event, get_ident
from typing import Any

import pytest

from archsearch.domain import ChronologyReview, Geography, HistoricalPhase, Site, SourceReference
from archsearch.supplement_data import base_contract, reuse_base_contract_fragments


def _site(identifier: str, point: tuple[float, float] | None = None) -> Site:
    source = SourceReference(
        id="catalogue",
        title='Établissement "北" \U00010300',
        uri="https://example.test/cultural-sites",
        publisher="档案目录",
        excerpt='第一行\n  第二行\t"quote"\\path\r\n\u0001',
    )
    return Site(
        id=identifier,
        title="遗址 É",
        description="Sources document a settlement.",
        names=["e\u0301", "\n  北"],
        types=["historic-site"],
        periods=[],
        repr_point=point,
        source_uri=source.uri,
        contributors=[],
        period_evidence=[],
        source_kind="supplement",
        source_refs=[source],
        chronology=ChronologyReview(
            status="reviewed",
            method="source review",
            reviewed_at="2026-01-01",
            default_phase_id="occupation",
            phases=[HistoricalPhase(
                id="occupation",
                kind="use",
                label="Occupação",
                start_year=-117,
                precision="period",
                sources=[source],
            )],
        ),
        geography=Geography(
            authority_id="supplement:" + identifier,
            countries=["FR"],
            regions=["europe-north-america"],
            point_count=int(point is not None),
            source=source,
        ),
    )


def _reference_contract(sites: list[Site]) -> dict[str, str | int]:
    def digest(records: object) -> str:
        encoded = json.dumps(records, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    return {
        "base_count": len(sites),
        "base_ids_sha256": digest([site.id for site in sites]),
        "base_sites_sha256": digest([site.model_dump(mode="json") for site in sites]),
    }


def _record_site_encodings(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    dump = json.dumps
    batches: list[tuple[int, int]] = []

    def observe(records: object, **options: Any) -> str:
        if isinstance(records, list) and records and isinstance(records[0], dict):
            if "chronology" in records[0]:
                batches.append((get_ident(), len(records)))
        return dump(records, **options)

    monkeypatch.setattr(json, "dumps", observe)
    return batches


def test_fingerprint_preserves_empty_nested_and_ordered_records() -> None:
    empty_digest = "37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"
    first = _site("auth:test:1")
    second = _site("auth:test:2", (179.75, -64.125))
    with reuse_base_contract_fragments():
        assert base_contract([]) == {
            "base_count": 0,
            "base_ids_sha256": empty_digest,
            "base_sites_sha256": empty_digest,
        }
        assert base_contract([first]) == _reference_contract([first])
        forward = base_contract([first, second])
        reversed_order = base_contract([second, first])
        assert forward == _reference_contract([first, second])
        assert reversed_order == _reference_contract([second, first])
        assert reversed_order["base_ids_sha256"] != forward["base_ids_sha256"]
        assert reversed_order["base_sites_sha256"] != forward["base_sites_sha256"]


def test_same_id_distinguishes_replacement_content_and_signed_zero() -> None:
    positive = _site("auth:test:1", (0.0, 45.125))
    negative = _site("auth:test:1", (-0.0, 45.125))
    with reuse_base_contract_fragments():
        first = base_contract([positive])
        second = base_contract([negative])
        assert first == _reference_contract([positive])
        assert second == _reference_contract([negative])
        assert first["base_ids_sha256"] == second["base_ids_sha256"]
        assert first["base_sites_sha256"] != second["base_sites_sha256"]
        assert base_contract([positive]) == first


def test_mutating_a_nested_source_list_updates_the_same_sites_fingerprint() -> None:
    site = _site("auth:test:1")
    with reuse_base_contract_fragments():
        original = base_contract([site])
        site.chronology.phases[0].sources.append(
            site.source_refs[0].model_copy(update={"id": "notes", "excerpt": "补充证据"})
        )
        changed = base_contract([site])
        assert changed == _reference_contract([site])
        assert changed["base_ids_sha256"] == original["base_ids_sha256"]
        assert changed["base_sites_sha256"] != original["base_sites_sha256"]
        site.chronology.phases[0].sources.pop()
        assert base_contract([site]) == original


@pytest.mark.parametrize("exceptional_exit", [False, True])
def test_reuse_is_limited_to_the_context(
    monkeypatch: pytest.MonkeyPatch, exceptional_exit: bool,
) -> None:
    sites = [_site("auth:test:1"), _site("auth:test:2")]
    expected = _reference_contract(sites)
    batches = _record_site_encodings(monkeypatch)
    outcome = pytest.raises(RuntimeError, match="early exit") if exceptional_exit else nullcontext()
    with outcome, reuse_base_contract_fragments():
        assert base_contract(sites) == expected
        encoded_once = list(batches)
        assert sum(size for _, size in encoded_once) == len(sites)
        assert base_contract(sites) == expected
        assert batches == encoded_once
        if exceptional_exit:
            raise RuntimeError("early exit")

    batches.clear()
    assert base_contract(sites) == expected
    assert base_contract(sites) == expected
    assert batches == [(get_ident(), len(sites))] * 2


def test_active_contexts_in_two_threads_reuse_only_their_own_fragments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sites = [_site("auth:test:1")]
    expected = _reference_contract(sites)
    batches = _record_site_encodings(monkeypatch)
    worker_entered = Event()
    main_checked = Event()

    def check_worker() -> int:
        with reuse_base_contract_fragments():
            worker_entered.set()
            assert main_checked.wait(timeout=10)
            assert base_contract(sites) == expected
            assert base_contract(sites) == expected
        return get_ident()

    with ThreadPoolExecutor(max_workers=1) as pool, reuse_base_contract_fragments():
        assert base_contract(sites) == expected
        worker = pool.submit(check_worker)
        try:
            assert worker_entered.wait(timeout=10)
            assert base_contract(sites) == expected
        finally:
            main_checked.set()
        worker_ident = worker.result(timeout=10)
        assert base_contract(sites) == expected

    assert batches == [(get_ident(), 1), (worker_ident, 1)]
