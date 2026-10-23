"""Reproducible paired-language runs with a strict manual-judgment gate."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter
from typing import Any, Literal

from archsearch.config import DATA_DIR, MODEL_ID, MODEL_REVISION, TEXT_VERSION
from archsearch.corpus import load_corpus
from archsearch.index import IndexUnavailable, SemanticIndex, document_contract
from archsearch.search import SearchEngine, SearchRequest

Mode = Literal["bm25", "semantic"]
Language = Literal["zh", "en"]
RUNS: tuple[tuple[Mode, Language], ...] = (
    ("bm25", "zh"),
    ("bm25", "en"),
    ("semantic", "zh"),
    ("semantic", "en"),
)
Rankings = Mapping[str, Mapping[str, Sequence[str]]]
WARMUP_QUERY = "ancient places"


@dataclass(frozen=True)
class QueryPair:
    id: str
    query_zh: str
    query_en: str
    topic: str


def query_contract_hash(pairs: Sequence[QueryPair]) -> str:
    """Bind judgments to exact paired intents and the fixed evaluation request."""
    contract = {
        "schema_version": 1,
        "queries": [
            {"id": pair.id, "query_zh": pair.query_zh, "query_en": pair.query_en} for pair in pairs
        ],
        "filters": {"type": None},
        "limit": 10,
    }
    encoded = json.dumps(contract, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_queries(path: Path = DATA_DIR / "queries.json") -> list[QueryPair]:
    """Load the same 20 research intents in Chinese and faithful English."""
    payload = json.loads(path.read_text("utf-8"))
    records = payload.get("queries") if isinstance(payload, dict) else None
    if not isinstance(records, list) or len(records) != 20:
        raise ValueError("评价查询文件必须包含20条中英配对查询。")
    pairs = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("评价查询必须是对象。")
        values = [record.get(key) for key in ("id", "query_zh", "query_en", "topic")]
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("每条查询必须有非空ID、中英文文本和主题。")
        pair = QueryPair(*(str(value).strip() for value in values))
        if pair.id in seen:
            raise ValueError(f"评价查询ID重复：{pair.id}")
        seen.add(pair.id)
        pairs.append(pair)
    return pairs


def query_metrics(
    ranked_ids: Sequence[str], judgments: Mapping[str, int]
) -> dict[str, float | None]:
    """Recall uses judged relevant documents only; nDCG uses gains 2**grade-1."""
    if len(set(ranked_ids)) != len(ranked_ids):
        raise ValueError("排名中不得重复出现同一资料。")
    relevant_count = sum(grade > 0 for grade in judgments.values())
    if not relevant_count:
        return {"recall_at_5": None, "ndcg_at_10": None}
    recall = sum(judgments.get(site_id, 0) > 0 for site_id in ranked_ids[:5]) / relevant_count
    dcg = sum(
        (2 ** judgments.get(site_id, 0) - 1) / math.log2(rank + 2)
        for rank, site_id in enumerate(ranked_ids[:10])
    )
    ideal = sum(
        (2**grade - 1) / math.log2(rank + 2)
        for rank, grade in enumerate(sorted(judgments.values(), reverse=True)[:10])
    )
    return {"recall_at_5": recall, "ndcg_at_10": dcg / ideal}


def build_pool(rankings: Rankings, query_ids: Sequence[str]) -> dict[str, set[str]]:
    """Pool the top ten of all four conditions without inventing relevance labels."""
    return {
        query_id: {
            site_id for queries in rankings.values() for site_id in queries.get(query_id, [])[:10]
        }
        for query_id in query_ids
    }


def validate_qrels(
    payload: Mapping[str, Any],
    *,
    corpus_sha256: str,
    query_contract_sha256: str,
    query_ids: Sequence[str],
    site_ids: set[str],
    pool: Mapping[str, set[str]],
) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Reject bad provenance; unconfirmed or incomplete labels stay unscored."""
    allowed_fields = {
        "confirmed",
        "assessor",
        "corpus_sha256",
        "query_contract_sha256",
        "instructions",
        "scope",
        "judgments",
    }
    if unknown_fields := set(payload) - allowed_fields:
        raise ValueError(f"qrels包含未知字段：{', '.join(sorted(unknown_fields))}")
    if payload.get("corpus_sha256") != corpus_sha256:
        raise ValueError("标注语料校验和不匹配，请基于当前语料重新标注。")
    if payload.get("query_contract_sha256") != query_contract_sha256:
        raise ValueError("标注查询或过滤契约校验和不匹配，请基于当前查询重新标注。")
    records = payload.get("judgments")
    if not isinstance(records, list):
        raise ValueError("qrels.judgments必须是列表。")
    allowed_queries = set(query_ids)
    judgments: dict[str, dict[str, int]] = {query_id: {} for query_id in query_ids}
    seen: set[tuple[str, str]] = set()
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("每条标注必须是对象。")
        if unknown_fields := set(item) - {"query_id", "site_id", "relevance", "evidence"}:
            raise ValueError(f"标注包含未知字段：{', '.join(sorted(unknown_fields))}")
        query_id, site_id = item.get("query_id"), item.get("site_id")
        if not isinstance(query_id, str) or query_id not in allowed_queries:
            raise ValueError(f"未知评价查询ID：{query_id}")
        if not isinstance(site_id, str) or site_id not in site_ids:
            raise ValueError(f"未知资料ID：{site_id}")
        pair = (query_id, site_id)
        if pair in seen:
            raise ValueError(f"重复标注：{query_id}/{site_id}")
        seen.add(pair)
        grade = item.get("relevance")
        if grade is None:
            continue
        if type(grade) is not int or grade not in (0, 1, 2):
            raise ValueError(f"相关程度必须为0、1、2或待标注null：{query_id}/{site_id}")
        evidence = item.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"已评分标注缺少判断依据：{query_id}/{site_id}")
        judgments[query_id][site_id] = grade
    reasons = []
    if payload.get("confirmed") is not True:
        reasons.append("标注尚未由人工设置confirmed=true。")
    assessor = payload.get("assessor")
    if not isinstance(assessor, str) or not assessor.strip():
        reasons.append("尚未填写人工标注者assessor。")
    missing_queries = [query_id for query_id in query_ids if not judgments[query_id]]
    if missing_queries:
        reasons.append(f"仍有{len(missing_queries)}个查询没有人工判定。")
    missing_pool = sum(
        len(site_set - judgments[query_id].keys()) for query_id, site_set in pool.items()
    )
    if missing_pool:
        reasons.append(f"四组top10并集标注池仍有{missing_pool}对查询与资料未判定。")
    return judgments, reasons


