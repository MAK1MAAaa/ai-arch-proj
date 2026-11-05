"""Same-origin HTTP API and static research interface."""

from __future__ import annotations

import ipaddress
import os
import re
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response

from archsearch.bounds import SpatialBounds
from archsearch.config import (
    DEFAULT_HOME,
    MODEL_ID,
    MODEL_REVISION,
    PERIOD_LABEL,
    STATIC_DIR,
    TYPE_LABELS,
)
from archsearch.corpus import CORPUS_VERSION, load_corpus
from archsearch.coverage import (
    CatalogueIndex,
    CatalogueResponse,
    CoverageResponse,
    SiteLocationsResponse,
    SitePage,
    SpatialLocationCoverage,
)
from archsearch.domain import Site
from archsearch.history import HistoryStore, HistoryUnavailable, validate_year
from archsearch.hong_kong_areas import load_hong_kong_area_group
from archsearch.index import IndexUnavailable, SemanticIndex
from archsearch.llm import (
    ConfigApply,
    ConfigConflict,
    ConfigDraft,
    ConfigInvalid,
    LlmManager,
    LlmUnavailable,
    ModelsResponse,
    PublicConfig,
)
from archsearch.registered_areas import (
    RegisteredAreasIndex,
    RegisteredAreasResponse,
    RegisteredAreasStatus,
)
from archsearch.search import SearchEngine, SearchHit, SearchRequest
from archsearch.spatial_data import SpatialDataError
from archsearch.subdivisions import (
    SiteSubdivisionsResponse,
    SubdivisionFacetsResponse,
    SubdivisionIndex,
    SubdivisionStatus,
    SubdivisionUnavailable,
)

HISTORY_PATH = "/api/history/boundaries"
HISTORY_PREPARE = "请运行 uv run --no-sync archsearch prepare-history 准备或修复历史疆域缓存。"
HISTORY_CACHE_CONTROL = "private, no-cache"
_ENTITY_TAG = r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]*"'


def _require_same_origin(request: Request) -> None:
    try:
        authority = urlsplit("//" + request.headers.get("host", ""))
        host = (authority.hostname or "").casefold().rstrip(".")
        if (not host or authority.username is not None or authority.password is not None
                or authority.path or authority.query or authority.fragment):
            raise ValueError
        port = authority.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        allowed = host == "localhost" or host.endswith(".ts.net")
        try:
            ipaddress.ip_address(host)
            allowed = True
        except ValueError:
            pass
        configured = {name.strip().casefold().rstrip(".") for name in
                      os.environ.get("ARCHSEARCH_LLM_TRUSTED_HOSTS", "").split(",")}
        allowed = allowed or host in configured
    except ValueError:
        allowed = False
    if not allowed:
        raise HTTPException(status_code=403, detail="请从本机、Tailscale或明确授权的域名配置LLM。")
    origin = request.headers.get("origin")
    if origin is None:
        return
    try:
        parsed = urlsplit(origin)
        valid = (parsed.scheme in {"http", "https"}
                 and parsed.netloc.casefold() == request.headers.get("host", "").casefold()
                 and not parsed.username and not parsed.password
                 and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(status_code=403, detail="模型设置与增强请求须来自当前页面。")


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
    spatial_locations: SpatialLocationCoverage | None = None
    registered_areas: RegisteredAreasStatus | None = None
    subdivisions: SubdivisionStatus | None = None
    llm: PublicConfig | None = None


class Facet(BaseModel):
    id: str
    label: str
    count: int


class FacetResponse(BaseModel):
    types: list[Facet]


class SearchEnhancement(BaseModel):
    requested: Literal[True] = True
    applied: bool
    provider: Literal["ollama", "openai"]
    model: str
    queries: list[str]
    elapsed_ms: float
    ranking_method: Literal["rrf", "original"]
    reason: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchHit]
    mode: str
    query: str
    elapsed_ms: float
    corpus_version: str
    total_candidates: int
    subdivision: str | None = None
    subdivision_version: str | None = None
    enhancement: SearchEnhancement | None = None


