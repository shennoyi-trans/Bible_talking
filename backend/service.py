import hashlib
import json
import logging
import threading
import uuid
from pathlib import Path

from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.orm import sessionmaker
from qdrant_client.models import PointStruct

from .config import ROOT
from .models import Base, Corpus, CorpusArchive, CorpusResource, Fragment, IngestionJob, Resource, ResourceVersion
from .parsers import index_spans, parse_records
from .vectors import Embedder, VectorStore

log = logging.getLogger(__name__)


def uid(prefix):
    return f'{prefix}_{uuid.uuid4().hex}'


class Library:
    def __init__(self, settings, embedder=None):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f'sqlite:///{settings.data_dir / "library.sqlite3"}', connect_args={'check_same_thread': False, 'timeout': 30})
        @event.listens_for(self.engine, 'connect')
        def configure(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(self.engine, expire_on_commit=False)
        self.vectors = VectorStore(settings)
        self.embedder = embedder or Embedder(settings)
        self.stop = threading.Event()
        self.wakeup = threading.Event()
        self.mutation = threading.RLock()
        self.worker = None
        with self.db.begin() as db:
            db.execute(update(IngestionJob).where(IngestionJob.status == 'processing').values(status='pending'))

    def create_corpus(self, name, description='', builtin=False, corpus_id=None):
        with self.db.begin() as db:
            corpus = Corpus(corpus_id=corpus_id or uid('corpus'), name=name, description=description, builtin=builtin)
            db.add(corpus)
        return corpus.corpus_id

    def require_corpus(self, db, corpus_id):
        corpus = db.get(Corpus, corpus_id)
        if not corpus or corpus.owner_user_id != 1 or db.get(CorpusArchive, corpus_id):
            raise LookupError('语料库不存在。')
        return corpus

    def resource_rows(self, db, corpus_id):
        self.require_corpus(db, corpus_id)
        return list(db.scalars(select(Resource).join(CorpusResource).where(
            CorpusResource.corpus_id == corpus_id, Resource.owner_user_id == 1, Resource.visibility == 'active').order_by(Resource.created_at)))

    def import_parsed(self, corpus_id, title, source_text, fragments, source_type='upload', source_ref=None, raw=None):
        if not fragments:
            raise ValueError('文件中没有可切分的正文。')
        if len(fragments) > 50000:
            raise ValueError('单个文件最多包含 50,000 个片段，请分批上传。')
        digest = hashlib.sha256(source_text.encode()).hexdigest()
        identity = hashlib.sha256(json.dumps([title, digest, [f.citation for f in fragments]], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        resource_id = 'res_' + hashlib.sha256(f'{corpus_id}:{identity}'.encode()).hexdigest()[:32]
        version_id = f'{resource_id}:{digest}'
        with self.mutation, self.db.begin() as db:
            self.require_corpus(db, corpus_id)
            existing = db.get(Resource, resource_id)
            if existing:
                existing.visibility = 'active'
                job = db.scalar(select(IngestionJob).where(IngestionJob.resource_id == resource_id).order_by(IngestionJob.created_at.desc()))
                if not existing.active_generation and job.status in {'failed', 'cancelled'}:
                    job = IngestionJob(job_id=uid('idx'), resource_id=resource_id, version_id=version_id,
                        total=len(fragments), model=self.settings.embedding_revision)
                    db.add(job)
                    self.wakeup.set()
                return {'resource_id': resource_id, 'job_id': job.job_id, 'duplicate': True}
            resource = Resource(resource_id=resource_id, title=title, source_type=source_type,
                source_ref_id=source_ref or title, content_hash=digest, version_id=version_id,
                meta={'language': 'zh', 'offset_unit': 'unicode_codepoint', 'offset_interval': '[start,end)'})
            db.add(resource)
            db.flush()
            db.add(CorpusResource(corpus_id=corpus_id, resource_id=resource_id))
            db.add(ResourceVersion(version_id=version_id, resource_id=resource_id, text=source_text, content_hash=digest))
            db.flush()
            for i, part in enumerate(fragments):
                if source_text[part.start:part.end] != part.text:
                    raise ValueError('片段位置与原文不一致。')
                db.add(Fragment(fragment_id=f'{version_id}:f{i}', resource_id=resource_id, version_id=version_id,
                    fragment_index=i, text=part.text, start_offset=part.start, end_offset=part.end, citation=part.citation))
            job = IngestionJob(job_id=uid('idx'), resource_id=resource_id, version_id=version_id,
                total=len(fragments), model=self.settings.embedding_revision)
            db.add(job)
            if raw is not None:
                folder = self.settings.data_dir / 'originals'
                folder.mkdir(exist_ok=True)
                (folder / f'{resource_id}.source').write_bytes(raw)
        self.wakeup.set()
        return {'resource_id': resource_id, 'job_id': job.job_id, 'duplicate': False}

    def bootstrap(self):
        corpus_id = 'corpus_cuv'
        with self.db() as db:
            exists = db.get(Corpus, corpus_id)
            if db.get(CorpusArchive, corpus_id):
                return
        if not exists:
            self.create_corpus('圣经 · 和合本', '简体中文和合本。按卷、章、节保留出处；支持查看上下文。', True, corpus_id)
        source = ROOT / 'resources' / 'cuv.jsonl'
        books = {}
        for line in source.read_text(encoding='utf-8').splitlines():
            item = json.loads(line)
            books.setdefault(item['citation']['book'], []).append(item)
        # New Testament first so conversational examples become available early.
        preferred = ['JHN', 'MAT', 'LUK', 'MRK']
        ordered = [key for key in preferred if key in books] + [key for key in books if key not in preferred]
        for key in ordered:
            with self.db() as db:
                if db.scalar(select(Resource).where(Resource.source_type == 'builtin_bible', Resource.source_ref_id == f'cuv:{key}')):
                    continue
            records = books[key]
            title = records[0]['citation']['book_name']
            text, fragments = parse_records(records, title)
            self.import_parsed(corpus_id, title, text, fragments, 'builtin_bible', f'cuv:{key}')

    def list_corpora(self):
        with self.db() as db:
            result = []
            for corpus in db.scalars(select(Corpus).where(Corpus.owner_user_id == 1,
                    ~Corpus.corpus_id.in_(select(CorpusArchive.corpus_id))).order_by(Corpus.created_at)):
                resources = self.resource_rows(db, corpus.corpus_id)
                ids = [r.resource_id for r in resources]
                count = db.scalar(select(func.count()).select_from(Fragment).where(Fragment.resource_id.in_(ids)))
                jobs = list(db.scalars(select(IngestionJob).where(IngestionJob.resource_id.in_(ids))))
                active = sum(bool(r.active_generation) for r in resources)
                result.append({'corpus_id': corpus.corpus_id, 'name': corpus.name, 'description': corpus.description,
                    'builtin': corpus.builtin, 'resource_count': len(ids), 'fragment_count': count,
                    'indexed_resources': active, 'pending_jobs': sum(j.status in ('pending', 'processing') for j in jobs),
                    'failed_jobs': sum(j.status == 'failed' for j in jobs)})
            return result

    def archived_corpora(self):
        with self.db() as db:
            return [{'corpus_id': c.corpus_id, 'name': c.name} for c in db.scalars(
                select(Corpus).join(CorpusArchive).where(Corpus.owner_user_id == 1).order_by(CorpusArchive.created_at.desc()))]

    def archive_corpus(self, corpus_id):
        with self.mutation, self.db.begin() as db:
            self.require_corpus(db, corpus_id)
            db.add(CorpusArchive(corpus_id=corpus_id))
            # Keep original data and vectors for recovery; archived corpora cannot be queried.
            ids = select(CorpusResource.resource_id).where(CorpusResource.corpus_id == corpus_id)
            db.execute(update(IngestionJob).where(IngestionJob.resource_id.in_(ids),
                IngestionJob.status == 'pending').values(status='cancelled'))

    def restore_corpus(self, corpus_id):
        with self.mutation, self.db.begin() as db:
            corpus, archived = db.get(Corpus, corpus_id), db.get(CorpusArchive, corpus_id)
            if not corpus or corpus.owner_user_id != 1 or not archived:
                raise LookupError('已删除的语料库不存在。')
            db.delete(archived)
            ids = select(Resource.resource_id).join(CorpusResource).where(
                CorpusResource.corpus_id == corpus_id, Resource.visibility == 'active')
            db.execute(update(IngestionJob).where(IngestionJob.resource_id.in_(ids),
                IngestionJob.status == 'cancelled').values(status='pending'))
        self.wakeup.set()

    def resource_content(self, corpus_id, resource_id, offset=0, limit=50):
        with self.db() as db:
            resources = {r.resource_id: r for r in self.resource_rows(db, corpus_id)}
            if resource_id not in resources:
                raise LookupError('资源不存在。')
            resource = resources[resource_id]
            total = db.scalar(select(func.count()).select_from(Fragment).where(Fragment.version_id == resource.version_id))
            parts = db.scalars(select(Fragment).where(Fragment.version_id == resource.version_id)
                .order_by(Fragment.fragment_index).offset(offset).limit(limit))
            return {'title': resource.title, 'total': total, 'offset': offset,
                'fragments': [{'fragment_id': f.fragment_id, 'text': f.text, 'citation': f.citation} for f in parts]}

    def list_resources(self, corpus_id):
        with self.db() as db:
            result = []
            for resource in self.resource_rows(db, corpus_id):
                job = db.scalar(select(IngestionJob).where(IngestionJob.resource_id == resource.resource_id).order_by(IngestionJob.created_at.desc()))
                result.append({'resource_id': resource.resource_id, 'title': resource.title,
                    'indexed': bool(resource.active_generation), 'job': self.job_dict(job)})
            return result

    @staticmethod
    def job_dict(job):
        return {key: getattr(job, key) for key in ('job_id', 'status', 'processed', 'total', 'error', 'attempts')}

    def reindex(self, corpus_id, resource_id):
        with self.mutation, self.db.begin() as db:
            resources = {r.resource_id: r for r in self.resource_rows(db, corpus_id)}
            if resource_id not in resources:
                raise LookupError('资源不存在。')
            pending = db.scalar(select(IngestionJob).where(IngestionJob.resource_id == resource_id,
                IngestionJob.status.in_(['pending', 'processing'])))
            if pending:
                return self.job_dict(pending)
            resource = resources[resource_id]
            job = IngestionJob(job_id=uid('idx'), resource_id=resource_id, version_id=resource.version_id,
                model=self.settings.embedding_revision, total=db.scalar(select(func.count()).select_from(Fragment).where(Fragment.version_id == resource.version_id)))
            db.add(job)
            db.flush()
            result = self.job_dict(job)
        self.wakeup.set()
        return result

    def archive(self, corpus_id, resource_id):
        with self.mutation, self.db.begin() as db:
            resources = {r.resource_id: r for r in self.resource_rows(db, corpus_id)}
            if resource_id not in resources:
                raise LookupError('资源不存在。')
            resources[resource_id].visibility = 'archived'
            db.execute(update(IngestionJob).where(IngestionJob.resource_id == resource_id,
                IngestionJob.status == 'pending').values(status='cancelled'))

    def process_one(self):
        with self.db.begin() as db:
            job = db.scalar(select(IngestionJob).join(Resource, Resource.resource_id == IngestionJob.resource_id)
                .where(IngestionJob.status == 'pending')
                .order_by((Resource.source_type == 'builtin_bible').asc(), IngestionJob.created_at).limit(1))
            if not job:
                return False
            resource = db.get(Resource, job.resource_id)
            if resource.visibility != 'active':
                job.status = 'cancelled'
                return True
            job.status, job.error = 'processing', None
            job.attempts += 1
            fragments = list(db.scalars(select(Fragment).where(Fragment.version_id == job.version_id).order_by(Fragment.fragment_index)))
        try:
            # Replayed batches are idempotent; a generation is invisible until committed.
            for start in range(0, len(fragments), 64):
                if self.stop.is_set():
                    with self.db.begin() as db:
                        db.get(IngestionJob, job.job_id).status = 'pending'
                    return False
                with self.db() as db:
                    if db.get(Resource, job.resource_id).visibility != 'active':
                        raise ValueError('资源已归档，导入已停止。')
                items = [(f, a, b) for f in fragments[start:start+64] for a, b in index_spans(f.text)]
                embeddings = self.embedder.encode([f.text[a:b] for f, a, b in items])
                points = [PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, f'{job.job_id}:{f.fragment_id}:{a}:{b}')),
                    vector=vector, payload={'generation': job.job_id, 'fragment_id': f.fragment_id,
                    'start': a, 'end': b}) for (f, a, b), vector in zip(items, embeddings, strict=True)]
                self.vectors.upsert(points)
                with self.db.begin() as db:
                    db.get(IngestionJob, job.job_id).processed = min(start + 64, len(fragments))
            with self.mutation, self.db.begin() as db:
                resource = db.get(Resource, job.resource_id)
                current = db.get(IngestionJob, job.job_id)
                if resource.visibility == 'active' and resource.version_id == job.version_id:
                    old_generation = resource.active_generation
                    resource.active_generation, current.status = job.job_id, 'ready'
                else:
                    old_generation, current.status = job.job_id, 'cancelled'
            if old_generation and old_generation != resource.active_generation:
                try:
                    self.vectors.delete_generation(old_generation)
                except Exception:
                    log.exception('Old generation cleanup failed; it remains excluded from search')
        except Exception as exc:
            log.exception('Indexing failed: %s', job.resource_id)
            with self.db.begin() as db:
                current = db.get(IngestionJob, job.job_id)
                current.status, current.error = 'failed', str(exc)[:1000]
        return True

    def start_worker(self):
        def run():
            while not self.stop.is_set():
                try:
                    if self.process_one():
                        continue
                except Exception:
                    log.exception('Worker failed')
                self.wakeup.wait(2)
                self.wakeup.clear()
        self.worker = threading.Thread(target=run, daemon=True, name='corpus-indexer')
        self.worker.start()

    def search(self, corpus_id, query, top_k=50):
        with self.db() as db:
            resources = self.resource_rows(db, corpus_id)
            generations = [r.active_generation for r in resources if r.active_generation]
        if not generations:
            return {'results': [], 'indexing': bool(resources), 'query': query, 'top_k': top_k}
        vector = self.embedder.encode([query], query=True)[0]
        # Retrieve enough distinct fragments when passage/excerpt points overlap.
        limit = top_k * 4
        with self.mutation:
            with self.db() as db:
                resources = self.resource_rows(db, corpus_id)
                allowed = {r.resource_id: r for r in resources}
                generations = [r.active_generation for r in resources if r.active_generation]
                points = self.vectors.search(vector, generations, limit)
                while len({p.payload['fragment_id'] for p in points}) < top_k and len(points) == limit:
                    limit *= 2
                    points = self.vectors.search(vector, generations, limit)
                hits, seen = [], set()
                for point in points:
                    payload = point.payload
                    fragment = db.get(Fragment, payload['fragment_id'])
                    if not fragment or fragment.resource_id not in allowed or fragment.fragment_id in seen:
                        continue
                    resource = allowed[fragment.resource_id]
                    if resource.active_generation != payload['generation']:
                        continue
                    seen.add(fragment.fragment_id)
                    text = fragment.text[payload['start']:payload['end']]
                    hits.append({'rank': len(hits) + 1, 'fragment_id': fragment.fragment_id,
                        'resource_id': fragment.resource_id, 'version_id': fragment.version_id,
                        'text': text, 'full_text': fragment.text, 'is_excerpt': text != fragment.text,
                        'citation': fragment.citation, 'title': resource.title,
                        'copy_text': f'“{text}”（{fragment.citation["label"]}）'})
                    if len(hits) == top_k:
                        break
                return {'results': hits, 'indexing': any(not r.active_generation for r in resources), 'query': query, 'top_k': top_k}

    def context(self, corpus_id, fragment_id):
        with self.db() as db:
            resources = {r.resource_id for r in self.resource_rows(db, corpus_id)}
            fragment = db.get(Fragment, fragment_id)
            if not fragment or fragment.resource_id not in resources:
                raise LookupError('片段不存在。')
            neighbors = db.scalars(select(Fragment).where(Fragment.version_id == fragment.version_id,
                Fragment.fragment_index.between(fragment.fragment_index - 1, fragment.fragment_index + 1)).order_by(Fragment.fragment_index))
            return [{'text': f.text, 'citation': f.citation, 'selected': f.fragment_id == fragment_id} for f in neighbors]

    def close(self):
        self.stop.set()
        self.wakeup.set()
        if self.worker:
            self.worker.join(timeout=30)
            if self.worker.is_alive():
                return  # Process teardown will release handles after the in-flight batch.
        self.vectors.close()
        self.engine.dispose()
