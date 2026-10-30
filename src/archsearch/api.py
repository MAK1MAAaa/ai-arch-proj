"""Same-origin HTTP API and static research interface."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response

from archsearch.config import (
    DEFAULT_HOME,
    MODEL_ID,
    MODEL_REVISION,
    PERIOD_LABEL,
    STATIC_DIR,
    TYPE_LABELS,
)
from archsearch.corpus import CORPUS_VERSION, load_corpus
from archsearch.domain import Site
from archsearch.history import HistoryStore, HistoryUnavailable, validate_year
from archsearch.index import IndexUnavailable, SemanticIndex
from archsearch.search import SearchEngine, SearchHit, SearchRequest

HISTORY_PATH = "/api/history/boundaries"
HISTORY_PREPARE = "请运行 uv run --no-sync archsearch prepare-history 准备或修复历史疆域缓存。"
HISTORY_CACHE_CONTROL = "private, no-cache"
_ENTITY_TAG = r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]*"'


def _etag_matches(value: str | None, etag: str) -> bool:
    if value is None or not re.fullmatch(
        rf"\s*(?:\*|{_ENTITY_TAG}(?:\s*,\s*{_ENTITY_TAG})*)\s*", value
    ):
        return False
    return value.strip() == "*" or any(
        candidate.removeprefix("W/") == etag.removeprefix("W/")
        for candidate in re.findall(_ENTITY_TAG, value)
    )


class CorpusStatus(BaseModel):
    count: int
    version: str
    period: str


class SemanticStatus(BaseModel):
    ready: bool
    reason: str | None
    model: str = MODEL_ID
    revision: str = MODEL_REVISION


class HistoryStatus(BaseModel):
    ready: bool
    reason: str | None
    version: str
    min_year: int
    max_year: int
    change_years: list[int]
    feature_count: int = 0
    counts: dict[str, int] | None = None
    source: dict[str, Any] = Field(default_factory=dict)
    normalization: dict[str, Any] = Field(default_factory=dict)


class StatusResponse(BaseModel):
    status: str
    corpus: CorpusStatus
    semantic: SemanticStatus
    history: HistoryStatus


class Facet(BaseModel):
    id: str
    label: str
    count: int


class FacetResponse(BaseModel):
    types: list[Facet]


class SearchResponse(BaseModel):
    results: list[SearchHit]
    mode: str
    query: str
    elapsed_ms: float
    corpus_version: str
    total_candidates: int


def create_app(
    home: Path = DEFAULT_HOME,
    sites: list[Site] | None = None,
    semantic: SemanticIndex | None = None,
    history: HistoryStore | None = None,
) -> FastAPI:
    corpus = load_corpus() if sites is None else sites
    index = semantic if semantic is not None else SemanticIndex(corpus, home)
    history_store = history if history is not None else HistoryStore(home)
    engine = SearchEngine(corpus, index)
    type_counts = Counter(kind for site in corpus for kind in set(site.types))
    app = FastAPI(title="古迹检索 ArchSearch", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.engine = engine
    app.state.history = history_store
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

    @app.middleware("http")
    async def response_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://*.tile.openstreetmap.org; "
            "connect-src 'self' https://*.tile.openstreetmap.org; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        if request.url.path == HISTORY_PATH and response.status_code in (200, 304):
            response.headers["Cache-Control"] = HISTORY_CACHE_CONTROL
            vary = [
                part.strip() for part in response.headers.get("Vary", "").split(",") if part.strip()
            ]
            if not any(part.casefold() == "accept-encoding" for part in vary):
                vary.append("Accept-Encoding")
            response.headers["Vary"] = ", ".join(vary)
        elif request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/status", response_model=StatusResponse)
    def status() -> StatusResponse:
        ready = index.ready
        history_state = history_store.status()
        if not history_state["ready"]:
            history_state["reason"] = (
                f"{history_state.get('reason') or '历史疆域缓存不可用。'} {HISTORY_PREPARE}"
            )
        return StatusResponse(
            status="ready" if ready else "degraded",
            corpus=CorpusStatus(count=len(corpus), version=CORPUS_VERSION, period=PERIOD_LABEL),
            semantic=SemanticStatus(ready=ready, reason=index.reason),
            history=HistoryStatus.model_validate(history_state),
        )

    @app.get(HISTORY_PATH)
    def historical_boundaries(request: Request, year: str) -> Response:
        if len(request.query_params.getlist("year")) != 1 or not re.fullmatch(
            r"-?[1-9][0-9]{0,4}", year
        ):
            raise HTTPException(status_code=422, detail="year 必须是唯一的非零整数年份。")
        try:
            selected_year = validate_year(int(year))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            collection, source_etag = history_store.boundaries(selected_year)
        except HistoryUnavailable as error:
            raise HTTPException(status_code=503, detail=f"{error} {HISTORY_PREPARE}") from error
        # A weak validator remains valid across gzip/identity representations of the same JSON.
        etag = source_etag if source_etag.startswith("W/") else "W/" + source_etag
        headers = {"ETag": etag, "Cache-Control": HISTORY_CACHE_CONTROL}
        conditional = ",".join(request.headers.getlist("if-none-match")) or None
        if _etag_matches(conditional, etag):
            return Response(status_code=304, headers=headers)
        return JSONResponse(collection, headers=headers, media_type="application/geo+json")

    @app.get("/api/facets", response_model=FacetResponse)
    def facets() -> FacetResponse:
        return FacetResponse(
            types=[
                Facet(id=kind, label=TYPE_LABELS.get(kind, kind), count=count)
                for kind, count in sorted(type_counts.items(), key=lambda pair: (-pair[1], pair[0]))
            ]
        )

    @app.post("/api/search", response_model=SearchResponse)
    def search(body: SearchRequest) -> SearchResponse:
        if body.type is not None and body.type not in type_counts:
            raise HTTPException(status_code=422, detail="未知地点类型，请从类型筛选列表选择。")
        started = perf_counter()
        if body.mode == "semantic" and not index.ready:
            raise HTTPException(status_code=503, detail=index.reason or "本地语义模型尚未准备。")
        try:
            hits, total = engine.search(body)
        except IndexUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return SearchResponse(
            results=hits,
            mode=body.mode,
            query=body.query,
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
            corpus_version=CORPUS_VERSION,
            total_candidates=total,
        )

    @app.get("/api/sites/{site_id}", response_model=Site)
    def site_detail(site_id: str) -> Site:
        site = engine.by_id.get(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="地点不存在于本演示语料中。")
        return site

    @app.get("/", include_in_schema=False)
    def homepage() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")
    return app
