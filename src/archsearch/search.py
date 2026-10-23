"""Shared-document BM25 and semantic ranking over a small, fixed corpus."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, field_validator

from archsearch.corpus import build_document
from archsearch.domain import Site
from archsearch.index import SemanticIndex


def tokenize(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    mode: Literal["semantic", "bm25"] = "semantic"
    type: str | None = None
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("查询不能为空")
        return value


class SearchHit(BaseModel):
    site: Site
    score: float
    matched_fields: list[str]


class BM25:
    """BM25 with positive Robertson IDF, k1=1.5 and b=0.75."""

    def __init__(self, documents: list[str]) -> None:
        self.terms = [Counter(tokenize(doc)) for doc in documents]
        self.lengths = np.asarray([sum(doc.values()) for doc in self.terms], dtype=np.float64)
        mean_length = float(self.lengths.mean()) if documents else 0.0
        self.average_length = mean_length if mean_length > 0 else 1.0
        self.frequency: Counter[str] = Counter()
        for document in self.terms:
            self.frequency.update(document.keys())

    def scores(self, query: str) -> NDArray[np.float64]:
        scores = np.zeros(len(self.terms), dtype=np.float64)
        for term in sorted(set(tokenize(query))):
            count = self.frequency.get(term, 0)
            if not count:
                continue
            inverse = math.log1p((len(self.terms) - count + 0.5) / (count + 0.5))
            frequency = np.asarray([doc.get(term, 0) for doc in self.terms], dtype=np.float64)
            denominator = frequency + 1.5 * (0.25 + 0.75 * self.lengths / self.average_length)
            scores += inverse * frequency * 2.5 / denominator
        return scores


class SearchEngine:
    def __init__(self, sites: list[Site], semantic: SemanticIndex) -> None:
        self.sites = list(sites)
        self.semantic = semantic
        documents = [build_document(site) for site in self.sites]
        current = list(zip((site.id for site in self.sites), documents, strict=True))
        indexed = [(site.id, build_document(site)) for site in semantic.sites]
        if current != indexed:
            raise ValueError("检索引擎和语义索引的语料编号、顺序或检索文本不匹配。")
        if len({site.id for site in sites}) != len(sites):
            raise ValueError("检索语料包含重复的地点编号。")
        self.bm25 = BM25(documents)
        self.by_id = {site.id: site for site in sites}

    def search(self, request: SearchRequest) -> tuple[list[SearchHit], int]:
        candidates = [
            i
            for i, site in enumerate(self.sites)
            if request.type is None or request.type in site.types
        ]
        if not candidates:
            return [], 0
        scores = (
            self.semantic.scores(request.query)
            if request.mode == "semantic"
            else self.bm25.scores(request.query)
        )
        if request.mode == "bm25":
            candidates = [i for i in candidates if scores[i] > 0]
        candidates.sort(key=lambda i: (-float(scores[i]), self.sites[i].id))
        tokens = set(tokenize(request.query))
        hits = []
        for i in candidates[: request.limit]:
            site = self.sites[i]
            fields = {
                "title": site.title,
                "names": " ".join(site.names),
                "description": site.description,
                "details": site.details,
                "types": " ".join(site.types),
                "periods": " ".join(site.periods),
            }
            matched = [name for name, text in fields.items() if tokens & set(tokenize(text))]
            hits.append(SearchHit(site=site, score=float(scores[i]), matched_fields=matched))
        return hits, len(candidates)
