from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from archsearch.api import create_app
from archsearch.corpus import load_corpus
from archsearch.index import IndexUnavailable, SemanticIndex


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(home=tmp_path, sites=load_corpus()[:3]))


def test_offline_status_and_bm25_without_model(client: TestClient) -> None:
    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["semantic"]["ready"] is False
    assert status.json()["corpus"]["count"] == 3
    assert "prepare" in status.json()["semantic"]["reason"]
    assert status.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in status.headers["content-security-policy"]
    site = load_corpus()[0]
    result = client.post("/api/search", json={"query": site.title, "mode": "bm25"})
    assert result.status_code == 200
    assert any(hit["site"]["id"] == site.id for hit in result.json()["results"])
    assert result.json()["corpus_version"] == "global-v2"
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


def test_semantic_ranking_uses_query_and_returns_source_evidence(tmp_path: Path) -> None:
    sites = load_corpus()[:3]
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
