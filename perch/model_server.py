"""The GPU-side models of the hybrid deployment (S9) as one small HTTP service.

The app runs in Docker without GPU access (the node has no NVIDIA container runtime),
so the embedder, the reranker and the MiniCheck fallback grounder run here, on the
host, as a systemd user unit on a demo GPU. The app reaches them through
RemoteEmbedder, RemoteReranker and RemoteGrounder when PERCH_MODEL_SERVER is set.
Same models and code as in-process, so results match the S8 back-test.

  uv run --extra ml python -m perch.model_server --port 8093
"""

from __future__ import annotations

import argparse
import threading
from collections.abc import Callable

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

from perch.embed import Embedder
from perch.grounding import Grounder
from perch.rerank import Reranker


class EmbedRequest(BaseModel):
    model: str
    kind: str  # "query" or "document"
    texts: list[str]


class RerankRequest(BaseModel):
    model: str
    query: str
    docs: list[str]


class GroundRequest(BaseModel):
    document: str
    claims: list[str]


def create_app(embedder: Callable[[str], Embedder], reranker: Callable[[str], Reranker],
               grounder: Callable[[], Grounder]) -> FastAPI:
    """Models load on first use, one per name, behind one lock (GPU calls are serial)."""
    app = FastAPI(title="Perch model server")
    lock = threading.Lock()
    loaded: dict[tuple[str, str], object] = {}

    def get(kind: str, name: str, make: Callable[[], object]) -> object:
        if (kind, name) not in loaded:
            loaded[(kind, name)] = make()
        return loaded[(kind, name)]

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "loaded": sorted(f"{k}:{n}" for k, n in loaded)}

    @app.post("/embed")
    def embed(req: EmbedRequest) -> dict:
        with lock:
            e = get("embed", req.model, lambda: embedder(req.model))
            m = (e.embed_queries(req.texts) if req.kind == "query"
                 else e.embed_documents(req.texts))
        return {"vectors": np.asarray(m, dtype=np.float32).tolist()}

    @app.post("/rerank")
    def rerank(req: RerankRequest) -> dict:
        with lock:
            return {"scores": get("rerank", req.model, lambda: reranker(req.model))
                    .score(req.query, req.docs)}

    @app.post("/ground")
    def ground(req: GroundRequest) -> dict:
        with lock:
            return {"scores": get("ground", "minicheck", grounder).support(req.document,
                                                                            req.claims)}

    return app


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    from perch.embed import get_embedder
    from perch.grounding import MiniCheckGrounder
    from perch.rerank import CrossEncoderReranker

    ap = argparse.ArgumentParser(description="Perch model server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8093)
    a = ap.parse_args(argv)
    # No cache here: the app's CachedEmbedder and RerankCache sit in front of this service.
    app = create_app(lambda name: get_embedder(name, cache=None),
                     lambda name: CrossEncoderReranker(name),
                     lambda: MiniCheckGrounder(device="cuda"))
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
