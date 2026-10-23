"""Check ranking behavior and explicit failures independently of model downloads."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from archsearch.domain import Site
from archsearch.index import IndexUnavailable, SemanticIndex
from archsearch.search import BM25, SearchEngine, SearchRequest, tokenize


def test_tokenization_normalizes_case_and_unicode() -> None:
    assert tokenize("ＲＯＭＡ, Harbor_123 港口") == ["roma", "harbor", "123", "港口"]


def test_bm25_has_positive_idf_and_zero_scores_for_unknown_terms() -> None:
    bm25 = BM25(["harbor", "harbor harbor", ""])
    assert np.all(bm25.scores("harbor")[:2] > 0)
    assert bm25.scores("harbor")[2] == 0
    assert np.array_equal(bm25.scores("不存在"), np.zeros(3))
    assert np.array_equal(bm25.scores("!!!"), np.zeros(3))
    assert np.array_equal(bm25.scores("harbor harbor"), bm25.scores("harbor"))
    assert BM25([]).scores("harbor").size == 0
    assert np.array_equal(BM25(["", ""]).scores("harbor"), np.zeros(2))


def test_bm25_no_overlap_is_empty_and_works_without_semantic_resources(
    tmp_path: Path, sample_sites: list[Site]
) -> None:
    engine = SearchEngine(sample_sites, SemanticIndex(sample_sites, tmp_path))
    hits, total = engine.search(SearchRequest(query="harbor", mode="bm25"))
    assert total == 2
    assert {hit.site.id for hit in hits} == {"2", "3"}
    assert all(hit.score > 0 and "title" in hit.matched_fields for hit in hits)
    assert engine.search(SearchRequest(query="港口", mode="bm25")) == ([], 0)
    with pytest.raises(IndexUnavailable):
        engine.search(SearchRequest(query="harbor", mode="semantic"))


def test_type_filter_limit_and_total_candidates(tmp_path: Path, sample_sites: list[Site]) -> None:
    engine = SearchEngine(sample_sites, SemanticIndex(sample_sites, tmp_path))
    hits, total = engine.search(SearchRequest(query="ancient", mode="bm25", type="port", limit=1))
    assert len(hits) == 1
    assert hits[0].site.types == ["port"]
    assert total == 2
    assert engine.search(SearchRequest(query="ancient", mode="bm25", type="unknown")) == ([], 0)


def test_tied_scores_have_deterministic_id_order_for_both_modes(
    tmp_path: Path, sample_sites: list[Site], monkeypatch: pytest.MonkeyPatch
) -> None:
    semantic = SemanticIndex(sample_sites, tmp_path)
    engine = SearchEngine(sample_sites, semantic)
    monkeypatch.setattr(semantic, "scores", lambda query: np.ones(3, dtype=np.float32))
    monkeypatch.setattr(engine.bm25, "scores", lambda query: np.ones(3))
    for mode in ("semantic", "bm25"):
        hits, total = engine.search(SearchRequest(query="roman", mode=mode))
        assert total == 3
        assert [hit.site.id for hit in hits] == ["1", "2", "3"]
        assert all("periods" in hit.matched_fields for hit in hits)


def test_semantic_failure_never_falls_back_to_bm25(
    tmp_path: Path, sample_sites: list[Site], monkeypatch: pytest.MonkeyPatch
) -> None:
    semantic = SemanticIndex(sample_sites, tmp_path)
    engine = SearchEngine(sample_sites, semantic)

    def fail(query: str) -> np.ndarray:
        raise IndexUnavailable("encoding failed")

    def forbidden_fallback(query: str) -> np.ndarray:
        raise AssertionError("semantic failures must not silently become BM25 results")

    monkeypatch.setattr(semantic, "scores", fail)
    monkeypatch.setattr(engine.bm25, "scores", forbidden_fallback)
    with pytest.raises(IndexUnavailable, match="encoding failed"):
        engine.search(SearchRequest(query="harbor", mode="semantic"))


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 501},
        {"query": "harbor", "mode": "hybrid"},
        {"query": "harbor", "limit": 0},
        {"query": "harbor", "limit": 51},
        {"query": "harbor", "unknown": "field"},
    ],
)
def test_invalid_search_requests_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SearchRequest.model_validate(payload)


def test_query_whitespace_is_trimmed() -> None:
    assert SearchRequest(query="  港口  ").query == "港口"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("description", "A changed source description."),
        ("names", ["A newly added alias"]),
        ("types", ["villa"]),
    ],
)
def test_same_ids_with_changed_retrieval_text_reject_old_semantic_index(
    tmp_path: Path, sample_sites: list[Site], field: str, value: str | list[str]
) -> None:
    semantic = SemanticIndex(sample_sites, tmp_path)
    changed = list(sample_sites)
    changed[0] = changed[0].model_copy(update={field: value})
    assert [site.id for site in changed] == [site.id for site in semantic.sites]
    with pytest.raises(ValueError, match="检索文本不匹配"):
        SearchEngine(changed, semantic)
