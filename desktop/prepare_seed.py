"""Build a clean Bible-only library, optionally reusing verified project vectors.

SQLite backups are taken through SQLite itself, so a running preview can keep
its files open. Only vectors matching newly parsed built-in fragments are copied.
"""
import json
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from qdrant_client import QdrantClient, models
from sqlalchemy import select
from backend.config import Settings
from backend.models import Fragment, IngestionJob, Resource
from backend.parsers import index_spans
from backend.service import Library
from backend.vectors import VectorStore


def snapshot_database(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def main():
    target = ROOT / 'build' / 'bible-seed'
    if target.exists():
        raise RuntimeError('build/bible-seed already exists; preserve or rename it before rebuilding.')
    snapshot = ROOT / 'build' / ('source-snapshot-' + uuid.uuid4().hex[:8])
    snapshot.mkdir(parents=True)
    source = ROOT / 'data'
    snapshot_database(source / 'library.sqlite3', snapshot / 'library.sqlite3')
    for file in (source / 'qdrant').rglob('*'):
        relative = file.relative_to(source / 'qdrant')
        destination = snapshot / 'qdrant' / relative
        if file.is_file() and file.suffix == '.sqlite':
            snapshot_database(file, destination)
        elif file.is_file() and file.name == 'meta.json':
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, destination)
    cached = VectorStore(Settings(data_dir=snapshot, preload=False, worker_enabled=False)).client
    database = sqlite3.connect(snapshot / 'library.sqlite3')
    database.row_factory = sqlite3.Row
    lib = Library(Settings(data_dir=target, preload=False, worker_enabled=False))
    copied, encoded = 0, 0
    try:
        lib.bootstrap()
        with lib.db() as db:
            resources = list(db.scalars(select(Resource).order_by(Resource.created_at)))
        for resource in resources:
            old = database.execute('SELECT * FROM resources WHERE resource_id=? AND content_hash=? AND source_type=?',
                (resource.resource_id, resource.content_hash, 'builtin_bible')).fetchone()
            with lib.db() as db:
                job = db.scalar(select(IngestionJob).where(IngestionJob.resource_id == resource.resource_id))
                fragments = list(db.scalars(select(Fragment).where(Fragment.resource_id == resource.resource_id)))
            expected = {(f.fragment_id, a, b) for f in fragments for a, b in index_spans(f.text)}
            points = []
            if old and old['active_generation']:
                offset = None
                while True:
                    batch, offset = cached.scroll(lib.settings.collection,
                        scroll_filter=models.Filter(must=[models.FieldCondition(key='generation',
                            match=models.MatchValue(value=old['active_generation']))]),
                        limit=512, offset=offset, with_vectors=True)
                    points.extend(batch)
                    if offset is None:
                        break
            actual = {(p.payload['fragment_id'], p.payload['start'], p.payload['end']) for p in points}
            if actual == expected and len(points) == len(expected):
                rewritten = [models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL,
                    f'{job.job_id}:{p.payload["fragment_id"]}:{p.payload["start"]}:{p.payload["end"]}')),
                    vector=p.vector, payload={**p.payload, 'generation': job.job_id}) for p in points]
                for i in range(0, len(rewritten), 512):
                    lib.vectors.upsert(rewritten[i:i+512])
                with lib.db.begin() as db:
                    db.get(Resource, resource.resource_id).active_generation = job.job_id
                    done = db.get(IngestionJob, job.job_id)
                    done.status, done.processed = 'ready', len(fragments)
                copied += 1
                print(f'{copied + encoded}/66 {resource.title}: verified cached vectors', flush=True)
            else:
                encoded += 1
                print(f'{resource.title}: scheduled fresh indexing', flush=True)
        while lib.process_one():
            print('Indexing remaining Bible resource', flush=True)
        corpora = lib.list_corpora()
        assert len(corpora) == 1 and corpora[0]['corpus_id'] == 'corpus_cuv', corpora
        assert corpora[0]['fragment_count'] == 31100 and corpora[0]['indexed_resources'] == 66, corpora
        assert corpora[0]['failed_jobs'] == 0, corpora
        report = {'corpora': corpora, 'cached_books': copied, 'reencoded_books': encoded, 'private_corpora_included': False}
        (ROOT / 'build' / 'seed-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        lib.close()
        cached.close()
        database.close()
    # Keep snapshot outside release for diagnosis; never include it in the archive.


if __name__ == '__main__':
    main()
