import numpy as np

from perch.embed import CachedEmbedder, FakeEmbedder, get_embedder


def test_fake_is_deterministic_unit_length_and_word_sensitive():
    e = FakeEmbedder(128)
    a, b, c = e.embed_documents(["blood brain barrier injury", "blood brain barrier",
                                 "kidney transplant donors"])
    assert np.allclose(np.linalg.norm([a, b, c], axis=1), 1.0)
    assert np.allclose(e.embed_documents(["blood brain barrier"])[0], b)
    assert a @ b > a @ c


def test_cache_hits_on_second_call_and_keeps_kinds_apart(tmp_path):
    c = CachedEmbedder(FakeEmbedder(64), tmp_path / "e.db")
    first = c.embed_documents(["x y", "y z"])
    assert (c.hits, c.misses) == (0, 2)
    again = c.embed_documents(["y z", "x y"])
    assert (c.hits, c.misses) == (2, 2)
    assert np.allclose(again[1], first[0])
    c.embed_queries(["x y"])
    assert c.misses == 3  # queries cached separately from documents


def test_get_embedder_fake_without_cache():
    e = get_embedder("fake-32", cache=None)
    assert e.dim == 32 and e.embed_queries(["a"]).shape == (1, 32)
