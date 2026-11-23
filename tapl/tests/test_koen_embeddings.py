"""Semantic model compatibility and atomic publication of model-specific vectors."""

import base64
from contextlib import closing
import hashlib
import io
import struct
from urllib.error import HTTPError

import pytest

from taplctl import config, db, embedding_model, embeddings, searchd


KOEN, MULTILINGUAL = embedding_model.MODELS
LEGACY = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
VECTOR = struct.pack("<384f", 1.0, *([0.0] * 383))


def test_cache_only_installs_complete_verified_artifacts(tmp_path, monkeypatch):
    target = tmp_path / "cache" / "model.onnx"
    digest = hashlib.sha256(b"complete").hexdigest()
    url = "https://example.invalid/revision/model.onnx"
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(b"partial"))
    with pytest.raises(ValueError, match="SHA-256"):
        embedding_model._verified_file(target, url, digest)
    assert list(target.parent.iterdir()) == []

    target.write_bytes(b"corrupt")
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(b"complete"))
    assert embedding_model._verified_file(target, url, digest).read_bytes() == b"complete"
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("unexpected download"))
    assert embedding_model._verified_file(target, url, digest) == target


def test_model_download_retries_transient_http_errors(tmp_path, monkeypatch):
    target = tmp_path / "model.onnx"
    url = "https://example.invalid/revision/model.onnx"
    outcomes = iter([502, 503, 200])
    sleeps = []

    def fetch(request_url, *, timeout):
        status = next(outcomes)
        if status != 200:
            raise HTTPError(request_url, status, "temporary failure", {}, None)
        return io.BytesIO(b"model data")

    monkeypatch.setattr("urllib.request.urlopen", fetch)
    monkeypatch.setattr("time.sleep", sleeps.append)
    digest = hashlib.sha256(b"model data").hexdigest()
    assert embedding_model._verified_file(target, url, digest).read_bytes() == b"model data"
    assert sleeps == [1, 2]
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("mode", ["semantic", "hybrid", "bm25", "word"])
def test_legacy_index_stays_readable_without_loading_an_encoder(tmp_path, monkeypatch, mode):
    path = tmp_path / "history.db"
    with closing(db.connect(path)) as conn:
        conn.execute("CREATE TABLE item_embeddings(embedding BLOB)")
        conn.execute("INSERT INTO item_embeddings VALUES(?)", (VECTOR,))
        db.set_meta(conn, "embedding_model", LEGACY)
        conn.commit()

    monkeypatch.setattr(embeddings, "query_embedding_blob", lambda *args: pytest.fail("queried legacy vectors"))
    with closing(db.connect(path)) as conn:
        result = embeddings.search(conn, "restore", search_config=config.SearchConfig(mode=mode))
        assert result["mode"] == ("bm25" if mode == "semantic" else mode)
        if mode in ("semantic", "hybrid"):
            assert "taplctl reindex" in result["fallback_reason"] and LEGACY in result["fallback_reason"]
        else:
            assert "fallback_reason" not in result
        dry = embeddings.reindex(conn, model=MULTILINGUAL, dry_run=True)
        assert dry["embedding_model"] == MULTILINGUAL and dry["needs_reindex"]
        assert dry["indexed_model"] == LEGACY
        assert db.get_meta(conn)["embedding_model"] == LEGACY
        assert conn.execute("SELECT embedding FROM item_embeddings").fetchone()[0] == VECTOR


@pytest.fixture
def indexed_db(tmp_path, monkeypatch):
    pytest.importorskip("sqlite_vec")
    path = tmp_path / "history.db"
    conn = db.connect(path)
    try:
        if not hasattr(conn, "enable_load_extension"):
            pytest.skip("Python SQLite does not support extension loading")
        conn.execute("""INSERT INTO workflow_runs(id,status,slug,created_at,updated_at)
                        VALUES('w','archived','w','now','now')""")
        conn.execute("""INSERT INTO items(id,run_id,stable_id,kind,title,created_at,updated_at)
                        VALUES(1,'w','PLAN-001','plan','restore','now','now')""")
        conn.commit()
        monkeypatch.setattr(embeddings, "dependency_status", lambda: {"sqlite_vec": True})

        class FakeModel:
            def encode(self, texts, *, query):
                return [VECTOR] * len(texts)

        monkeypatch.setattr(embeddings, "_local_model", lambda *args: FakeModel())
        assert embeddings.reindex(conn)["ok"]
        yield path, conn
    finally:
        conn.close()


def test_failed_rebuild_keeps_previous_vectors_metadata_and_jobs(indexed_db):
    path, conn = indexed_db
    # Fail after the replacement vectors have been inserted.
    conn.execute("""CREATE TRIGGER fail_job BEFORE UPDATE ON embedding_jobs
                    BEGIN SELECT RAISE(ABORT, 'simulated failure'); END""")
    before = db.get_meta(conn), list(conn.execute("SELECT * FROM embedding_jobs"))
    result = embeddings.reindex(conn, model=MULTILINGUAL)
    assert not result["ok"] and "simulated failure" in result["error"]
    assert before == (db.get_meta(conn), list(conn.execute("SELECT * FROM embedding_jobs")))
    with closing(db.connect_readonly(path)) as reader:
        search = embeddings.search(reader, "restore", search_config=config.SearchConfig(mode="semantic", semantic_provider="local"))
        assert search["mode"] == "semantic" and search["results"][0]["id"] == 1


