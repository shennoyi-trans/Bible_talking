import sys
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import select

from backend.config import Settings
from backend.models import Fragment, IngestionJob, Resource
from backend.service import Library
from backend.vectors import Embedder
from test_library import TestEmbedder, import_records


@pytest.mark.parametrize('values', [
    {'embedding_batch_size': 0}, {'embedding_threads': 0},
    {'embedding_idle_seconds': 0}, {'index_batch_pause': -1},
    {'index_batch_pause': float('nan')}, {'index_batch_pause': float('inf')},
])
def test_invalid_resource_limits(values):
    with pytest.raises(ValueError):
        Settings(**values).validate()


def test_idle_model_unloads_and_reloads_without_interrupting_inference(tmp_path, monkeypatch):
    models = []

    class Model:
        def __init__(self, **options):
            assert options['threads'] == 1
            assert options['enable_cpu_mem_arena'] is False
            models.append(self)

        def passage_embed(self, texts, batch_size):
            assert batch_size == 8
            return (np.array([len(text), 1.0]) for text in texts)

        query_embed = passage_embed

    monkeypatch.setitem(sys.modules, 'fastembed', SimpleNamespace(TextEmbedding=Model))
    embedder = Embedder(Settings(data_dir=tmp_path))
    assert embedder.model is None
    expected = embedder.encode(['测试'])
    embedder.release_if_idle()
    assert embedder.model is models[0]
    embedder.last_used -= 61
    with embedder.lock:
        embedder.release_if_idle()
        assert embedder.model is models[0]
    embedder.release_if_idle()
    assert embedder.model is None
    assert embedder.encode(['测试'], query=True) == expected
    assert len(models) == 2
    embedder.close()
    assert embedder.model is None


def test_bounded_excerpt_batches_and_interrupted_index_replay(tmp_path):
    class RecordingEmbedder(TestEmbedder):
        def encode(self, texts, query=False):
            assert len(texts) <= 2
            return super().encode(texts, query)

    settings = Settings(data_dir=tmp_path, preload=False, worker_enabled=False,
        dimensions=16, collection='test', embedding_batch_size=2, index_batch_pause=0)
    lib = Library(settings, RecordingEmbedder())
    try:
        corpus = lib.create_corpus('测试')
        result = import_records(lib, corpus, [
            {'text': f'第{i}段，他说「你好世界」，又说「天气不错」，最后说「一起散步」。'}
            for i in range(5)
        ])
        original_upsert = lib.vectors.upsert
        writes = []

        def interrupt(points):
            assert len(points) <= 2
            writes.extend(p.id for p in points)
            original_upsert(points)
            lib.stop.set()

        lib.vectors.upsert = interrupt
        assert lib.process_one() is False
        with lib.db() as db:
            assert db.get(IngestionJob, result['job_id']).status == 'pending'
            assert db.get(Resource, result['resource_id']).active_generation is None
        lib.stop.clear()

        def record(points):
            assert len(points) <= 2
            writes.extend(p.id for p in points)
            original_upsert(points)

        lib.vectors.upsert = record
        assert lib.process_one()
        with lib.db() as db:
            job = db.get(IngestionJob, result['job_id'])
            assert job.status == 'ready' and job.processed == job.total == 5
            fragments = list(db.scalars(select(Fragment)))
            assert len(fragments) == 5
        assert len(writes) > len(set(writes))  # The interrupted batch was safely replayed.
        assert lib.vectors.client.count('test').count == 20
        assert len(lib.search(corpus, '散步')['results']) == 5
    finally:
        lib.close()
