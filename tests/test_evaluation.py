"""Metric fixtures need no downloaded model and never fabricate human labels."""

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from archsearch import evaluation
from archsearch.domain import Site
from archsearch.evaluation import (
    QueryPair,
    build_pool,
    gated_metrics,
    load_queries,
    query_contract_hash,
    query_metrics,
)
from archsearch.index import IndexUnavailable
from archsearch.search import SearchHit, SearchRequest


@pytest.fixture
def rankings() -> dict[str, dict[str, list[str]]]:
    return {
        "bm25_zh": {"q1": [], "q2": ["c"]},
        "bm25_en": {"q1": ["b", "a"], "q2": ["c"]},
        "semantic_zh": {"q1": ["a", "b"], "q2": ["c"]},
        "semantic_en": {"q1": ["a", "b"], "q2": ["c"]},
    }


@pytest.fixture
def qrels() -> dict[str, Any]:
    return {
        "confirmed": True,
        "assessor": "human-reviewer",
        "corpus_sha256": "fixture-hash",
        "query_contract_sha256": "fixture-query-hash",
        "judgments": [
            {
                "query_id": "q1",
                "site_id": "a",
                "relevance": 2,
                "evidence": "Source explicitly supports the query.",
            },
            {
                "query_id": "q1",
                "site_id": "b",
                "relevance": 1,
                "evidence": "Source supports part of the intent.",
            },
            {
                "query_id": "q2",
                "site_id": "c",
                "relevance": 0,
                "evidence": "Source does not support the requested association.",
            },
        ],
    }


def gate(
    rankings: dict[str, dict[str, list[str]]],
    qrels: dict[str, Any] | None,
    *,
    runs_complete: bool = True,
) -> tuple[dict[str, Any] | None, list[str]]:
    return gated_metrics(
        rankings,
        qrels_payload=qrels,
        corpus_sha256="fixture-hash",
        query_contract_sha256="fixture-query-hash",
        query_ids=["q1", "q2"],
        site_ids={"a", "b", "c"},
        runs_complete=runs_complete,
    )


def test_metrics_use_grades_and_judged_recall_denominator() -> None:
    metrics = query_metrics(["a", "b"], {"a": 2, "b": 1, "c": 1})
    assert metrics["recall_at_5"] == pytest.approx(2 / 3)
    assert metrics["ndcg_at_10"] == pytest.approx(
        (3 + 1 / math.log2(3)) / (3 + 1 / math.log2(3) + 0.5)
    )
    assert query_metrics(["a", "b"], {"a": 2, "b": 1})["ndcg_at_10"] == 1
    assert query_metrics(["b", "a"], {"a": 2, "b": 1})["ndcg_at_10"] < 1


def test_no_relevant_queries_are_null() -> None:
    assert query_metrics(["a"], {"a": 0}) == {"recall_at_5": None, "ndcg_at_10": None}
    with pytest.raises(ValueError, match="重复"):
        query_metrics(["a", "a"], {"a": 2})


def test_no_qrels_never_emits_metrics(rankings: dict[str, dict[str, list[str]]]) -> None:
    metrics, reasons = gate(rankings, None)
    assert metrics is None
    assert reasons
    assert build_pool(rankings, ["q1", "q2"]) == {"q1": {"a", "b"}, "q2": {"c"}}


def test_confirmed_complete_qrels_enable_metrics(
    rankings: dict[str, dict[str, list[str]]],
    qrels: dict[str, Any],
) -> None:
    metrics, reasons = gate(rankings, qrels)
    assert reasons == []
    assert metrics is not None
    assert metrics["semantic_zh"]["ndcg_at_10"] == 1
    assert metrics["bm25_zh"]["recall_at_5"] == 0
    assert metrics["semantic_zh"]["evaluated_queries"] == 1
    assert metrics["semantic_zh"]["queries_without_judged_relevant"] == 1


