"""Check ranking behavior and explicit failures independently of model downloads."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from archsearch.domain import Geography, Site, SourceReference
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
        {"query": "harbor", "country": "cn"},
        {"query": "harbor", "country": "CHN"},
        {"query": "harbor", "country": ""},
        {"query": "harbor", "region": "unknown"},
    ],
)
def test_invalid_search_requests_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SearchRequest.model_validate(payload)


def test_query_whitespace_is_trimmed() -> None:
    assert SearchRequest(query="  港口  ").query == "港口"


def test_geographic_filters_select_source_membership_before_ranking(
    tmp_path: Path, sample_sites: list[Site], monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SourceReference(
        id="geo", title="Catalogue membership", uri="https://example.org/geo", publisher="Test",
    )
    sites = list(sample_sites)
    sites[0] = sites[0].model_copy(update={"geography": Geography(
        countries=["CN", "JP"], regions=["asia-pacific"], source=source,
    )})
    sites[1] = sites[1].model_copy(update={"geography": Geography(
        countries=["FR"], regions=["europe-north-america"], source=source,
    )})
    semantic = SemanticIndex(sites, tmp_path)
    engine = SearchEngine(sites, semantic)
    monkeypatch.setattr(semantic, "scores", lambda query: np.asarray([0.1, 0.9, 1.0]))
    for mode in ("semantic", "bm25"):
        hits, total = engine.search(SearchRequest(
            query="ancient", mode=mode, country="CN", region="asia-pacific", type="port",
        ))
        assert total == 1 and [hit.site.id for hit in hits] == [sites[0].id]
    assert engine.search(SearchRequest(
        query="ancient", mode="semantic", country="FR", region="asia-pacific",
    )) == ([], 0)
    assert engine.search(SearchRequest(query="ancient", mode="bm25", country="XX")) == ([], 0)


def test_geography_with_no_candidates_does_not_encode_a_query(
    tmp_path: Path, sample_sites: list[Site], monkeypatch: pytest.MonkeyPatch,
) -> None:
    semantic = SemanticIndex(sample_sites, tmp_path)
    engine = SearchEngine(sample_sites, semantic)

    def forbidden_encoding(query: str) -> np.ndarray:
        raise AssertionError("empty source membership must not invoke semantic encoding")

    monkeypatch.setattr(semantic, "scores", forbidden_encoding)
    assert engine.search(SearchRequest(query="harbor", country="CN")) == ([], 0)


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


def supplementary_site(
    identifier: str, *, title: str = "Fixture place", description: str = "",
    description_zh: str = "", references: list[SourceReference] | None = None,
) -> Site:
    source = SourceReference(
        id="qualification:fixture", title="Cultural qualification",
        uri="https://example.org/cultural", publisher="Fixture authority",
    )
    return Site(
        id="auth:fixture:" + identifier, title=title, description=description,
        description_zh=description_zh, details="", names=[], types=["historic-site"],
        periods=[], period_evidence=[], repr_point=(10, 40), location_precision=None,
        source_uri=source.uri, contributors=[], source_kind="supplement",
        source_refs=[source] if references is None else references,
        geography=Geography(
            authority_id="supplement:auth:fixture:" + identifier,
            countries=["FR"], regions=["europe-north-america"], source=source,
        ),
    )


@pytest.mark.parametrize(("query", "expected"), [
    ("西伯利亚", "siberia"), ("旧石器", "siberia"), ("电报站", "telegraph"),
])
def test_chinese_subwords_retrieve_long_translations_without_a_local_model(
    tmp_path: Path, query: str, expected: str,
) -> None:
    sites = [
        supplementary_site(
            "siberia", description="upper Palaeolithic site in northeastern Siberia",
            description_zh="西伯利亚东北部的旧石器时代晚期遗址",
        ),
        supplementary_site(
            "telegraph", description="telegraph station in the Northern Territory",
            description_zh="位于北领地的电报站",
        ),
    ]
    semantic = SemanticIndex(sites, tmp_path)
    assert not semantic.ready
    engine = SearchEngine(sites, semantic)
    hits, total = engine.search(SearchRequest(query=query, mode="bm25"))
    assert total == 1 and [hit.site.id for hit in hits] == ["auth:fixture:" + expected]
    assert hits[0].score > 0 and hits[0].matched_fields == ["description_zh"]
    assert engine.search(SearchRequest(query="玛雅王宫", mode="bm25")) == ([], 0)


def test_chinese_runs_retain_full_words_without_duplicate_short_tokens() -> None:
    assert tokenize("港口") == ["港口"]
    assert tokenize("河") == ["河"]
    assert tokenize("北极遗址").count("北极遗址") == 1
    bm25 = BM25(["河", "河岸", "河，岸", "考古遗址", "考，古遗址"])
    assert np.flatnonzero(bm25.scores("河")).tolist() == [0, 2]
    assert np.flatnonzero(bm25.scores("河岸")).tolist() == [1]
    assert np.flatnonzero(bm25.scores("考古")).tolist() == [3]
    assert np.array_equal(bm25.scores("港口"), np.zeros(5))


def test_extended_han_characters_are_searchable_without_spanning_punctuation() -> None:
    bm25 = BM25(["𠀀𰀀遗址", "𠀀，𰀀遗址", "𠀀", "别处遗址"])
    assert np.flatnonzero(bm25.scores("𠀀𰀀")).tolist() == [0]
    assert np.flatnonzero(bm25.scores("𠀀")).tolist() == [1, 2]
    assert np.flatnonzero(bm25.scores("𰀀遗")).tolist() == [0, 1]


def test_compatibility_han_can_match_inside_a_name_without_crossing_punctuation() -> None:
    bm25 = BM25(["山﨑城址", "山﨑、城址", "SAKI2024"])
    assert np.flatnonzero(bm25.scores("﨑城")).tolist() == [0]


def test_mixed_han_latin_digits_and_non_han_words_keep_their_boundaries() -> None:
    bm25 = BM25([
        "ＨＭＳ２０２４西伯利亚B2", "hms_2024西伯利亚B2", "hms2024,西伯利亚,b2",
    ])
    assert np.flatnonzero(bm25.scores("HMS2024")).tolist() == [0, 2]
    assert np.flatnonzero(bm25.scores("hms")).tolist() == [1]
    assert np.flatnonzero(bm25.scores("2024")).tolist() == [1]
    assert np.flatnonzero(bm25.scores("西伯利亚")).tolist() == [0, 1, 2]
    assert np.flatnonzero(bm25.scores("B2")).tolist() == [0, 1, 2]
    assert not {"2024西", "亚b2", "hms2024西伯利亚b2"} & set(
        tokenize("ＨＭＳ２０２４西伯利亚B2")
    )
    other_words = BM25(["ＣＡＦÉ カタカナ Москва", "cafe カタ カナ"])
    assert np.flatnonzero(other_words.scores("CAFÉ")).tolist() == [0]
    assert np.flatnonzero(other_words.scores("カタカナ")).tolist() == [0]
    assert np.flatnonzero(other_words.scores("МОСКВА")).tolist() == [0]


@pytest.mark.parametrize(("identifier", "uri"), [
    ("qualification:authority", "https://example.org/qualification"),
    ("legacy-authority", "https://example.org/cultural"),
])
def test_real_indexed_source_evidence_reports_source_refs_as_the_matching_field(
    tmp_path: Path, identifier: str, uri: str,
) -> None:
    source = SourceReference(
        id=identifier, title="Original evidence", uri=uri, publisher="Fixture authority",
        excerpt="石砌祭祀建筑群",
    )
    sites = [supplementary_site("evidence", references=[source])]
    engine = SearchEngine(sites, SemanticIndex(sites, tmp_path))
    hits, total = engine.search(SearchRequest(query="祭祀", mode="bm25"))
    assert total == 1 and hits[0].site.id == "auth:fixture:evidence"
    assert hits[0].score > 0 and hits[0].matched_fields == ["source_refs"]


def test_regional_metadata_is_not_indexed_or_reported_as_matching_evidence(tmp_path: Path) -> None:
    qualification = SourceReference(
        id="qualification:authority", title="Cultural evidence",
        uri="https://example.org/cultural", publisher="Fixture authority", excerpt="石砌祭祀建筑群",
    )
    metadata = SourceReference(
        id="region:membership", title="Regional association", uri="https://example.org/region",
        publisher="Fixture authority", excerpt="欧洲和北美地区的元数据说明",
    )
    sites = [
        supplementary_site("metadata-only", references=[qualification, metadata]),
        supplementary_site("body-text", description_zh="欧洲的古城遗存",
                           references=[qualification, metadata]),
    ]
    engine = SearchEngine(sites, SemanticIndex(sites, tmp_path))
    hits, total = engine.search(SearchRequest(query="欧洲", mode="bm25"))
    assert total == 1 and hits[0].site.id == "auth:fixture:body-text"
    assert hits[0].matched_fields == ["description_zh"]
    assert engine.search(SearchRequest(query="元数据", mode="bm25")) == ([], 0)


def test_non_supplement_references_do_not_create_new_retrieval_evidence(
    tmp_path: Path, sample_sites: list[Site],
) -> None:
    source = SourceReference(
        id="qualification:unindexed", title="Not in the original cohort document",
        uri=sample_sites[0].source_uri, publisher="Fixture authority", excerpt="夏商祭祀遗存",
    )
    sites = [sample_sites[0].model_copy(update={"source_refs": [source]})]
    engine = SearchEngine(sites, SemanticIndex(sites, tmp_path))
    assert engine.search(SearchRequest(query="夏商", mode="bm25")) == ([], 0)


def test_english_case_normalization_and_tied_ranking_remain_stable_without_a_model(
    tmp_path: Path,
) -> None:
    sites = [supplementary_site(identifier, title="Roman harbor") for identifier in ("z", "a")]
    engine = SearchEngine(sites, SemanticIndex(sites, tmp_path))
    scores = []
    for query in ("ＲＯＭＡＮ", "roman", "ROMAN roman"):
        hits, total = engine.search(SearchRequest(query=query, mode="bm25"))
        assert total == 2
        assert [hit.site.id for hit in hits] == ["auth:fixture:a", "auth:fixture:z"]
        assert all(hit.score > 0 and hit.matched_fields == ["title"] for hit in hits)
        scores.append([hit.score for hit in hits])
    assert scores[0] == scores[1] == scores[2]
    assert engine.search(SearchRequest(query="unknownword", mode="bm25")) == ([], 0)
