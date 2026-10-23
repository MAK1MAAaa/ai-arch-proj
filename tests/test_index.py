"""Validate source-bound assets, failure states, and inference without network access."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from archsearch import index
from archsearch.config import MODEL_ID, MODEL_REVISION
from archsearch.corpus import build_document
from archsearch.domain import Site


def unit_vectors(rows: int) -> NDArray[np.float32]:
    return np.eye(rows, index.DIMENSIONS, dtype=np.float32)


def write_assets(home: Path, sites: list[Site]) -> None:
    model = home / "model"
    for name in index.REQUIRED_MODEL_FILES:
        path = model / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("fixture:" + name).encode())
    files = {
        name: {
            "sha256": hashlib.sha256((model / name).read_bytes()).hexdigest(),
            "size": (model / name).stat().st_size,
        }
        for name in index.REQUIRED_MODEL_FILES
    }
    marker = model / index.MODEL_MARKER
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model_id": MODEL_ID,
                "model_revision": MODEL_REVISION,
                "files": files,
            }
        ),
        encoding="utf-8",
    )
    target = home / "index"
    target.mkdir(parents=True, exist_ok=True)
    np.save(target / "embeddings.npy", unit_vectors(len(sites)), allow_pickle=False)
    manifest = index.document_contract(sites) | {
        "embeddings_sha256": index.sha256(target / "embeddings.npy"),
        "model_manifest_sha256": index.sha256(marker),
    }
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture(autouse=True)
def prohibit_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    import huggingface_hub

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("unit tests must not download a model")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", refuse)


@pytest.fixture
def prepared_home(tmp_path: Path, sample_sites: list[Site]) -> Path:
    write_assets(tmp_path, sample_sites)
    return tmp_path


def test_missing_assets_fail_closed_and_later_preparation_recovers(
    tmp_path: Path, sample_sites: list[Site]
) -> None:
    semantic = index.SemanticIndex(sample_sites, tmp_path)
    assert not semantic.ready
    with pytest.raises(index.IndexUnavailable):
        semantic.scores("harbor")
    write_assets(tmp_path, sample_sites)
    assert semantic.ready
    assert semantic.reason is None


def test_file_deletion_creation_and_corruption_refresh_status(
    prepared_home: Path, sample_sites: list[Site]
) -> None:
    semantic = index.SemanticIndex(sample_sites, prepared_home)
    assert semantic.ready
    path = prepared_home / "model" / "tokenizer.json"
    original = path.read_bytes()
    path.unlink()
    assert not semantic.ready
    assert semantic.vectors is None
    path.write_bytes(original)
    assert semantic.ready
    path.write_bytes(b"corrupted model content")
    assert not semantic.ready
    path.write_bytes(original)
    assert semantic.ready


@pytest.mark.parametrize(
    "field", ["model_revision", "documents_sha256", "site_ids", "query_prefix"]
)
def test_manifest_mismatch_rejects_index(
    prepared_home: Path, sample_sites: list[Site], field: str
) -> None:
    path = prepared_home / "index" / "manifest.json"
    manifest = json.loads(path.read_text("utf-8"))
    manifest[field] = "wrong"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    semantic = index.SemanticIndex(sample_sites, prepared_home)
    assert not semantic.ready
    assert semantic.reason is not None


def test_embedding_corruption_is_rejected_on_existing_instance(
    prepared_home: Path, sample_sites: list[Site]
) -> None:
    semantic = index.SemanticIndex(sample_sites, prepared_home)
    assert semantic.ready
    with (prepared_home / "index" / "embeddings.npy").open("ab") as stream:
        stream.write(b"corruption")
    assert not semantic.ready
    assert semantic.vectors is None


@pytest.mark.parametrize("fault", ["dimension", "dtype", "normalization", "nan"])
def test_invalid_vector_contract_is_rejected_even_with_matching_checksum(
    prepared_home: Path, sample_sites: list[Site], fault: str
) -> None:
    vectors: NDArray[Any] = unit_vectors(len(sample_sites))
    if fault == "dimension":
        vectors = vectors[:, :2]
    elif fault == "dtype":
        vectors = vectors.astype(np.float64)
    elif fault == "normalization":
        vectors *= 2
    else:
        vectors[0, 0] = np.nan
    path = prepared_home / "index" / "embeddings.npy"
    np.save(path, vectors, allow_pickle=False)
    metadata = path.with_name("manifest.json")
    manifest = json.loads(metadata.read_text("utf-8"))
    manifest["embeddings_sha256"] = index.sha256(path)
    metadata.write_text(json.dumps(manifest), encoding="utf-8")
    assert not index.SemanticIndex(sample_sites, prepared_home).ready


def test_query_prefix_encoder_reuse_and_failure_invalidation(
    prepared_home: Path, sample_sites: list[Site], monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[Path] = []
    calls: list[list[str]] = []

    class FakeEncoder:
        def __init__(self, model_dir: Path) -> None:
            created.append(model_dir)

        def encode(self, texts: list[str]) -> NDArray[np.float32]:
            calls.append(texts)
            if texts[0].endswith("fail"):
                raise RuntimeError("fake encoder failure")
            return unit_vectors(len(texts))

    monkeypatch.setattr(index, "LocalEncoder", FakeEncoder)
    semantic = index.SemanticIndex(sample_sites, prepared_home)
    with ThreadPoolExecutor(max_workers=4) as executor:
        scores = list(executor.map(semantic.scores, ["港口"] * 8))
    assert len(created) == 1
    assert calls == [["query: 港口"]] * 8
    assert all(np.array_equal(value, [1, 0, 0]) for value in scores)
    with pytest.raises(index.IndexUnavailable, match="编码失败"):
        semantic.scores("fail")
    assert not semantic.ready
    assert semantic.encoder is None


def test_prepare_uses_fixed_snapshot_passage_prefix_and_reuses_valid_model(
    tmp_path: Path, sample_sites: list[Site], monkeypatch: pytest.MonkeyPatch
) -> None:
    import huggingface_hub

    downloads: list[dict[str, Any]] = []
    calls: list[list[str]] = []

    def fake_download(**kwargs: Any) -> None:
        downloads.append(kwargs)
        model = Path(kwargs["local_dir"])
        for name in index.REQUIRED_MODEL_FILES:
            path = model / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("fixture:" + name).encode())

    class FakeEncoder:
        def __init__(self, model_dir: Path) -> None:
            pass

        def encode(self, texts: list[str]) -> NDArray[np.float32]:
            calls.append(texts)
            return unit_vectors(len(texts))

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_download)
    monkeypatch.setattr(index, "LocalEncoder", FakeEncoder)
    manifest = index.prepare_index(sample_sites, tmp_path)
    assert downloads[0]["repo_id"] == MODEL_ID
    assert downloads[0]["revision"] == MODEL_REVISION
    assert calls[0] == ["passage: " + build_document(site) for site in sample_sites]
    assert manifest["normalized"] is True
    assert manifest["dimensions"] == 384
    assert index.SemanticIndex(sample_sites, tmp_path).ready
    index.prepare_index(sample_sites, tmp_path)
    assert len(downloads) == 1


def test_local_encoder_is_cpu_local_only_normalized_and_serialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructor: dict[str, Any] = {}
    arguments: list[dict[str, Any]] = []
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    class FakeTransformer:
        def __init__(self, path: str, **kwargs: Any) -> None:
            constructor.update(path=path, **kwargs)
            self.max_seq_length = 0

        def encode(self, texts: list[str], **kwargs: Any) -> NDArray[np.float32]:
            nonlocal active, maximum_active
            arguments.append(kwargs)
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.005)
            with state_lock:
                active -= 1
            return unit_vectors(len(texts))

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=FakeTransformer),
    )
    encoder = index.LocalEncoder(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(encoder.encode, [["query: 港口"]] * 8))
    assert constructor == {
        "path": str(tmp_path),
        "device": "cpu",
        "local_files_only": True,
        "trust_remote_code": False,
    }
    assert encoder.model.max_seq_length == 512
    assert maximum_active == 1
    assert all(item["normalize_embeddings"] is True for item in arguments)
