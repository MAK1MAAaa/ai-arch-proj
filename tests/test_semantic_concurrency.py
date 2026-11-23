"""Keep status and keyword searches independent of a busy semantic encoder."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Literal

import numpy as np
import pytest
from api_test_app import create_test_app
from fastapi.testclient import TestClient
from numpy.typing import NDArray
from test_index import unit_vectors, write_assets

from archsearch import index
from archsearch.domain import Site


@pytest.mark.parametrize("phase", ["load", "encode"])
def test_status_and_keyword_search_can_finish_while_semantic_search_is_busy(
    phase: Literal["load", "encode"],
    tmp_path: Path,
    sample_sites: list[Site],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = Event()
    release = Event()
    constructed: list[Path] = []

    def hold() -> None:
        entered.set()
        assert release.wait(timeout=15), "test did not release the encoder gate"

    class GatedEncoder:
        def __init__(self, model_dir: Path) -> None:
            constructed.append(model_dir)
            if phase == "load":
                hold()

        def encode(self, texts: list[str]) -> NDArray[np.float32]:
            if phase == "encode" and texts == [index.QUERY_PREFIX + "harbor"]:
                hold()
            return unit_vectors(len(texts))

    write_assets(tmp_path, sample_sites)
    monkeypatch.setattr(index, "LocalEncoder", GatedEncoder)
    app = create_test_app(tmp_path, sample_sites)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=3) as pool:
        if phase == "encode":
            warmup = client.post("/api/search", json={"query": "Eastern", "mode": "semantic"})
            assert warmup.status_code == 200
            assert constructed == [tmp_path / "model"]

        semantic = pool.submit(
            client.post, "/api/search", json={"query": "harbor", "mode": "semantic"},
        )
        try:
            assert entered.wait(timeout=5), "semantic search did not reach the encoder gate"
            status = pool.submit(client.get, "/api/status")
            keyword = pool.submit(
                client.post, "/api/search", json={"query": "Roman bath", "mode": "bm25"},
            )
            keyword_response = keyword.result(timeout=5)
            assert keyword_response.status_code == 200
            assert keyword_response.json()["results"][0]["site"]["id"] == "1"
            status_response = status.result(timeout=5)
            assert status_response.status_code == 200
            assert status_response.json()["semantic"]["ready"] is True
            assert status_response.json()["semantic"]["reason"] is None
            assert not semantic.done()
        finally:
            release.set()

        assert semantic.result(timeout=5).status_code == 200

    assert constructed == [tmp_path / "model"]