@pytest.mark.parametrize(
    "incomplete", ["unconfirmed", "no-assessor", "missing-query", "missing-pool", "not-run"]
)
def test_partial_or_unconfirmed_qrels_stay_unscored(
    rankings: dict[str, dict[str, list[str]]],
    qrels: dict[str, Any],
    incomplete: str,
) -> None:
    if incomplete == "unconfirmed":
        qrels["confirmed"] = False
    elif incomplete == "no-assessor":
        qrels["assessor"] = " "
    elif incomplete == "missing-query":
        qrels["judgments"].pop()
    elif incomplete == "missing-pool":
        qrels["judgments"][1]["relevance"] = None
        qrels["judgments"][1]["evidence"] = ""
    metrics, reasons = gate(rankings, qrels, runs_complete=incomplete != "not-run")
    assert metrics is None
    assert reasons


@pytest.mark.parametrize(
    "invalid",
    [
        "duplicate",
        "unknown-query",
        "unknown-site",
        "no-evidence",
        "old-corpus",
        "bad-grade",
        "boolean-grade",
    ],
)
def test_bad_qrels_are_rejected(
    rankings: dict[str, dict[str, list[str]]],
    qrels: dict[str, Any],
    invalid: str,
) -> None:
    if invalid == "duplicate":
        qrels["judgments"].append(deepcopy(qrels["judgments"][0]))
    elif invalid == "unknown-query":
        qrels["judgments"][0]["query_id"] = "unknown"
    elif invalid == "unknown-site":
        qrels["judgments"][0]["site_id"] = "unknown"
    elif invalid == "no-evidence":
        qrels["judgments"][0]["evidence"] = " "
    elif invalid == "old-corpus":
        qrels["corpus_sha256"] = "outdated-hash"
    elif invalid == "bad-grade":
        qrels["judgments"][0]["relevance"] = 3
    elif invalid == "boolean-grade":
        qrels["judgments"][0]["relevance"] = True
    with pytest.raises(ValueError):
        gate(rankings, qrels)


def test_packaged_queries_have_twenty_unique_pairs() -> None:
    pairs = load_queries()
    assert len(pairs) == 20
    assert len({pair.id for pair in pairs}) == 20
    assert all(pair.query_zh and pair.query_en and pair.topic for pair in pairs)


def test_changed_query_text_with_same_ids_rejects_old_judgments(
    rankings: dict[str, dict[str, list[str]]],
    qrels: dict[str, Any],
) -> None:
    original = [
        QueryPair("q1", "寻找港口", "Find ports", "type"),
        QueryPair("q2", "寻找剧场", "Find theaters", "type"),
    ]
    changed = [QueryPair("q1", "寻找浴场", "Find baths", "type"), original[1]]
    qrels["query_contract_sha256"] = query_contract_hash(original)
    assert query_contract_hash(original) != query_contract_hash(changed)
    with pytest.raises(ValueError, match="查询或过滤契约"):
        gated_metrics(
            rankings,
            qrels_payload=qrels,
            corpus_sha256="fixture-hash",
            query_contract_sha256=query_contract_hash(changed),
            query_ids=["q1", "q2"],
            site_ids={"a", "b", "c"},
        )


@pytest.mark.parametrize("extra_field", ["query_version", "future_schema"])
def test_unknown_qrels_version_fields_are_rejected(
    rankings: dict[str, dict[str, list[str]]],
    qrels: dict[str, Any],
    extra_field: str,
) -> None:
    qrels[extra_field] = "unsupported"
    with pytest.raises(ValueError, match="未知字段"):
        gate(rankings, qrels)


def test_missing_query_contract_rejects_old_qrels(
    rankings: dict[str, dict[str, list[str]]],
    qrels: dict[str, Any],
) -> None:
    qrels.pop("query_contract_sha256")
    with pytest.raises(ValueError, match="查询或过滤契约"):
        gate(rankings, qrels)