def score_rankings(
    rankings: Rankings, judgments: Mapping[str, Mapping[str, int]], query_ids: Sequence[str]
) -> dict[str, Any]:
    """Compute per-query and macro metrics after the caller validates the pool."""
    results = {}
    for run_id, query_rankings in rankings.items():
        per_query = {
            query_id: query_metrics(query_rankings.get(query_id, []), judgments[query_id])
            for query_id in query_ids
        }
        recall_values = [
            value for item in per_query.values() if (value := item["recall_at_5"]) is not None
        ]
        ndcg_values = [
            value for item in per_query.values() if (value := item["ndcg_at_10"]) is not None
        ]
        results[run_id] = {
            "recall_at_5": statistics.mean(recall_values) if recall_values else None,
            "ndcg_at_10": statistics.mean(ndcg_values) if ndcg_values else None,
            "evaluated_queries": len(recall_values),
            "queries_without_judged_relevant": len(query_ids) - len(recall_values),
            "per_query": per_query,
        }
    return results


def gated_metrics(
    rankings: Rankings,
    *,
    qrels_payload: Mapping[str, Any] | None,
    corpus_sha256: str,
    query_contract_sha256: str,
    query_ids: Sequence[str],
    site_ids: set[str],
    runs_complete: bool = True,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Never publish relevance metrics for machine-generated or partial labels."""
    if qrels_payload is None:
        reasons = ["尚未提供人工相关性标注；已生成标注池与空白模板。"]
        if not runs_complete:
            reasons.append("至少一组检索运行未完成，请先准备本地语义模型与索引。")
        return None, reasons
    judgments, reasons = validate_qrels(
        qrels_payload,
        corpus_sha256=corpus_sha256,
        query_contract_sha256=query_contract_sha256,
        query_ids=query_ids,
        site_ids=site_ids,
        pool=build_pool(rankings, query_ids),
    )
    if not runs_complete:
        reasons.append("至少一组检索运行未完成，不能发布完整对照指标。")
    return (None, reasons) if reasons else (score_rankings(rankings, judgments, query_ids), [])


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.archsearch-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def evaluate_corpus(home: Path, output: Path, qrels: Path | None = None) -> dict[str, Any]:
    """Write four paired runs, a review pool, and an unscored annotation template."""
    pairs = load_queries()
    query_ids = [pair.id for pair in pairs]
    query_contract_sha256 = query_contract_hash(pairs)
    sites = load_corpus()
    site_ids = {site.id for site in sites}
    corpus_sha256 = hashlib.sha256((DATA_DIR / "sites.json").read_bytes()).hexdigest()
    semantic = SemanticIndex(sites, home)
    engine = SearchEngine(sites, semantic)
    semantic_usable = semantic.ready
    warmup_error = semantic.reason if not semantic_usable else None
    cold_start_ms: float | None = None
    if semantic_usable:
        warmup_started = perf_counter()
        try:
            engine.search(SearchRequest(query=WARMUP_QUERY, mode="semantic", limit=1))
        except IndexUnavailable as error:
            semantic_usable = False
            warmup_error = str(error)
        finally:
            cold_start_ms = (perf_counter() - warmup_started) * 1000
    rankings: dict[str, dict[str, list[str]]] = {}
    runs: dict[str, Any] = {}
    runs_complete = True
    for mode, language in RUNS:
        run_id = f"{mode}_{language}"
        rankings[run_id] = {}
        records = []
        elapsed_values = []
        for pair in pairs:
            query = pair.query_zh if language == "zh" else pair.query_en
            started = perf_counter()
            try:
                if mode == "semantic" and not semantic_usable:
                    raise IndexUnavailable(warmup_error or "本地语义模型未准备。")
                hits, total = engine.search(SearchRequest(query=query, mode=mode, limit=10))
                elapsed = (perf_counter() - started) * 1000
                elapsed_values.append(elapsed)
                ranked = [hit.site.id for hit in hits]
                record: dict[str, Any] = {
                    "query_id": pair.id,
                    "query": query,
                    "elapsed_ms": elapsed,
                    "total_candidates": total,
                    "error": None,
                    "results": [
                        {"rank": rank, "site_id": hit.site.id, "score": hit.score}
                        for rank, hit in enumerate(hits, start=1)
                    ],
                }
            except IndexUnavailable as error:
                if mode == "semantic":
                    semantic_usable = False
                    warmup_error = str(error)
                ranked = []
                record = {
                    "query_id": pair.id,
                    "query": query,
                    "elapsed_ms": None,
                    "total_candidates": None,
                    "error": str(error),
                    "results": [],
                }
                runs_complete = False
            rankings[run_id][pair.id] = ranked
            records.append(record)
        runs[run_id] = {
            "mode": mode,
            "language": language,
            "queries": records,
            "mean_elapsed_ms": statistics.mean(elapsed_values) if elapsed_values else None,
            "median_elapsed_ms": statistics.median(elapsed_values) if elapsed_values else None,
            "p95_elapsed_ms": sorted(elapsed_values)[math.ceil(len(elapsed_values) * 0.95) - 1]
            if elapsed_values
            else None,
        }
    qrels_payload = None
    if qrels is not None:
        payload = json.loads(qrels.read_text("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("qrels文件必须为JSON对象。")
        qrels_payload = payload
    metrics, reasons = gated_metrics(
        rankings,
        qrels_payload=qrels_payload,
        corpus_sha256=corpus_sha256,
        query_contract_sha256=query_contract_sha256,
        query_ids=query_ids,
        site_ids=site_ids,
        runs_complete=runs_complete,
    )
    pool = build_pool(rankings, query_ids)
    by_id = {site.id: site for site in sites}
    pool_records = [
        {
            "query_id": pair.id,
            "query_zh": pair.query_zh,
            "query_en": pair.query_en,
            "candidates": [
                {
                    "site_id": site_id,
                    "title": by_id[site_id].title,
                    "description": by_id[site_id].description,
                    "details": by_id[site_id].details,
                    "source_uri": by_id[site_id].source_uri,
                    "runs": [
                        run_id
                        for run_id, queries in rankings.items()
                        if site_id in queries[pair.id]
                    ],
                }
                for site_id in sorted(pool[pair.id])
            ],
        }
        for pair in pairs
    ]
    pool_path = output.with_name(f"{output.stem}.pool.json")
    pool_signature = hashlib.sha256(
        json.dumps(
            {
                "corpus_sha256": corpus_sha256,
                "query_contract_sha256": query_contract_sha256,
                "pool": {query_id: sorted(site_set) for query_id, site_set in pool.items()},
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    template_path = output.with_name(f"{output.stem}.qrels-{pool_signature[:12]}.template.json")
    if qrels is not None and qrels.resolve() in {output.resolve(), pool_path.resolve()}:
        raise ValueError("标注输入路径不得与报告或候选池输出路径相同。")
    pool_scope = "同一语料、无过滤、BM25/E5×中文/英文四组各top10的并集；不是全语料穷尽相关性标注。"
    write_json(
        pool_path,
        {
            "corpus_sha256": corpus_sha256,
            "query_contract_sha256": query_contract_sha256,
            "scope": pool_scope,
            "pair_count": sum(map(len, pool.values())),
            "queries": pool_records,
        },
    )
    template = {
        "confirmed": False,
        "assessor": "",
        "corpus_sha256": corpus_sha256,
        "query_contract_sha256": query_contract_sha256,
        "instructions": (
            "阅读原始资料后填写relevance（0无关/1部分相关/2高度相关）及evidence；完成后确认。"
        ),
        "scope": pool_scope,
        "judgments": [
            {"query_id": pair.id, "site_id": site_id, "relevance": None, "evidence": ""}
            for pair in pairs
            for site_id in sorted(pool[pair.id])
        ],
    }
    template_preserved = template_path.exists()
    if not template_preserved:
        write_json(template_path, template)
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "retrieval_incomplete"
        if not runs_complete
        else ("evaluated" if metrics is not None else "awaiting_manual_judgments"),
        "metrics": metrics,
        "metric_gate_reasons": reasons,
        "runs_complete": runs_complete,
        "corpus_sha256": corpus_sha256,
        "query_contract_sha256": query_contract_sha256,
        "corpus_count": len(sites),
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "text_version": TEXT_VERSION,
        "document_contract": document_contract(sites),
        "semantic_ready": semantic_usable,
        "warmup_query": WARMUP_QUERY,
        "cold_start_ms": cold_start_ms,
        "warmup_error": warmup_error,
        "query_pairing": (
            "每对中英文表达同一研究意图；英文只用于离线对照，检索运行不自动翻译或扩词。"
        ),
        "queries": [
            {
                "id": pair.id,
                "query_zh": pair.query_zh,
                "query_en": pair.query_en,
                "topic": pair.topic,
            }
            for pair in pairs
        ],
        "pool_scope": pool_scope,
        "metric_definitions": {
            "recall_at_5": (
                "分母仅为该查询已人工标注相关（等级1或2）的资料数，不是未知全语料召回率。"
            ),
            "ndcg_at_10": (
                "分级收益2**relevance-1，折扣log2(rank+1)；理想排序来自该查询已标注资料。"
            ),
            "no_relevant_queries": "无已标相关资料的查询指标为null，排除于宏平均并单独计数。",
            "latency": (
                "四组串行计时前执行固定语义预热；mean/median/p95仅含预热后的查询编码与检索，"
                "p95使用最近秩法。cold_start_ms单独记录首次预热全过程，包含模型加载。"
            ),
        },
        "qrels": {
            "path": str(qrels) if qrels else None,
            "confirmed": qrels_payload.get("confirmed") is True if qrels_payload else False,
            "assessor": qrels_payload.get("assessor") if qrels_payload else None,
        },
        "artifacts": {
            "pool": str(pool_path),
            "qrels_template": str(template_path),
            "existing_template_preserved": template_preserved,
        },
        "runs": runs,
    }
    write_json(output, report)
    return report