def test_search_model_and_vectors_share_snapshot_during_reindex(indexed_db, monkeypatch):
    path, writer = indexed_db
    # For the two models, index one orthogonal passage each. Switch the model
    # after the reader's identity check, before the KNN query actually runs.
    other_vector = struct.pack("<384f", 0.0, 1.0, *([0.0] * 382))

    class OtherModel:
        def encode(self, texts, *, query):
            return [other_vector] * len(texts)

    monkeypatch.setattr(embeddings, "_local_model", lambda *args: OtherModel())
    def switch_during_inference(*args):
        assert embeddings.reindex(writer, model=MULTILINGUAL)["ok"]
        return VECTOR
    monkeypatch.setattr(embeddings, "query_embedding_blob", switch_during_inference)
    with closing(db.connect(path)) as reader:
        settings = config.SearchConfig(model=KOEN, mode="semantic")
        result = embeddings.search(reader, "restore", search_config=settings)
        assert result["results"][0]["score"] == 0 and result["mode"] == "semantic"
        stale = embeddings.search(reader, "restore", search_config=settings)
        assert stale["mode"] == "bm25" and "taplctl reindex" in stale["fallback_reason"]


def test_source_edits_during_inference_do_not_publish_a_stale_index(indexed_db, monkeypatch):
    path, conn = indexed_db
    assert not embeddings.reindex(conn, dry_run=True)["needs_reindex"]
    class RacingModel:
        def encode(self, texts, *, query):
            with closing(db.connect(path)) as writer:
                writer.execute("UPDATE items SET title='new text' WHERE id=1")
                writer.commit()
            return [VECTOR] * len(texts)
    monkeypatch.setattr(embeddings, "_local_model", lambda *args: RacingModel())
    result = embeddings.reindex(conn, model=MULTILINGUAL)
    assert not result["ok"] and "retry taplctl reindex" in result["error"]
    assert db.get_meta(conn)["onnx_embedding_model"] == KOEN
    assert conn.execute("SELECT title FROM items").fetchone()[0] == "new text"
    assert embeddings.reindex(conn, dry_run=True)["needs_reindex"]


@pytest.mark.parametrize("change", [
    {"model": LEGACY}, {"fingerprint": None}, {"fingerprint": "different"},
    {"dimension": 128}, {"embedding_b64": "YWJj"}, {"embedding_b64": "%%"},
])
def test_client_rejects_incompatible_daemon_vector(monkeypatch, change):
    response = {
        "ok": True, "model": KOEN, "fingerprint": embedding_model.MODELS[KOEN].fingerprint,
        "dimension": 384, "embedding_b64": base64.b64encode(VECTOR).decode("ascii"),
    }
    monkeypatch.setattr(searchd, "request", lambda *args, **kwargs: {**response, **change})
    with pytest.raises(searchd.SearchdError):
        searchd.embed_query("질의", config.SearchConfig())


def test_new_daemon_rejects_legacy_request_before_loading():
    state = searchd.ModelState(model_idle_timeout_seconds=1, model_loader=lambda *args: pytest.fail("model load"))
    response, stopped = searchd.handle_request(
        {"op": "embed", "model": LEGACY, "dimension": 384, "text": "query"}, model_state=state, started_at=0,
    )
    assert not response["ok"] and not stopped and not state.model_loaded


@pytest.mark.parametrize("query,prefix", [(True, "query: "), (False, "passage: ")])
def test_encoder_masks_padding_normalizes_and_applies_role_prefix(query, prefix):
    from types import SimpleNamespace
    np = pytest.importorskip("numpy")
    encoder = embedding_model.Encoder.__new__(embedding_model.Encoder)

    class Tokenizer:
        def encode_batch(self, texts):
            assert texts == [prefix + "계획", prefix + "restore"]
            return [SimpleNamespace(ids=[1, 2, 0], attention_mask=[1, 1, 0]),
                    SimpleNamespace(ids=[1, 3, 2], attention_mask=[1, 1, 1])]

    class Session:
        def run(self, outputs, inputs):
            assert outputs == ["last_hidden_state"]
            assert inputs["input_ids"].dtype == np.int64 and inputs["attention_mask"].dtype == np.int64
            hidden = np.zeros((2, 3, 384), dtype=np.float32)
            hidden[0, 0, 0] = 3
            hidden[0, 1, 1] = 4
            hidden[0, 2, :] = 1000
            hidden[1, :, 2] = 9
            return [hidden]

    encoder.inputs = ["input_ids", "attention_mask"]
    encoder.tokenizer = Tokenizer()
    encoder.session = Session()
    first, second = encoder.encode(["계획", "restore"], query=query)
    assert len(first) == len(second) == 1536
    assert np.allclose(np.frombuffer(first, dtype="<f4"), [0.6, 0.8, *([0.] * 382)])
    assert np.allclose(np.frombuffer(second, dtype="<f4"), [0., 0., 1., *([0.] * 381)])


def test_successful_rebuild_leaves_legacy_clients_their_own_vectors(indexed_db):
    _, conn = indexed_db
    conn.execute("CREATE VIRTUAL TABLE item_embeddings USING vec0(embedding float[384], kind text, run_id text)")
    old_vector = struct.pack("<384f", -1.0, *([0.0] * 383))
    conn.execute("INSERT INTO item_embeddings(rowid, embedding, kind, run_id) VALUES(1,?,'plan','w')", (old_vector,))
    db.set_meta(conn, "embedding_model", LEGACY)
    db.set_meta(conn, "embedding_dimension", "384")
    conn.commit()

    assert embeddings.reindex(conn, model=MULTILINGUAL)["ok"]
    assert db.get_meta(conn)["embedding_model"] == LEGACY
    assert conn.execute("SELECT embedding FROM item_embeddings WHERE rowid=1").fetchone()[0] == old_vector
    assert conn.execute("SELECT embedding FROM item_embeddings_onnx WHERE rowid=1").fetchone()[0] == VECTOR