@pytest.mark.parametrize("warmup_failure", [False, True])
@pytest.mark.parametrize("qrels_filename", [None, "report.json.tmp", "report.pool.json.tmp"])
def test_evaluation_separates_cold_start_and_preserves_old_templates(
    tmp_path: Path,
    sample_sites: list[Site],
    monkeypatch: pytest.MonkeyPatch,
    warmup_failure: bool,
    qrels_filename: str | None,
) -> None:
    pairs = load_queries()
    corpus_bytes = b"fixture corpus bytes"
    (tmp_path / "sites.json").write_bytes(corpus_bytes)
    clock = {"seconds": 0.0}
    calls: list[tuple[str, str]] = []

    class FakeIndex:
        def __init__(self, sites: list[Site], home: Path) -> None:
            self.sites = sites
            self.ready = True
            self.reason = None

    class FakeEngine:
        def __init__(self, sites: list[Site], semantic: FakeIndex) -> None:
            self.sites = sites

        def search(self, request: SearchRequest) -> tuple[list[SearchHit], int]:
            calls.append((request.mode, request.query))
            if request.query == evaluation.WARMUP_QUERY:
                clock["seconds"] += 6.5
                if warmup_failure:
                    raise IndexUnavailable("fixture warmup failure")
            else:
                clock["seconds"] += 0.002
            return [SearchHit(site=self.sites[0], score=1, matched_fields=[])], len(self.sites)

    monkeypatch.setattr(evaluation, "DATA_DIR", tmp_path)
    monkeypatch.setattr(evaluation, "load_corpus", lambda: sample_sites)
    monkeypatch.setattr(evaluation, "SemanticIndex", FakeIndex)
    monkeypatch.setattr(evaluation, "SearchEngine", FakeEngine)
    monkeypatch.setattr(evaluation, "perf_counter", lambda: clock["seconds"])
    corpus_hash = hashlib.sha256(corpus_bytes).hexdigest()
    old_pool_signature = hashlib.sha256(
        json.dumps(
            {
                "corpus_sha256": corpus_hash,
                "queries": [(pair.id, pair.query_zh, pair.query_en) for pair in pairs],
                "pool": {pair.id: [sample_sites[0].id] for pair in pairs},
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    old_template = tmp_path / f"report.qrels-{old_pool_signature[:12]}.template.json"
    old_template.write_text('{"assessor":"existing human notes"}', "utf-8")

    qrels_path = tmp_path / qrels_filename if qrels_filename else None
    original_qrels: bytes | None = None
    if qrels_path is not None:
        original_qrels = json.dumps(
            {
                "confirmed": False,
                "assessor": "in-progress human annotations",
                "corpus_sha256": corpus_hash,
                "query_contract_sha256": query_contract_hash(pairs),
                "judgments": [],
            }
        ).encode("utf-8")
        qrels_path.write_bytes(original_qrels)
    report = evaluation.evaluate_corpus(tmp_path / "home", tmp_path / "report.json", qrels_path)
    if qrels_path is not None:
        assert qrels_path.read_bytes() == original_qrels
    assert not list(tmp_path.glob(".*.archsearch-*.tmp"))
    assert report["metrics"] is None
    assert report["cold_start_ms"] == pytest.approx(6500)
    assert report["warmup_query"] == evaluation.WARMUP_QUERY
    assert calls[0] == ("semantic", evaluation.WARMUP_QUERY)
    assert sum(query == evaluation.WARMUP_QUERY for _, query in calls) == 1
    for run_id, run in report["runs"].items():
        assert len(run["queries"]) == 20
        if warmup_failure and run_id.startswith("semantic"):
            assert run["mean_elapsed_ms"] is None
            assert all(record["error"] for record in run["queries"])
        else:
            assert run["mean_elapsed_ms"] == pytest.approx(2)
            assert run["median_elapsed_ms"] == pytest.approx(2)
            assert run["p95_elapsed_ms"] == pytest.approx(2)
    if warmup_failure:
        assert report["semantic_ready"] is False
        assert report["runs_complete"] is False
        assert report["status"] == "retrieval_incomplete"
        assert len(calls) == 41
    else:
        assert len(calls) == 81
    new_template = Path(report["artifacts"]["qrels_template"])
    assert new_template != old_template
    assert old_template.read_text("utf-8") == '{"assessor":"existing human notes"}'
    assert json.loads(new_template.read_text("utf-8"))[
        "query_contract_sha256"
    ] == query_contract_hash(pairs)


def test_json_failure_preserves_existing_files_and_cleans_its_own_temporary(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text("existing report", "utf-8")
    annotations = tmp_path / "report.json.tmp"
    annotations.write_text("human annotations", "utf-8")
    with pytest.raises(TypeError):
        evaluation.write_json(report, object())
    assert report.read_text("utf-8") == "existing report"
    assert annotations.read_text("utf-8") == "human annotations"
    assert not list(tmp_path.glob(".*.archsearch-*.tmp"))
