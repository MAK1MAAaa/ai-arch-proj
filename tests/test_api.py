from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from archsearch.api import create_app
from archsearch.corpus import CORPUS_VERSION
from archsearch.domain import Site
from archsearch.history import HistoryStore, HistoryUnavailable
from archsearch.index import IndexUnavailable, SemanticIndex


@pytest.fixture
def client(tmp_path: Path, sample_sites: list[Site]) -> TestClient:
    return TestClient(create_app(home=tmp_path, sites=sample_sites))


def test_offline_status_and_bm25_without_model(
    client: TestClient, sample_sites: list[Site]
) -> None:
    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["semantic"]["ready"] is False
    assert status.json()["corpus"]["count"] == 3
    assert "prepare" in status.json()["semantic"]["reason"]
    assert status.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in status.headers["content-security-policy"]
    assert status.json()["history"]["ready"] is False
    assert "prepare-history" in status.json()["history"]["reason"]
    site = sample_sites[0]
    result = client.post("/api/search", json={"query": site.title, "mode": "bm25"})
    assert result.status_code == 200
    assert any(hit["site"]["id"] == site.id for hit in result.json()["results"])
    assert result.json()["corpus_version"] == CORPUS_VERSION
    assert client.get(f"/api/sites/{site.id}").json()["repr_point"] == list(site.repr_point)
    assert client.get("/api/sites/not-a-place").status_code == 404


def test_semantic_missing_is_explicit_and_does_not_fall_back(client: TestClient) -> None:
    response = client.post("/api/search", json={"query": "罗马港口"})
    assert response.status_code == 503
    assert "prepare" in response.json()["detail"]
    assert (
        client.post("/api/search", json={"query": "xyznevermatch987654", "mode": "bm25"}).json()[
            "results"
        ]
        == []
    )


@pytest.mark.parametrize(
    "body",
    [
        {"query": "   "},
        {"query": "x" * 501},
        {"query": "port", "limit": 51},
        {"query": "port", "limit": 0},
        {"query": "port", "mode": "invented"},
        {"query": "port", "type": "unknown"},
        {"query": "port", "unexpected": True},
    ],
)
def test_invalid_search(client: TestClient, body: dict[str, object]) -> None:
    assert client.post("/api/search", json=body).status_code == 422


def test_semantic_ranking_uses_query_and_returns_source_evidence(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    sites = sample_sites
    semantic = Mock(spec=SemanticIndex)
    semantic.sites = sites
    semantic.ready = True
    semantic.reason = None
    semantic.scores.return_value = np.asarray([0.1, 0.9, 0.3], dtype=np.float32)
    with TestClient(create_app(home=tmp_path, sites=sites, semantic=semantic)) as client:
        response = client.post("/api/search", json={"query": "  港口  ", "limit": 2})
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "港口"
        assert [hit["site"]["id"] for hit in data["results"]] == [sites[1].id, sites[2].id]
        assert data["results"][0]["site"]["period_evidence"]
        semantic.scores.assert_called_once_with("港口")
        assert client.get("/api/facets").json()["types"]
        semantic.scores.side_effect = IndexUnavailable("模型损坏")
        failed = client.post("/api/search", json={"query": "港口"})
        assert failed.status_code == 503
        assert failed.json()["detail"] == "模型损坏"


def historical_store() -> Mock:
    store = Mock(spec=HistoryStore)
    store.status.return_value = {
        "ready": True,
        "reason": None,
        "version": "v0.2.1",
        "min_year": -3400,
        "max_year": 2024,
        "change_years": [-3400, 117, 127],
        "feature_count": 1,
        "counts": {"features": 1},
        "source": {"name": "Cliopatria", "license": "CC BY 4.0"},
        "normalization": {"years": "no year zero"},
    }
    store.boundaries.side_effect = lambda year: (
        {
            "type": "FeatureCollection",
            "features": [],
            "metadata": {
                "year": year,
                "valid_from": year,
                "valid_to": year,
                "frame_id": f"frame-{year}",
                "source": {"version": "v0.2.1"},
            },
        },
        f'"fixture-{year}"',
    )
    return store


def test_history_status_and_year_frame_are_independent_of_semantic_model(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    history = historical_store()
    with TestClient(create_app(home=tmp_path, sites=sample_sites, history=history)) as client:
        status = client.get("/api/status").json()
        assert status["semantic"]["ready"] is False and status["history"]["ready"] is True
        assert status["history"]["version"] == "v0.2.1"
        assert status["history"]["change_years"] == [-3400, 117, 127]
        for year in (-3400, -1, 1, 117, 2024):
            response = client.get(f"/api/history/boundaries?year={year}")
            assert response.status_code == 200
            assert response.json()["metadata"]["year"] == year
            assert response.headers["content-type"].startswith("application/geo+json")
            assert response.headers["cache-control"] == "private, no-cache"
            assert response.headers["vary"] == "Accept-Encoding"
        assert client.get("/api/status").headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "?year=0",
        "?year=-3401",
        "?year=2025",
        "?year=117.0",
        "?year=1e2",
        "?year=true",
        "?year=%2B117",
        "?year=0117",
        "?year=%20117",
        "?year=117&year=118",
    ],
)
def test_history_year_is_strict_and_validated_before_store_access(
    tmp_path: Path,
    sample_sites: list[Site],
    suffix: str,
) -> None:
    history = historical_store()
    with TestClient(create_app(home=tmp_path, sites=sample_sites, history=history)) as client:
        response = client.get("/api/history/boundaries" + suffix)
        assert response.status_code == 422
        assert response.headers["cache-control"] == "no-store"
    history.boundaries.assert_not_called()


