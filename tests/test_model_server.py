"""The hybrid deployment's model server and its HTTP clients, with fake models."""

import httpx
import numpy as np
from fastapi.testclient import TestClient

from perch.embed import FakeEmbedder
from perch.grounding import FakeGrounder, make_grounder
from perch.model_server import create_app
from perch.remote_models import RemoteEmbedder, RemoteGrounder, RemoteReranker
from perch.rerank import FakeReranker


class Bridge(httpx.BaseTransport):
    """Sends the clients' requests to the app in process."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        r = self.client.request(request.method, request.url.path, content=request.read(),
                                headers={"content-type": "application/json"})
        return httpx.Response(r.status_code, content=r.content, headers=r.headers)


def bridge():
    app = create_app(lambda name: FakeEmbedder(64), lambda name: FakeReranker(), FakeGrounder)
    return Bridge(TestClient(app)), app


def test_remote_embedder_matches_the_in_process_model():
    t, _ = bridge()
    e = RemoteEmbedder("http://models", "fake-64", transport=t)
    texts = ["gait sensing", "SYNTHETIC wearable study"]
    assert e.dim == 64
    assert np.allclose(e.embed_queries(texts), FakeEmbedder(64).embed_queries(texts))
    assert np.allclose(e.embed_documents(texts), FakeEmbedder(64).embed_documents(texts))
    assert e.embed_queries([]).shape == (0, 64)


def test_remote_reranker_and_grounder_return_the_served_scores():
    t, _ = bridge()
    r = RemoteReranker("http://models", "fake", transport=t)
    assert r.score("gait sensor", ["gait sensor study", "ocean"]) == \
        FakeReranker().score("gait sensor", ["gait sensor study", "ocean"])
    g = RemoteGrounder("http://models", transport=t)
    assert g.support("doc text", ["a claim"]) == FakeGrounder().support("doc text", ["a claim"])


def test_health_lists_models_loaded_on_first_use():
    t, app = bridge()
    c = TestClient(app)
    assert c.get("/health").json()["loaded"] == []
    RemoteReranker("http://models", "fake", transport=t).score("q", ["d"])
    assert c.get("/health").json()["loaded"] == ["rerank:fake"]


def test_grounder_falls_back_to_the_given_factory_when_the_decision_server_is_down(monkeypatch):
    monkeypatch.setenv("PERCH_CLEF_URL", "http://127.0.0.1:9")  # nothing listens on port 9
    g = make_grounder("systemone:clef", fallback=FakeGrounder)
    assert isinstance(g, FakeGrounder)
