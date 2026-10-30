"""Same-origin HTTP API and static research interface."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import RequestResponseEndpoint
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
from archsearch.index import IndexUnavailable, SemanticIndex
from archsearch.search import SearchEngine, SearchHit, SearchRequest


class CorpusStatus(BaseModel):
    count: int
    version: str
    period: str


class SemanticStatus(BaseModel):
    ready: bool
    reason: str | None
    model: str = MODEL_ID
    revision: str = MODEL_REVISION


class StatusResponse(BaseModel):
    status: str
    corpus: CorpusStatus
    semantic: SemanticStatus


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
) -> FastAPI:
    corpus = load_corpus() if sites is None else sites
    index = semantic if semantic is not None else SemanticIndex(corpus, home)
    engine = SearchEngine(corpus, index)
    type_counts = Counter(kind for site in corpus for kind in set(site.types))
    app = FastAPI(title="古迹检索 ArchSearch", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.engine = engine

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
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/status", response_model=StatusResponse)
    def status() -> StatusResponse:
        ready = index.ready
        return StatusResponse(
            status="ready" if ready else "degraded",
            corpus=CorpusStatus(count=len(corpus), version=CORPUS_VERSION, period=PERIOD_LABEL),
            semantic=SemanticStatus(ready=ready, reason=index.reason),
        )

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