@pytest.mark.parametrize(
    "conditional",
    [
        'W/"fixture-117"',
        '"fixture-117"',
        '"unrelated", W/"fixture-117"',
        "*",
    ],
)
def test_history_conditional_get_has_empty_304_and_security_headers(
    tmp_path: Path,
    sample_sites: list[Site],
    conditional: str,
) -> None:
    with TestClient(
        create_app(home=tmp_path, sites=sample_sites, history=historical_store())
    ) as client:
        response = client.get(
            "/api/history/boundaries?year=117", headers={"If-None-Match": conditional}
        )
        assert response.status_code == 304 and response.content == b""
        assert response.headers["etag"] == 'W/"fixture-117"'
        assert response.headers["cache-control"] == "private, no-cache"
        assert response.headers["vary"] == "Accept-Encoding"
        assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "conditional", ['"unrelated"', 'W/"fixture-127"', "broken", '* , "fixture-117"']
)
def test_history_cache_miss_and_malformed_conditions_return_full_frame(
    tmp_path: Path,
    sample_sites: list[Site],
    conditional: str,
) -> None:
    with TestClient(
        create_app(home=tmp_path, sites=sample_sites, history=historical_store())
    ) as client:
        response = client.get(
            "/api/history/boundaries?year=117", headers={"If-None-Match": conditional}
        )
        assert response.status_code == 200
        assert response.json()["metadata"]["year"] == 117


def test_large_history_json_is_gzipped_with_semantic_etag(
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    history = historical_store()
    frame, etag = history.boundaries(117)
    frame["source_fixture_description"] = "历史资料" * 1000
    history.boundaries.side_effect = None
    history.boundaries.return_value = frame, etag
    with TestClient(create_app(home=tmp_path, sites=sample_sites, history=history)) as client:
        compressed = client.get(
            "/api/history/boundaries?year=117", headers={"Accept-Encoding": "gzip"}
        )
        identity = client.get(
            "/api/history/boundaries?year=117", headers={"Accept-Encoding": "identity"}
        )
        assert compressed.headers["content-encoding"] == "gzip"
        assert "content-encoding" not in identity.headers
        assert compressed.json() == identity.json() == frame
        assert compressed.headers["etag"] == identity.headers["etag"] == 'W/"fixture-117"'
        assert compressed.headers["vary"] == "Accept-Encoding"


def test_unprepared_and_corrupt_history_return_503_with_prepare_guidance(
    client: TestClient,
    tmp_path: Path,
    sample_sites: list[Site],
) -> None:
    response = client.get("/api/history/boundaries?year=117", headers={"If-None-Match": "*"})
    assert response.status_code == 503
    assert "prepare-history" in response.json()["detail"]
    assert response.headers["cache-control"] == "no-store" and "etag" not in response.headers
    history = historical_store()
    history.boundaries.side_effect = HistoryUnavailable("历史记录校验失败")
    with TestClient(create_app(home=tmp_path, sites=sample_sites, history=history)) as broken:
        response = broken.get("/api/history/boundaries?year=117")
        assert response.status_code == 503
        assert "校验失败" in response.json()["detail"]
        assert "prepare-history" in response.json()["detail"]
        assert response.headers["cache-control"] == "no-store"
