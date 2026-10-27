from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest
from fastapi.testclient import TestClient
from qdrant_client import models

from backend.config import Settings
from backend.main import create_app
from backend.service import Library
from backend.vectors import VectorStore
from test_library import TestEmbedder, import_records


def settings_for(path, **kwargs):
    return Settings(data_dir=path, preload=False, worker_enabled=False, dimensions=16, collection='test', **kwargs)


def populate(store):
    store.upsert([models.PointStruct(id=1, vector=[1.0] + [0.0] * 15,
        payload={'generation': 'g1', 'fragment_id': 'f1'})])


def query(store):
    return store.search([1.0] + [0.0] * 15, ['g1'], 10)


def test_startup_health_and_library_browsing_never_load_vectors(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    lib = Library(settings, TestEmbedder())
    corpus = lib.create_corpus('已有语料')
    item = import_records(lib, corpus, [{'text': '原文'}])
    lib.process_one()
    lib.close()

    def forbidden(*args, **kwargs):
        raise AssertionError('metadata request loaded the vector store')

    monkeypatch.setattr('backend.vectors.QdrantClient', forbidden)
    with TestClient(create_app(settings, TestEmbedder())) as client:
        assert client.get('/api/health').json()['vector_cache'] == {'loaded': False, 'idle_seconds': 30}
        assert client.get('/api/corpora').json()[0]['indexed_resources'] == 1
        assert client.get(f'/api/corpora/{corpus}/resources').status_code == 200
        assert client.get(f'/api/corpora/{corpus}/resources/{item["resource_id"]}/content').status_code == 200
        assert client.app.state.library.vectors.last_used == 0


def test_cache_reuse_eviction_reload_and_delete(tmp_path):
    store = VectorStore(settings_for(tmp_path))
    try:
        assert store._client is None
        populate(store)
        first = store._client
        assert query(store)[0].id == 1
        assert store._client is first
        store.release_if_idle()
        assert store._client is first
        store.last_used -= 31
        timestamp = store.last_used
        assert store.cache_status()['loaded']
        assert store.last_used == timestamp
        store.release_if_idle()
        assert store._client is None
        assert query(store)[0].payload['fragment_id'] == 'f1'
        assert store._client is not first
        store.delete_generation('g1')
        store.compact_deleted()
        assert store._client is None
        assert query(store) == []
    finally:
        store.close()


def test_concurrent_cold_requests_load_once(tmp_path, monkeypatch):
    from backend import vectors
    store = VectorStore(settings_for(tmp_path))
    populate(store)
    store.compact_deleted()
    constructor = vectors.QdrantClient
    calls = []

    def recorded(*args, **kwargs):
        calls.append(1)
        return constructor(*args, **kwargs)

    monkeypatch.setattr(vectors, 'QdrantClient', recorded)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: query(store)[0].id, range(12)))
        assert results == [1] * 12
        assert len(calls) == 1
    finally:
        store.close()


def test_eviction_never_closes_an_active_query(tmp_path, monkeypatch):
    store = VectorStore(settings_for(tmp_path))
    populate(store)
    started, resume = threading.Event(), threading.Event()
    client = store._client
    original_query = client.query_points

    def blocked(*args, **kwargs):
        started.set()
        assert resume.wait(5)
        return original_query(*args, **kwargs)

    monkeypatch.setattr(client, 'query_points', blocked)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(query, store)
            try:
                assert started.wait(5)
                store.last_used -= 31
                store.release_if_idle()
                assert store._client is client
            finally:
                resume.set()
            assert pending.result(timeout=5)[0].id == 1
        store.release_if_idle()
        assert store._client is client  # Lifetime is refreshed when the query finishes.
    finally:
        store.close()


def test_directory_stays_exclusive_while_unloaded(tmp_path):
    settings = settings_for(tmp_path)
    store = VectorStore(settings)
    try:
        with pytest.raises(RuntimeError, match='另一个进程'):
            VectorStore(settings)
        populate(store)
        store.last_used -= 31
        store.release_if_idle()
        assert store._client is None
        with pytest.raises(RuntimeError, match='另一个进程'):
            VectorStore(settings)
    finally:
        store.close()
    reopened = VectorStore(settings)
    assert query(reopened)[0].id == 1
    reopened.close()
    with pytest.raises(RuntimeError, match='closed'):
        query(reopened)


def test_worker_releases_cache_without_more_requests(tmp_path, monkeypatch):
    lib = Library(settings_for(tmp_path), TestEmbedder())
    corpus = lib.create_corpus('自动回收')
    import_records(lib, corpus, [{'text': '需要按需加载'}])
    lib.process_one()
    unloaded = threading.Event()
    original = lib.vectors._unload

    def notify_unload():
        original()
        unloaded.set()

    monkeypatch.setattr(lib.vectors, '_unload', notify_unload)
    lib.vectors.last_used -= 31
    try:
        lib.start_worker()
        assert unloaded.wait(5)
        assert lib.vectors._client is None
        assert len(lib.search(corpus, '按需')['results']) == 1
    finally:
        lib.close()


def test_failed_initialization_closes_client_and_can_retry(tmp_path, monkeypatch):
    store = VectorStore(settings_for(tmp_path))
    original = store._initialize_collection

    def fail(client):
        raise RuntimeError('initialization interrupted')

    monkeypatch.setattr(store, '_initialize_collection', fail)
    try:
        with pytest.raises(RuntimeError, match='interrupted'):
            query(store)
        assert store._client is None
        monkeypatch.setattr(store, '_initialize_collection', original)
        populate(store)  # Reopening succeeds only if the failed client's file lock was released.
        assert query(store)[0].id == 1
    finally:
        store.close()


def test_live_idle_expiry_with_health_and_library_polling(tmp_path):
    settings = Settings(data_dir=tmp_path, preload=False, dimensions=16, collection='test',
        vector_cache_idle_seconds=1, index_batch_pause=0)
    with TestClient(create_app(settings, TestEmbedder())) as client:
        lib = client.app.state.library
        corpus = lib.create_corpus('缓存端到端验证')
        import_records(lib, corpus, [{'text': '按需检索的原文'}])
        deadline = time.monotonic() + 10
        while client.get('/api/corpora').json()[0]['pending_jobs']:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        body = {'corpus_id': corpus, 'query': '原文'}
        first = client.post('/api/search', json=body).json()['results']
        assert len(first) == 1
        assert client.get('/api/health').json()['vector_cache']['loaded']
        deadline = time.monotonic() + 6
        while client.get('/api/health').json()['vector_cache']['loaded']:
            assert time.monotonic() < deadline
            assert client.get('/api/corpora').json()[0]['indexed_resources'] == 1
            time.sleep(0.1)
        assert lib.vectors._client is None
        assert client.post('/api/search', json=body).json()['results'] == first
        assert client.get('/api/health').json()['vector_cache']['loaded']
