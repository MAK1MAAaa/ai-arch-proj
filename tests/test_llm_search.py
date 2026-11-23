"""LLM variants only change retrieval rankings, never sources or explicit filters."""

from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from pydantic import ValidationError

from archsearch.domain import Site
from archsearch.index import IndexUnavailable, SemanticIndex
from archsearch.search import SearchEngine, SearchRequest


def test_expansion_recovers_keyword_match_and_preserves_complete_source_records(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    before = [site.model_dump(mode="json") for site in sample_sites]
    engine = SearchEngine(sample_sites, SemanticIndex(sample_sites, tmp_path))
    request = SearchRequest(query="沐浴", mode="bm25", type="bath")
    assert engine.search(request) == ([], 0)
    hits, total = engine.search_expanded(request, [request.query, "bath"])
    assert total == 1 and [hit.site.id for hit in hits] == ["1"]
    assert hits[0].score == pytest.approx(1 / 61)
    assert "title" in hits[0].matched_fields and "types" in hits[0].matched_fields
    assert hits[0].site.model_dump(mode="json") == before[1]
    assert [site.model_dump(mode="json") for site in sample_sites] == before


def test_semantic_rrf_keeps_filters_full_rankings_and_deterministic_ties(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    semantic = Mock(spec=SemanticIndex)
    semantic.sites = sample_sites
    semantic.scores_many.return_value = (
        np.array([0.9, 0.1, 0.2], dtype=np.float32),
        np.array([0.2, 0.1, 0.9], dtype=np.float32),
    )
    engine = SearchEngine(sample_sites, semantic)
    request = SearchRequest(query="港口", type="port", limit=2)
    hits, total = engine.search_expanded(request, [request.query, "harbor"])
    assert total == 2 and [hit.site.id for hit in hits] == ["2", "3"]
    assert all(hit.score == pytest.approx(1 / 61 + 1 / 62) for hit in hits)
    assert all(hit.site.types == ["port"] for hit in hits)
    semantic.scores_many.assert_called_once_with(["港口", "harbor"])
    semantic.scores.assert_not_called()


def test_expanded_empty_scope_and_keyword_miss_have_no_invented_candidates(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    semantic = Mock(spec=SemanticIndex)
    semantic.sites = sample_sites
    engine = SearchEngine(sample_sites, semantic)
    assert engine.search_expanded(
        SearchRequest(query="港口", type="missing"),
        ["港口", "harbor"],
    ) == ([], 0)
    assert engine.search_expanded(
        SearchRequest(query="xyzmissingkeyword", mode="bm25"),
        ["xyzmissingkeyword", "zzzabsent"],
    ) == ([], 0)
    semantic.scores_many.assert_not_called()
    semantic.scores.assert_not_called()


def test_expanded_semantic_failure_does_not_switch_to_keywords(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    semantic = Mock(spec=SemanticIndex)
    semantic.sites = sample_sites
    semantic.scores_many.side_effect = IndexUnavailable("missing local model")
    engine = SearchEngine(sample_sites, semantic)
    engine.bm25.scores = Mock(side_effect=AssertionError("unexpected keyword fallback"))
    with pytest.raises(IndexUnavailable, match="missing local model"):
        engine.search_expanded(SearchRequest(query="港口"), ["港口", "harbor"])
    semantic.scores.assert_not_called()


@pytest.mark.parametrize(
    "queries",
    [
        [],
        ["other"],
        ["港口", "a", "b", "c"],
        ["港口", ""],
        ["港口", "a" * 501],
        ["港口", "Harbor", "harbor"],
        ["港口", "港口"],
    ],
)
def test_invalid_expansion_contract_is_rejected(
    tmp_path: Path,
    sample_sites: list[Site],
    queries: list[str],
) -> None:
    engine = SearchEngine(sample_sites, SemanticIndex(sample_sites, tmp_path))
    with pytest.raises(ValueError):
        engine.search_expanded(SearchRequest(query="港口", mode="bm25"), queries)


@pytest.mark.parametrize(
    "fields",
    [
        {"enhance": True},
        {"enhance": True, "llm_revision": -1},
        {"enhance": True, "llm_revision": True},
        {"enhance": True, "llm_revision": "1"},
        {"enhance": "true", "llm_revision": 1},
        {"llm_revision": 1},
        {"enhance": False, "llm_revision": 0},
    ],
)
def test_enhancement_intent_and_revision_are_strict(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SearchRequest.model_validate({"query": "港口", **fields})
