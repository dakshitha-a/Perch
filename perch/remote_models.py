"""Clients for perch.model_server: the embedder, reranker and MiniCheck grounder over HTTP.

Used when PERCH_MODEL_SERVER is set (the hybrid S9 deployment: the app in Docker
without GPU access, the models on the host). Same interfaces as the in-process
classes; the app's caches sit in front of them unchanged.
"""

from __future__ import annotations

import httpx
import numpy as np

from perch.embed import Embedder
from perch.grounding import Grounder
from perch.rerank import Reranker


def client(url: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(base_url=url, timeout=300.0, transport=transport)


class RemoteEmbedder(Embedder):
    def __init__(self, url: str, model: str, transport: httpx.BaseTransport | None = None) -> None:
        self.http, self.name = client(url, transport), model
        self.dim = int(self._embed(["dimension probe"], "query").shape[1])

    def _embed(self, texts: list[str], kind: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, getattr(self, "dim", 0)), dtype=np.float32)
        r = self.http.post("/embed", json={"model": self.name, "kind": kind, "texts": texts})
        r.raise_for_status()
        return np.asarray(r.json()["vectors"], dtype=np.float32).reshape(len(texts), -1)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts, "document")

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts, "query")


class RemoteReranker(Reranker):
    def __init__(self, url: str, model: str, transport: httpx.BaseTransport | None = None) -> None:
        self.http, self.name = client(url, transport), model

    def score(self, query: str, docs: list[str]) -> list[float]:
        r = self.http.post("/rerank", json={"model": self.name, "query": query, "docs": docs})
        r.raise_for_status()
        return [float(x) for x in r.json()["scores"]]


class RemoteGrounder(Grounder):
    name = "minicheck (model server)"

    def __init__(self, url: str, transport: httpx.BaseTransport | None = None) -> None:
        self.http = client(url, transport)

    def support(self, document: str, claims: list[str]) -> list[float]:
        r = self.http.post("/ground", json={"document": document, "claims": claims})
        r.raise_for_status()
        return [float(x) for x in r.json()["scores"]]
