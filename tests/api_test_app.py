"""Assemble HTTP contract tests with synthetic geography and real app routes."""

from pathlib import Path

import pytest
from fastapi import FastAPI

from archsearch import coverage
from archsearch.api import create_app
from archsearch.corpus import CORPUS_VERSION
from archsearch.domain import Site
from archsearch.history import HistoryStore
from archsearch.index import SemanticIndex
from archsearch.llm import LlmManager
from archsearch.registered_areas import RegisteredAreasIndex
from archsearch.subdivisions import SubdivisionIndex


def create_test_app(
    home: Path,
    sites: list[Site],
    *,
    semantic: SemanticIndex | None = None,
    history: HistoryStore | None = None,
    llm: LlmManager | None = None,
) -> FastAPI:
    """Build a fresh app per test without loading sidecars for unrelated sites."""
    data_dir = home / "fixture-geography"
    data_dir.mkdir(exist_ok=True)
    registry = coverage.CoverageRegistry(
        countries={"CN": "中国", "JP": "日本"},
        regions={"asia-pacific": "亚太地区", "arab-states": "阿拉伯国家"},
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(coverage, "load_registry", lambda: registry)
        return create_app(
            home=home,
            sites=sites,
            semantic=semantic,
            history=history,
            areas=RegisteredAreasIndex(data_dir),
            subdivisions=SubdivisionIndex(sites, CORPUS_VERSION, data_dir),
            llm=llm,
        )
