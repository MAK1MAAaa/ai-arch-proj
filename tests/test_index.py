"""Validate source-bound assets, failure states, and inference without network access."""

from __future__ import annotations

import hashlib
import json
import os
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


def write_assets(
    home: Path, sites: list[Site], *,
    tag: str = "fixture", vectors: NDArray[np.float32] | None = None,
) -> None:
    model = home / "model"
    for name in index.REQUIRED_MODEL_FILES:
        path = model / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{tag}:{name}".encode())
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
    embeddings = unit_vectors(len(sites)) if vectors is None else vectors
    np.save(target / "embeddings.npy", embeddings, allow_pickle=False)
    manifest = index.document_contract(sites) | {
        "embeddings_sha256": index.sha256(target / "embeddings.npy"),
        "model_manifest_sha256": index.sha256(marker),
    }
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def prepare_next_generation(home: Path, sites: list[Site]) -> Path:
    replacement = home / "replacement"
    # Revision B also maps the query to axis 1. Crossing generations would therefore select row 1.
    write_assets(replacement, sites, tag="replacement", vectors=unit_vectors(len(sites))[[1, 0, 2]])
    directory = replacement / "index"
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    filename = f"embeddings-{manifest['embeddings_sha256']}.npy"
    (directory / "embeddings.npy").replace(directory / filename)
    manifest["embeddings_file"] = filename
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return replacement


def publish_next_generation(replacement: Path, home: Path) -> None:
    for filename in (*index.REQUIRED_MODEL_FILES, index.MODEL_MARKER):
        (replacement / "model" / filename).replace(home / "model" / filename)
    manifest = json.loads((replacement / "index" / "manifest.json").read_text("utf-8"))
    for filename in (manifest["embeddings_file"], "manifest.json"):
        (replacement / "index" / filename).replace(home / "index" / filename)


def encoder_axis(model_dir: Path) -> int:
    return int((model_dir / "tokenizer.json").read_bytes() == b"replacement:tokenizer.json")


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


def test_content_addressed_vectors_are_validated_and_tracked_by_status(
    prepared_home: Path, sample_sites: list[Site],
) -> None:
    directory = prepared_home / "index"
    meta_path = directory / "manifest.json"
    manifest = json.loads(meta_path.read_text("utf-8"))
    manifest["embeddings_file"] = f"embeddings-{manifest['embeddings_sha256']}.npy"
    original = (directory / "embeddings.npy").read_bytes()
    vectors = directory / manifest["embeddings_file"]
    vectors.write_bytes(original)
    meta_path.write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "embeddings.npy").unlink()

    semantic = index.SemanticIndex(sample_sites, prepared_home)
    assert semantic.status() == (True, None)
    vectors.write_bytes(original + b"unsafe bytes")
    assert not semantic.ready
    vectors.write_bytes(original)
    assert semantic.status() == (True, None)


@pytest.mark.parametrize("reference", [
    "../embeddings-{digest}.npy",
    "..\\embeddings-{digest}.npy",
    "embeddings-" + "0" * 64 + ".npy",
    "embeddings.npy",
    None,
])
def test_embedding_pointer_rejects_escape_and_nonmatching_sha_filename(
    prepared_home: Path, sample_sites: list[Site], reference: str | None,
) -> None:
    directory = prepared_home / "index"
    meta_path = directory / "manifest.json"
    manifest = json.loads(meta_path.read_text("utf-8"))
    legacy = directory / "embeddings.npy"
    if reference is None:
        manifest["embeddings_file"] = None
    else:
        filename = reference.format(digest=manifest["embeddings_sha256"])
        manifest["embeddings_file"] = filename
        target = directory / filename
        if target != legacy:
            target.write_bytes(legacy.read_bytes())
        assert index.sha256(target) == manifest["embeddings_sha256"]
    meta_path.write_text(json.dumps(manifest), encoding="utf-8")
    semantic = index.SemanticIndex(sample_sites, prepared_home)
    assert not semantic.ready and semantic.reason is not None


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


