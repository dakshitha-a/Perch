from perch.embed import FakeEmbedder
from perch.store.lance import LanceIndex

TEXTS = {
    "o1": "Blood brain barrier injury in HIV infection and alcohol use",
    "o2": "Living kidney donor decision support and transplant communication",
    "o3": "Leukemia DNA repair targeted therapy",
}


def build(tmp_path):
    e = FakeEmbedder(64)
    idx = LanceIndex(tmp_path / "lance")
    ids = list(TEXTS)
    texts = [TEXTS[i] for i in ids]
    assert idx.upsert(ids, texts, e.embed_documents(texts).tolist()) == 3
    return idx, e


def test_dense_and_bm25(tmp_path):
    idx, e = build(tmp_path)
    q = e.embed_queries(["kidney transplant donor"])[0].tolist()
    assert idx.dense(q, 3)[0][0] == "o2"
    assert idx.bm25("kidney donors (transplant)", 3)[0][0] == "o2"  # stemming; punctuation ok
    assert idx.ids() == {"o1", "o2", "o3"}


def test_upsert_replaces_by_id_and_reopens(tmp_path):
    idx, e = build(tmp_path)
    new = ["kidney organ allocation"]
    idx.upsert(["o3"], new, e.embed_documents(new).tolist())
    again = LanceIndex(tmp_path / "lance")
    assert again.ids() == {"o1", "o2", "o3"}
    assert {i for i, _ in again.bm25("leukemia", 3)} == set()
    assert "o3" in {i for i, _ in again.bm25("allocation", 3)}


def test_empty_index():
    import tempfile
    idx = LanceIndex(tempfile.mkdtemp())
    assert idx.dense([0.0] * 4, 3) == [] and idx.bm25("x", 3) == [] and idx.ids() == set()
