from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from shutil import copyfile
import struct
from threading import Event
from types import SimpleNamespace

import pytest

from taplctl import auto_reindex, db, embedding_model, embeddings


KOEN, MULTILINGUAL = embedding_model.MODELS
VECTOR = struct.pack("<384f", 1.0, *([0.0] * 383))


def write_config(path, *, model=KOEN, mode="hybrid"):
    path.write_text(f'[search]\nmode = "{mode}"\nmodel = "{model}"\n', encoding="utf-8")


@pytest.fixture
def legacy_index(tmp_path, monkeypatch):
    path = tmp_path / db.DEFAULT_DB_RELATIVE
    config_path = path.with_name("config.toml")
    with closing(db.connect(path)) as conn:
        db.ensure_active_run(conn)
        db.upsert_item(conn, kind="finding", stable_id="FINDING-001", title="A useful record", body="Evidence")
        conn.execute("CREATE TABLE item_embeddings(embedding BLOB)")
        conn.execute("INSERT INTO item_embeddings VALUES(?)", (VECTOR,))
        db.set_meta(conn, "embedding_model", "legacy-model")
        conn.commit()
    write_config(config_path)
    monkeypatch.setattr(db, "local_db_path", lambda workspace: None)
    monkeypatch.setattr(embeddings, "dependency_status", lambda: {"sqlite_vec": True})
    return path, config_path


def test_schedule_only_addresses_existing_local_mismatches(tmp_path, legacy_index, monkeypatch):
    path, config_path = legacy_index
    spawned = []

    def start(command, **options):
        spawned.append((command, options))
        return SimpleNamespace(wait=lambda: 0)

    monkeypatch.setattr(auto_reindex.subprocess, "Popen", start)
    assert auto_reindex.schedule(tmp_path) == {"status": "scheduled"}
    assert spawned[0][0][1:] == ["-m", "taplctl.auto_reindex", str(path)]
    assert spawned[0][1]["cwd"] == tmp_path
    peer = path.with_name("tapl-peer.db")
    copyfile(path, peer)
    assert auto_reindex.schedule(tmp_path, database=peer) is None
    write_config(config_path, mode="bm25")
    assert auto_reindex.schedule(tmp_path) is None
    write_config(config_path)
    path.unlink()
    assert auto_reindex.schedule(tmp_path) is None
    assert not path.exists()
    assert len(spawned) == 1


def test_worker_rechecks_a_model_selected_just_after_publication(tmp_path, legacy_index, monkeypatch):
    pytest.importorskip("sqlite_vec")
    path, config_path = legacy_index
    real_reindex = embeddings.reindex

    def reindex(conn, *, model, should_publish):
        result = real_reindex(conn, model=model, should_publish=should_publish)
        assert result["ok"]
        if model == KOEN:
            write_config(config_path, model=MULTILINGUAL)
        return result

    monkeypatch.setattr(embeddings, "reindex", reindex)
    monkeypatch.setattr(embeddings, "_local_model", lambda *_: SimpleNamespace(encode=lambda texts, query: [VECTOR] * len(texts)))
    assert auto_reindex._rebuild(path, tmp_path, None)
    with closing(db.connect_readonly(path)) as conn:
        assert not embeddings.index_model_mismatch(conn, MULTILINGUAL)


def test_worker_rechecks_latest_model_and_preserves_legacy_index(tmp_path, legacy_index, monkeypatch):
    pytest.importorskip("sqlite_vec")
    path, config_path = legacy_index
    encoded = []

    def encoder(model, _cache):
        encoded.append(model)
        if model == KOEN:
            write_config(config_path, model=MULTILINGUAL)
        return SimpleNamespace(encode=lambda texts, query: [VECTOR] * len(texts))

    monkeypatch.setattr(embeddings, "_local_model", encoder)
    assert auto_reindex._rebuild(path, tmp_path, None)
    assert encoded == [KOEN, MULTILINGUAL]
    with closing(db.connect_readonly(path)) as conn:
        assert not embeddings.index_model_mismatch(conn, MULTILINGUAL)
        assert conn.execute("SELECT embedding FROM item_embeddings").fetchone()[0] == VECTOR
    assert auto_reindex.schedule(tmp_path) is None


def test_concurrent_workers_only_encode_once(tmp_path, legacy_index, monkeypatch):
    pytest.importorskip("sqlite_vec")
    path, _ = legacy_index
    started, finish = Event(), Event()
    attempts = Counter()

    def encoder(model, _cache):
        attempts[model] += 1
        started.set()
        assert finish.wait(timeout=5)
        return SimpleNamespace(encode=lambda texts, query: [VECTOR] * len(texts))

    monkeypatch.setattr(embeddings, "_local_model", encoder)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(auto_reindex._rebuild, path, tmp_path, None)
        assert started.wait(timeout=5)
        second = pool.submit(auto_reindex._rebuild, path, tmp_path, None)
        finish.set()
        assert first.result(timeout=5) and second.result(timeout=5)
    assert attempts == {KOEN: 1}


def test_worker_failure_leaves_previous_index_and_can_retry(tmp_path, legacy_index, monkeypatch):
    pytest.importorskip("sqlite_vec")
    path, _ = legacy_index

    def unavailable(*_args):
        raise OSError("model is temporarily unavailable")

    monkeypatch.setattr(embeddings, "_local_model", unavailable)
    assert not auto_reindex._rebuild(path, tmp_path, None)
    with closing(db.connect_readonly(path)) as conn:
        assert embeddings.index_model_mismatch(conn, KOEN)
        assert db.get_meta(conn)["embedding_model"] == "legacy-model"
    monkeypatch.setattr(embeddings, "_local_model", lambda *_: SimpleNamespace(encode=lambda texts, query: [VECTOR] * len(texts)))
    assert auto_reindex._rebuild(path, tmp_path, None)
