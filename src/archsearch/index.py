"""Version-bound local E5 preparation and inference; serving never downloads assets."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from archsearch.config import DEFAULT_HOME, MODEL_ID, MODEL_REVISION, TEXT_VERSION
from archsearch.corpus import build_document
from archsearch.domain import Site

DIMENSIONS = 384
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
REQUIRED_MODEL_FILES = (
    "model.safetensors",
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "sentencepiece.bpe.model",
    "modules.json",
    "sentence_bert_config.json",
    "1_Pooling/config.json",
)
MODEL_MARKER = "archsearch-model.json"
_RESOURCE_ERRORS = (OSError, ValueError, KeyError, TypeError, IndexError, EOFError)


class IndexUnavailable(RuntimeError):
    """Local semantic resources require preparation or repair."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def document_contract(sites: list[Site]) -> dict[str, Any]:
    documents = [build_document(site) for site in sites]
    return {
        "schema_version": 1,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "text_version": TEXT_VERSION,
        "dimensions": DIMENSIONS,
        "query_prefix": QUERY_PREFIX,
        "passage_prefix": PASSAGE_PREFIX,
        "normalized": True,
        "site_ids": [site.id for site in sites],
        "documents_sha256": hashlib.sha256(
            json.dumps(documents, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }


def _model_manifest(model_dir: Path) -> dict[str, Any]:
    if any((model_dir / filename).stat().st_size == 0 for filename in REQUIRED_MODEL_FILES):
        raise IndexUnavailable("本地模型包含空文件。")
    return {
        "schema_version": 1,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "files": {
            filename: {
                "sha256": sha256(model_dir / filename),
                "size": (model_dir / filename).stat().st_size,
            }
            for filename in REQUIRED_MODEL_FILES
        },
    }


def _validate_model(model_dir: Path) -> None:
    meta = json.loads((model_dir / MODEL_MARKER).read_text("utf-8"))
    if not isinstance(meta, dict) or meta != _model_manifest(model_dir):
        raise IndexUnavailable("本地模型文件校验或固定版本检查失败。")


def _validate_vectors(vectors: NDArray[Any], rows: int) -> NDArray[np.float32]:
    if vectors.shape != (rows, DIMENSIONS) or vectors.dtype != np.float32:
        raise IndexUnavailable("向量形状或类型无效。")
    if not np.isfinite(vectors).all() or not np.allclose(
        np.linalg.norm(vectors, axis=1), 1, atol=1e-3
    ):
        raise IndexUnavailable("向量未归一化或包含非有限数值。")
    return np.asarray(vectors, dtype=np.float32)


class LocalEncoder:
    """One CPU encoder whose inference calls are serialized across request threads."""

    def __init__(self, model_dir: Path) -> None:
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(
            str(model_dir), device="cpu", local_files_only=True, trust_remote_code=False
        )
        self.model.max_seq_length = 512
        self.lock = threading.Lock()

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        with self.lock:
            vectors = np.asarray(
                self.model.encode(
                    texts,
                    batch_size=32,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                ),
                dtype=np.float32,
            )
        return _validate_vectors(vectors, len(texts))


def prepare_index(sites: list[Site], home: Path = DEFAULT_HOME) -> dict[str, Any]:
    """Download a fixed snapshot explicitly, then publish its validated local index."""
    home = Path(home)
    model_dir = home / "model"
    index_dir = home / "index"
    model_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    marker = model_dir / MODEL_MARKER
    try:
        _validate_model(model_dir)
    except (*_RESOURCE_ERRORS, IndexUnavailable):
        from huggingface_hub import snapshot_download

        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        snapshot_download(
            repo_id=MODEL_ID,
            revision=MODEL_REVISION,
            local_dir=str(model_dir),
            force_download=marker.exists(),
            allow_patterns=[
                "*.json",
                "model.safetensors",
                "sentencepiece.bpe.model",
                "1_Pooling/*",
                "README.md",
                "LICENSE",
            ],
        )
        model_meta = _model_manifest(model_dir)

        marker_temp = model_dir / (MODEL_MARKER + ".tmp")
        marker_temp.write_text(json.dumps(model_meta, sort_keys=True), "utf-8")
        marker_temp.replace(marker)
    encoder = LocalEncoder(model_dir)
    vectors = _validate_vectors(
        encoder.encode([PASSAGE_PREFIX + build_document(site) for site in sites]), len(sites)
    )
    temporary = index_dir / "embeddings.tmp"
    with temporary.open("wb") as stream:
        np.save(stream, vectors, allow_pickle=False)
    embeddings_hash = sha256(temporary)
    manifest = document_contract(sites) | {
        "embeddings_sha256": embeddings_hash,
        "model_manifest_sha256": sha256(marker),
    }
    temporary_meta = index_dir / "manifest.tmp"
    temporary_meta.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    temporary.replace(index_dir / "embeddings.npy")
    temporary_meta.replace(index_dir / "manifest.json")
    return manifest


class SemanticIndex:
    def __init__(self, sites: list[Site], home: Path = DEFAULT_HOME) -> None:
        self.sites = list(sites)
        self.home = Path(home)
        self.vectors: NDArray[np.float32] | None = None
        self.encoder: LocalEncoder | None = None
        self.load_lock = threading.RLock()
        self.reason: str | None = None
        self._signature: tuple[tuple[str, int, int, int] | tuple[str], ...] | None = None
        self._refresh()

    def _resource_signature(self) -> tuple[tuple[str, int, int, int] | tuple[str], ...]:
        paths = [
            *(self.home / "model" / filename for filename in REQUIRED_MODEL_FILES),
            self.home / "model" / MODEL_MARKER,
            self.home / "index" / "manifest.json",
            self.home / "index" / "embeddings.npy",
        ]
        signature: list[tuple[str, int, int, int] | tuple[str]] = []
        for path in paths:
            try:
                stat = path.stat()
                signature.append((str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino))
            except OSError:
                signature.append((str(path),))
        return tuple(signature)

    def _refresh(self) -> None:
        with self.load_lock:
            signature = self._resource_signature()
            if signature == self._signature:
                return
            self.encoder = None
            self.vectors = None
            self.reason = None
            try:
                self._validate()
            except (*_RESOURCE_ERRORS, IndexUnavailable) as error:
                self.reason = f"{error} 请运行 uv run archsearch prepare 修复本地模型和索引。"
                self.vectors = None
            self._signature = signature
            if signature != self._resource_signature():
                self.reason = "本地模型或索引正在更新，请稍后重试。"
                self.vectors = None
                self._signature = None

    def _validate(self) -> None:
        model_dir = self.home / "model"
        _validate_model(model_dir)
        index_dir = self.home / "index"
        meta = json.loads((index_dir / "manifest.json").read_text("utf-8"))
        if not isinstance(meta, dict):
            raise IndexUnavailable("索引清单格式无效。")
        for key, value in document_contract(self.sites).items():
            if meta.get(key) != value:
                raise IndexUnavailable("索引与语料、模型或文本构造版本不匹配。")
        if sha256(model_dir / MODEL_MARKER) != meta["model_manifest_sha256"]:
            raise IndexUnavailable("索引与本地模型文件清单不匹配。")
        path = index_dir / "embeddings.npy"
        if sha256(path) != meta["embeddings_sha256"]:
            raise IndexUnavailable("向量文件校验失败。")
        loaded = np.load(path, allow_pickle=False)
        if not isinstance(loaded, np.ndarray):
            if hasattr(loaded, "close"):
                loaded.close()
            raise IndexUnavailable("向量文件必须是 NumPy 数组。")
        vectors = _validate_vectors(loaded, len(self.sites))
        vectors.setflags(write=False)
        self.vectors = vectors

    @property
    def ready(self) -> bool:
        self._refresh()
        return self.reason is None and self.vectors is not None

    def scores(self, query: str) -> NDArray[np.float32]:
        with self.load_lock:
            self._refresh()
            if self.reason is not None or self.vectors is None:
                raise IndexUnavailable(self.reason or "语义索引不可用。")
            try:
                if self.encoder is None:
                    self.encoder = LocalEncoder(self.home / "model")
                query_vectors = _validate_vectors(self.encoder.encode([QUERY_PREFIX + query]), 1)
                return np.asarray(self.vectors @ query_vectors[0], dtype=np.float32)
            except Exception as error:
                self.encoder = None
                self.vectors = None
                self.reason = "本地模型加载或编码失败，请重新运行 prepare 修复模型和索引。"
                raise IndexUnavailable(self.reason) from error