def test_cold_load_cannot_use_a_new_encoder_with_previous_vectors(
    prepared_home: Path, sample_sites: list[Site], monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacement = prepare_next_generation(prepared_home, sample_sites)
    loading = threading.Event()
    allow_load = threading.Event()
    loaded_axes: list[int] = []
    encoded_axes: list[int] = []

    class GatedEncoder:
        def __init__(self, model_dir: Path) -> None:
            if not loaded_axes:
                loading.set()
                assert allow_load.wait(5), "load was not released"
            self.axis = encoder_axis(model_dir)
            loaded_axes.append(self.axis)

        def encode(self, texts: list[str]) -> NDArray[np.float32]:
            assert len(texts) == 1
            encoded_axes.append(self.axis)
            return unit_vectors(2)[[self.axis]]

    monkeypatch.setattr(index, "LocalEncoder", GatedEncoder)
    semantic = index.SemanticIndex(sample_sites, prepared_home)
    with ThreadPoolExecutor(max_workers=1) as executor:
        request = executor.submit(semantic.scores, "港口")
        try:
            assert loading.wait(5), "cold model load did not start"
            publish_next_generation(replacement, prepared_home)
        finally:
            allow_load.set()
        with pytest.raises(index.IndexUnavailable, match="更新|重试"):
            request.result(timeout=5)
    assert loaded_axes == [1]
    assert encoded_axes == []
    assert semantic.ready and semantic.reason is None
    assert np.array_equal(semantic.scores("港口"), [1, 0, 0])
    assert loaded_axes == [1, 1]
    assert encoded_axes == [1]


@pytest.mark.parametrize("failure_stage", ["construction", "encoding"])
def test_previous_encoder_failure_does_not_invalidate_replacement_generation(
    prepared_home: Path, sample_sites: list[Site], monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    replacement = prepare_next_generation(prepared_home, sample_sites)
    failing = threading.Event()
    allow_failure = threading.Event()

    def fail_previous_generation() -> None:
        failing.set()
        assert allow_failure.wait(10), "failure was not released"
        raise RuntimeError("simulated failure of the retired generation")

    class OldFailingEncoder:
        def __init__(self, model_dir: Path) -> None:
            self.axis = encoder_axis(model_dir)
            if self.axis == 0 and failure_stage == "construction":
                fail_previous_generation()

        def encode(self, texts: list[str]) -> NDArray[np.float32]:
            if self.axis == 0 and failure_stage == "encoding" and texts[0].endswith("fail"):
                fail_previous_generation()
            return unit_vectors(2)[[self.axis]]

    monkeypatch.setattr(index, "LocalEncoder", OldFailingEncoder)
    semantic = index.SemanticIndex(sample_sites, prepared_home)
    if failure_stage == "encoding":
        assert np.array_equal(semantic.scores("warm"), [1, 0, 0])
    with ThreadPoolExecutor(max_workers=2) as executor:
        request = executor.submit(semantic.scores, "fail")
        try:
            assert failing.wait(5), "the previous generation did not reach its failure"
            publish_next_generation(replacement, prepared_home)
            refreshed = executor.submit(lambda: semantic.ready)
            assert refreshed.result(timeout=5), "replacement was blocked by the retired request"
        finally:
            allow_failure.set()
        with pytest.raises(index.IndexUnavailable):
            request.result(timeout=5)
    assert semantic.ready and semantic.reason is None
    assert np.array_equal(semantic.scores("港口"), [1, 0, 0])


def test_scores_many_never_publishes_a_batch_across_resource_generations(
    prepared_home: Path, sample_sites: list[Site], monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacement = prepare_next_generation(prepared_home, sample_sites)
    encoding = threading.Event()
    allow_encode = threading.Event()
    calls: list[tuple[int, str]] = []

    class GatedEncoder:
        def __init__(self, model_dir: Path) -> None:
            self.axis = encoder_axis(model_dir)

        def encode(self, texts: list[str]) -> NDArray[np.float32]:
            assert len(texts) == 1, "query encoding remains per query"
            calls.append((self.axis, texts[0]))
            if self.axis == 0 and texts[0] == "query: 港口":
                encoding.set()
                assert allow_encode.wait(5), "encoding was not released"
            return unit_vectors(2)[[self.axis]]

    monkeypatch.setattr(index, "LocalEncoder", GatedEncoder)
    semantic = index.SemanticIndex(sample_sites, prepared_home)
    with ThreadPoolExecutor(max_workers=1) as executor:
        request = executor.submit(semantic.scores_many, ["港口", "浴场"])
        try:
            assert encoding.wait(5), "the first query did not reach the encoder"
            publish_next_generation(replacement, prepared_home)
        finally:
            allow_encode.set()
        with pytest.raises(index.IndexUnavailable, match="更新|重试"):
            request.result(timeout=5)
    assert calls[0] == (0, "query: 港口")
    assert all(axis == 0 for axis, _ in calls)
    assert semantic.status() == (True, None)

    updated = semantic.scores_many(["港口", "浴场"])
    assert len(updated) == 2 and all(np.array_equal(scores, [1, 0, 0]) for scores in updated)
    assert calls[-2:] == [(1, "query: 港口"), (1, "query: 浴场")]


def test_parallel_prepare_writers_finish_with_a_coherent_generation(
    prepared_home: Path, sample_sites: list[Site], monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoding_first = threading.Event()
    started_second = threading.Event()
    encoding_second = threading.Event()
    allow_first = threading.Event()

    class GatedPrepareEncoder:
        def __init__(self, model_dir: Path) -> None:
            pass

        def encode(self, texts: list[str]) -> NDArray[np.float32]:
            vectors = unit_vectors(len(texts))
            if not encoding_first.is_set():
                encoding_first.set()
                assert allow_first.wait(5), "the first writer was not released"
                return vectors
            encoding_second.set()
            return vectors[[1, 0, 2]]

    def prepare_second() -> dict[str, Any]:
        started_second.set()
        return index.prepare_index(sample_sites, prepared_home)

    monkeypatch.setattr(index, "LocalEncoder", GatedPrepareEncoder)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(index.prepare_index, sample_sites, prepared_home)
        try:
            assert encoding_first.wait(5), "the first writer did not start"
            second = executor.submit(prepare_second)
            assert started_second.wait(5), "the second writer did not start"
            assert not encoding_second.wait(0.25), "writers must serialize in one home"
        finally:
            allow_first.set()
        first_manifest = first.result(timeout=5)
        second_manifest = second.result(timeout=5)

    assert encoding_second.is_set()
    assert first_manifest["embeddings_sha256"] != second_manifest["embeddings_sha256"]
    directory = prepared_home / "index"
    assert json.loads((directory / "manifest.json").read_text("utf-8")) == second_manifest
    assert index.sha256(directory / second_manifest["embeddings_file"]) == (
        second_manifest["embeddings_sha256"]
    )
    assert index.SemanticIndex(sample_sites, prepared_home).ready


@pytest.mark.parametrize("legacy_manifest", [True, False])
def test_prepare_manifest_replace_failure_keeps_the_previous_index(
    prepared_home: Path, sample_sites: list[Site], monkeypatch: pytest.MonkeyPatch,
    legacy_manifest: bool,
) -> None:
    index_dir = prepared_home / "index"
    manifest_path = index_dir / "manifest.json"
    seen_new_digests: list[str] = []
    replace = os.replace
    changed_documents = False

    class OfflineEncoder:
        def __init__(self, model_dir: Path) -> None:
            pass

        def encode(self, texts: list[str]) -> NDArray[np.float32]:
            vectors = unit_vectors(len(texts))
            if changed_documents and len(texts) > 1:
                return vectors[[1, 0, 2]]
            return vectors

    def reject_manifest_publish(source: Path, destination: Path, **options: Any) -> None:
        if Path(destination) == manifest_path and not seen_new_digests:
            next_manifest = json.loads(Path(source).read_text("utf-8"))
            next_vectors = index_dir / next_manifest["embeddings_file"]
            seen_new_digests.append(index.sha256(next_vectors))
            assert seen_new_digests[0] == next_manifest["embeddings_sha256"]
            raise PermissionError("simulated failure replacing the published manifest")
        replace(source, destination, **options)

    monkeypatch.setattr(index, "LocalEncoder", OfflineEncoder)
    if not legacy_manifest:
        index.prepare_index(sample_sites, prepared_home)
    previous_manifest = manifest_path.read_bytes()
    metadata = json.loads(previous_manifest)
    vectors_path = index_dir / metadata.get("embeddings_file", "embeddings.npy")
    previous_vectors = vectors_path.read_bytes()
    previous_digest = index.sha256(vectors_path)

    changed_documents = True
    monkeypatch.setattr(os, "replace", reject_manifest_publish)
    with vectors_path.open("rb") as previous_reader:
        with pytest.raises((OSError, index.IndexUnavailable)):
            index.prepare_index(sample_sites, prepared_home)
        assert previous_reader.read() == previous_vectors

    assert len(seen_new_digests) == 1 and seen_new_digests[0] != previous_digest
    assert manifest_path.read_bytes() == previous_manifest
    assert vectors_path.read_bytes() == previous_vectors
    saved = index.SemanticIndex(sample_sites, prepared_home)
    assert saved.status() == (True, None)
    assert np.array_equal(saved.scores("港口"), [1, 0, 0])


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
    name = f"embeddings-{manifest['embeddings_sha256']}.npy"
    directory = tmp_path / "index"
    assert manifest["embeddings_file"] == name
    assert json.loads((directory / "manifest.json").read_text("utf-8")) == manifest
    assert index.sha256(directory / name) == manifest["embeddings_sha256"]
    assert index.SemanticIndex(sample_sites, tmp_path).ready
    with (directory / name).open("rb") as reader:
        assert index.prepare_index(sample_sites, tmp_path) == manifest
        assert hashlib.sha256(reader.read()).hexdigest() == manifest["embeddings_sha256"]
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