def create_app(
    home: Path = DEFAULT_HOME,
    sites: list[Site] | None = None,
    semantic: SemanticIndex | None = None,
    history: HistoryStore | None = None,
    areas: RegisteredAreasIndex | None = None,
    subdivisions: SubdivisionIndex | None = None,
    llm: LlmManager | None = None,
) -> FastAPI:
    corpus = load_corpus() if sites is None else sites
    index = semantic if semantic is not None else SemanticIndex(corpus, home)
    history_store = history if history is not None else HistoryStore(home)
    subdivision_index = (subdivisions if subdivisions is not None
                         else SubdivisionIndex(corpus, CORPUS_VERSION))
    engine = SearchEngine(corpus, index, subdivision_index)
    catalogue_index = CatalogueIndex(corpus, CORPUS_VERSION, subdivisions=subdivision_index)
    llm_manager = llm if llm is not None else LlmManager()
    if areas is not None:
        area_index = areas
    else:
        hong_kong_areas = load_hong_kong_area_group()
        area_index = RegisteredAreasIndex(sources=[hong_kong_areas] if hong_kong_areas else [])
    type_counts = Counter(kind for site in corpus for kind in set(site.types))
    app = FastAPI(title="古迹检索 ArchSearch", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.engine = engine
    app.state.history = history_store
    app.state.catalogue = catalogue_index
    app.state.registered_areas = area_index
    app.state.subdivisions = subdivision_index
    app.state.llm = llm_manager
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request: Request, error: RequestValidationError) -> Response:
        if request.url.path.startswith("/api/llm/"):
            return JSONResponse(status_code=422, content={
                "detail": "模型配置格式无效，请检查服务、地址、密钥、模型和配置版本。",
            })
        return await request_validation_exception_handler(request, error)

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
            spatial_locations=catalogue_index.spatial_coverage(),
            registered_areas=area_index.status(set(engine.by_id)),
            subdivisions=subdivision_index.status(),
            llm=llm_manager.public_config(),
        )

    @app.get("/api/llm/config", response_model=PublicConfig)
    def llm_config(request: Request) -> PublicConfig:
        _require_same_origin(request)
        return llm_manager.public_config()

    @app.post("/api/llm/models", response_model=ModelsResponse)
    def llm_models(request: Request, body: ConfigDraft) -> ModelsResponse:
        _require_same_origin(request)
        try:
            return llm_manager.discover(body)
        except ConfigInvalid as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        except LlmUnavailable as error:
            raise HTTPException(status_code=502, detail=str(error)) from None

    @app.post("/api/llm/config", response_model=PublicConfig)
    def apply_llm_config(request: Request, body: ConfigApply) -> PublicConfig:
        _require_same_origin(request)
        try:
            return llm_manager.apply(body)
        except ConfigConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except ConfigInvalid as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

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

    def catalogue_filters(
        request: Request, country: str | None, region: str | None, kind: str | None,
        subdivision: str | None = None,
    ) -> None:
        for name in ("country", "region", "type", "offset", "limit", "bbox", "subdivision"):
            if len(request.query_params.getlist(name)) > 1:
                raise HTTPException(status_code=422, detail=f"{name}参数不能重复。")
        try:
            catalogue_index.validate_filters(country, region, kind, subdivision)
        except SubdivisionUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/coverage", response_model=CoverageResponse)
    def coverage() -> CoverageResponse:
        return catalogue_index.coverage()

    @app.get("/api/subdivisions", response_model=SubdivisionFacetsResponse)
    def subdivision_facets(
        request: Request, country: str = Query(pattern=r"^[A-Z]{2}$"),
    ) -> SubdivisionFacetsResponse:
        catalogue_filters(request, country, None, None)
        return subdivision_index.facets(country, catalogue_index.country_counts[country])

    @app.get("/api/catalogue", response_model=CatalogueResponse)
    def catalogue_points(
        request: Request, country: str | None = None, region: str | None = None,
        type: str | None = None,
        subdivision: str | None = None,
    ) -> CatalogueResponse:
        catalogue_filters(request, country, region, type, subdivision)
        if "bbox" in request.query_params:
            raise HTTPException(status_code=422, detail="bbox仅用于/api/sites分页目录。")
        return catalogue_index.catalogue(country, region, type, subdivision)

    @app.get("/api/sites", response_model=SitePage)
    def browse_sites(
        request: Request, offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=100),
        country: str | None = None, region: str | None = None, type: str | None = None,
        bbox: str | None = Query(default=None, min_length=1, max_length=200),
        subdivision: str | None = None,
    ) -> SitePage:
        catalogue_filters(request, country, region, type, subdivision)
        try:
            bounds = SpatialBounds.from_csv(bbox) if bbox is not None else None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return catalogue_index.page(offset, limit, country, region, type, bounds, subdivision)

    @app.post("/api/search", response_model=SearchResponse)
    def search(body: SearchRequest, request: Request) -> SearchResponse:
        try:
            catalogue_index.validate_filters(body.country, body.region, body.type, body.subdivision)
        except SubdivisionUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        started = perf_counter()
        if body.mode == "semantic" and not index.ready:
            raise HTTPException(status_code=503, detail=index.reason or "本地语义模型尚未准备。")
        enhancement = None
        try:
            if body.enhance:
                _require_same_origin(request)
                assert body.llm_revision is not None
                try:
                    snapshot = llm_manager.snapshot(body.llm_revision)
                except ConfigConflict as error:
                    raise HTTPException(status_code=409, detail=str(error)) from None
                except ConfigInvalid as error:
                    raise HTTPException(status_code=503, detail=str(error)) from None
                llm_started = perf_counter()
                try:
                    queries = [body.query, *llm_manager.rewrite(body.query, snapshot)]
                except LlmUnavailable:
                    llm_elapsed = round((perf_counter() - llm_started) * 1000, 2)
                    hits, total = engine.search(body)
                    enhancement = SearchEnhancement(
                        applied=False, provider=snapshot.provider, model=snapshot.model,
                        queries=[body.query], elapsed_ms=llm_elapsed, ranking_method="original",
                        reason="LLM增强不可用，本次已按原查询检索。",
                    )
                else:
                    llm_elapsed = round((perf_counter() - llm_started) * 1000, 2)
                    hits, total = engine.search_expanded(body, queries)
                    enhancement = SearchEnhancement(
                        applied=True, provider=snapshot.provider, model=snapshot.model,
                        queries=queries, elapsed_ms=llm_elapsed, ranking_method="rrf",
                    )
            else:
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
            subdivision=body.subdivision,
            subdivision_version=subdivision_index.version if body.subdivision else None,
            enhancement=enhancement,
        )

    @app.get("/api/sites/{site_id}/subdivisions", response_model=SiteSubdivisionsResponse)
    def site_subdivisions(site_id: str) -> SiteSubdivisionsResponse:
        if site_id not in engine.by_id:
            raise HTTPException(status_code=404, detail="地点不存在于本演示语料中。")
        return subdivision_index.site_response(site_id)

    @app.get("/api/sites/{site_id}/locations", response_model=SiteLocationsResponse)
    def site_locations(site_id: str) -> SiteLocationsResponse:
        site = engine.by_id.get(site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="地点不存在于本演示语料中。")
        try:
            return catalogue_index.site_locations(site)
        except SpatialDataError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.get("/api/sites/{site_id}/areas", response_model=RegisteredAreasResponse)
    def site_areas(site_id: str) -> RegisteredAreasResponse:
        if site_id not in engine.by_id:
            raise HTTPException(status_code=404, detail="地点不存在于本演示语料中。")
        return area_index.response(site_id, CORPUS_VERSION)

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
