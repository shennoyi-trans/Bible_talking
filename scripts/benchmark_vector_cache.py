"""Measure lazy vector caching with an isolated synthetic Qdrant store.

First run --prepare with a NEW --data-dir, then run each measurement in a
separate process, once with --baseline and once without. No model is loaded.
"""
import argparse
import json
import math
from pathlib import Path
import pickle
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import Settings
from backend.vectors import VectorStore
from scripts.benchmark_embedding_memory import memory_mib


def prepare(path, count):
    # Refuse existing directories, including all real application data stores.
    path.mkdir(parents=True, exist_ok=False)
    from qdrant_client import QdrantClient, models
    from qdrant_client.local.persistence import CollectionPersistence

    client = QdrantClient(path=str(path / 'qdrant'))
    client.create_collection('cache_benchmark', vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE))
    client.close()
    # Fixture-only bulk insertion avoids one fsync per synthetic point. The
    # record format is the installed client's own PointStruct serialization.
    storage = path / 'qdrant' / 'collection' / 'cache_benchmark' / 'storage.sqlite'
    assert storage.is_file()
    vector = [1 / math.sqrt(512)] * 512
    with sqlite3.connect(storage) as db:
        for start in range(0, count, 256):
            rows = []
            for i in range(start, min(start + 256, count)):
                point = models.PointStruct(id=i, vector=vector, payload={
                    'generation': 'cache-test', 'fragment_id': f'res_{i:032x}:' + 'a' * 64 + ':f0',
                    'start': 0, 'end': 40})
                rows.append((CollectionPersistence.encode_key(i), sqlite3.Binary(pickle.dumps(point))))
            db.executemany('INSERT INTO points VALUES (?, ?)', rows)
    print(json.dumps({'prepared_points': count, 'data_dir': str(path)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--points', type=int, default=20000)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.prepare:
        if args.points < 1:
            parser.error('--points must be positive')
        prepare(args.data_dir.resolve(), args.points)
        return
    if not args.output:
        parser.error('--output is required for measurement')
    storage = args.data_dir / 'qdrant' / 'collection' / 'cache_benchmark' / 'storage.sqlite'
    if not storage.is_file():
        parser.error('prepare the synthetic store first')
    settings = Settings(data_dir=args.data_dir, qdrant_url='', collection='cache_benchmark', preload=False)
    report = {'mode': 'eager-baseline' if args.baseline else 'lazy-cache', 'platform': sys.platform,
              'before': memory_mib()}
    store = VectorStore(settings)
    try:
        if args.baseline:
            store.client  # Reproduce the previous eager initialization.
        report['startup'] = memory_mib()
        start = time.monotonic()
        hits = store.search([1 / math.sqrt(512)] * 512, ['cache-test'], 20)
        report['first_query_seconds'] = round(time.monotonic() - start, 3)
        report['after_query'] = memory_mib()
        start = time.monotonic()
        warm_hits = store.search([1 / math.sqrt(512)] * 512, ['cache-test'], 20)
        report['cached_query_seconds'] = round(time.monotonic() - start, 3)
        assert [p.id for p in warm_hits] == [p.id for p in hits]
        if not args.baseline:
            store.last_used -= settings.vector_cache_idle_seconds + 1
            store.release_if_idle()
            assert store._client is None
        report['after_idle'] = memory_mib()
        if not args.baseline:
            reloaded = store.search([1 / math.sqrt(512)] * 512, ['cache-test'], 20)
            assert [p.id for p in reloaded] == [p.id for p in hits]
            store.last_used -= settings.vector_cache_idle_seconds + 1
            store.release_if_idle()
            report['after_second_idle'] = memory_mib()
        report['result_ids'] = [p.id for p in hits]
    finally:
        store.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
