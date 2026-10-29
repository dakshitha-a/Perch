"""Embedding adapters behind one interface, with a content-hash cache.

Embeddings are asymmetric: researcher papers are embedded as queries (with a task
instruction) and opportunities as documents. The local default is
Qwen3-Embedding-0.6B through sentence-transformers (the optional `ml` extra);
tests use FakeEmbedder, which needs no model.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

DEFAULT_MODEL = "Qwen/Qwen3-Embedding-0.6B"
QUERY_TASK = "Given a research paper, retrieve funding opportunities whose aims it fits"
# Qwen3-Embedding's documented query format: "Instruct: <task>\nQuery:<text>".
# BGE-M3's model card uses no instruction for dense retrieval.
QWEN_PROMPT = f"Instruct: {QUERY_TASK}\nQuery:"
QUERY_PROMPTS = {"Qwen/Qwen3-Embedding-0.6B": QWEN_PROMPT, "Qwen/Qwen3-Embedding-4B": QWEN_PROMPT,
                 "BAAI/bge-m3": None}
SPECTER2 = "allenai/specter2_base"


def normalise(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


class Embedder(ABC):
    name: str
    dim: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Unit-length float32 rows, one per text."""

    @abstractmethod
    def embed_queries(self, texts: list[str]) -> np.ndarray:
        """Unit-length float32 rows, one per text, with the query instruction applied."""


class FakeEmbedder(Embedder):
    """Deterministic hashed bag of words. Shared words give similar vectors."""

    def __init__(self, dim: int = 256) -> None:
        self.name = f"fake-{dim}"
        self.dim = dim

    def _embed(self, texts: list[str]) -> np.ndarray:
        m = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                h = int.from_bytes(hashlib.sha256(w.encode()).digest()[:4], "little")
                m[i, h % self.dim] += 1.0
        return normalise(m)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)


class SentenceTransformerEmbedder(Embedder):
    """Local model via sentence-transformers. Install with `uv sync --extra ml`."""

    def __init__(self, model: str = DEFAULT_MODEL, device: str | None = None,
                 batch_size: int = 32, max_length: int = 1024) -> None:
        from sentence_transformers import SentenceTransformer  # optional dependency

        self.model = SentenceTransformer(model, device=device)
        self.model.max_seq_length = max_length
        self.name = model
        dim = getattr(self.model, "get_embedding_dimension", None) or \
            self.model.get_sentence_embedding_dimension
        self.dim = int(dim())
        self.batch_size = batch_size
        self.query_prompt = QUERY_PROMPTS.get(model, QWEN_PROMPT)

    def _encode(self, texts: list[str], prompt: str | None) -> np.ndarray:
        v = self.model.encode(texts, batch_size=self.batch_size, prompt=prompt,
                              normalize_embeddings=True, convert_to_numpy=True,
                              show_progress_bar=False)
        return v.astype(np.float32)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, None)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, self.query_prompt)


class Specter2Embedder(Embedder):
    """SPECTER2 base, without the proximity adapter: title and abstract joined by the
    separator token, 512 tokens, first-token state, as the allenai/specter2 card shows.
    Symmetric (no query instruction). The card's adapter needs the `adapters` library,
    which pins transformers 4.57 while sentence-transformers 6.2 needs transformers 5,
    so the adapter row is not benched (S8)."""

    def __init__(self, device: str | None = None, batch_size: int = 32) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer  # optional dependency (ml)

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(SPECTER2)
        self.model = AutoModel.from_pretrained(SPECTER2)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device).eval()
        self.name, self.dim, self.batch_size = SPECTER2, 768, batch_size

    def _embed(self, texts: list[str]) -> np.ndarray:
        # Perch texts are "title. abstract"; the card's format puts [SEP] between them.
        texts = [t.replace(". ", self.tok.sep_token, 1) for t in texts]
        out = []
        with self.torch.no_grad():
            for i in range(0, len(texts), self.batch_size):
                batch = self.tok(texts[i:i + self.batch_size], padding=True, truncation=True,
                                 max_length=512, return_tensors="pt").to(self.device)
                out.append(self.model(**batch).last_hidden_state[:, 0].float().cpu().numpy())
        return normalise(np.concatenate(out) if out else np.zeros((0, self.dim))).astype(
            np.float32)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CachedEmbedder(Embedder):
    """Wraps an embedder; caches vectors in SQLite by (model, kind, sha256 of text).

    Shared across brief jobs: one lock serialises cache access and model calls, so
    concurrent briefs can use the same instance."""

    def __init__(self, inner: Embedder, path: str | Path = "data/cache/embeddings.db") -> None:
        self.inner, self.name, self.dim = inner, inner.name, inner.dim
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        self.conn.execute("CREATE TABLE IF NOT EXISTS vectors (model TEXT, kind TEXT, hash TEXT, "
                          "vec BLOB, PRIMARY KEY (model, kind, hash))")
        self.hits = self.misses = 0

    def _get(self, texts: list[str], kind: str) -> np.ndarray:
        with self.lock:
            return self._get_locked(texts, kind)

    def _get_locked(self, texts: list[str], kind: str) -> np.ndarray:
        hashes = [content_hash(t) for t in texts]
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        missing: list[int] = []
        for i, h in enumerate(hashes):
            row = self.conn.execute("SELECT vec FROM vectors WHERE model=? AND kind=? AND hash=?",
                                    (self.name, kind, h)).fetchone()
            if row:
                out[i] = np.frombuffer(row[0], dtype=np.float32)
            else:
                missing.append(i)
        self.hits += len(texts) - len(missing)
        self.misses += len(missing)
        if missing:
            todo = [texts[i] for i in missing]
            vecs = (self.inner.embed_queries(todo) if kind == "query"
                    else self.inner.embed_documents(todo))
            with self.conn:
                for i, v in zip(missing, vecs, strict=True):
                    out[i] = v
                    self.conn.execute("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?)",
                                      (self.name, kind, hashes[i], v.astype(np.float32).tobytes()))
        return out

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._get(texts, "doc")

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._get(texts, "query")


def get_embedder(name: str = DEFAULT_MODEL, cache: str | Path | None = "data/cache/embeddings.db",
                 device: str | None = None) -> Embedder:
    inner: Embedder
    if name.startswith("fake-"):
        inner = FakeEmbedder(int(name.split("-")[1]))
    elif name == SPECTER2:
        inner = Specter2Embedder(device=device)
    else:
        inner = SentenceTransformerEmbedder(name, device=device)
    return CachedEmbedder(inner, cache) if cache else inner
