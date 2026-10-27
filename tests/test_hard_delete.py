import threading

import pytest
from sqlalchemy import func, select

from backend.config import Settings
from backend.models import BuiltinExclusion, Corpus, CorpusArchive, CorpusResource, Fragment, IngestionJob, PendingDeletion, Resource, ResourceVersion
from backend.parsers import parse_records
from backend.service import DeletionPending, Library
from test_library import TestEmbedder, import_records, library


def assert_resource_removed(lib, resource_id):
    with lib.db() as db:
        assert db.get(Resource, resource_id) is None
        for table in (CorpusResource, Fragment, ResourceVersion, IngestionJob):
            assert db.scalar(select(func.count()).select_from(table).where(table.resource_id == resource_id)) == 0
        assert db.get(PendingDeletion, resource_id) is None
    assert not (lib.settings.data_dir / 'originals' / f'{resource_id}.source').exists()


def test_delete_cleans_all_generations_originals_and_local_vector_slots(library):
    corpus = library.create_corpus('删除测试')
    other = library.create_corpus('保留测试')
    untouched = import_records(library, other, [{'text': '保留的原文'}])
    text, fragments = parse_records([{'text': '将被删除的原文'}], '删除测试')
    imported = library.import_parsed(corpus, '删除测试', text, fragments, raw=b'original file')
    while library.process_one():
        pass
    # A failed reindex can have already written points. It must be cleaned too.
    library.reindex(corpus, imported['resource_id'])
    upsert = library.vectors.upsert

    def fail_after_write(points):
        upsert(points)
        raise RuntimeError('failure after persisting vectors')

    library.vectors.upsert = fail_after_write
    library.process_one()
    library.vectors.upsert = upsert
    assert library.vectors.client.count('test').count == 3
    with pytest.raises(LookupError):
        library.delete_resource(other, imported['resource_id'])
    library.delete_resource(corpus, imported['resource_id'])
    assert_resource_removed(library, imported['resource_id'])
    assert library.vectors.client.count('test').count == 1
    local = library.vectors.client._client.collections['test']
    assert len(local.payload) == 1 and int(local.deleted.sum()) == 0
    assert len(local.vectors['']) == 1
    assert library.search(other, '原文')['results'][0]['resource_id'] == untouched['resource_id']


def test_legacy_archive_is_retained_until_explicit_hard_delete(library):
    corpus = library.create_corpus('旧版归档')
    imported = import_records(library, corpus, [{'text': '旧版原文'}])
    library.process_one()
    with library.db.begin() as db:
        db.add(CorpusArchive(corpus_id=corpus))
        db.get(Resource, imported['resource_id']).visibility = 'archived'
    assert library.archived_corpora()[0]['corpus_id'] == corpus
    library.delete_corpus(corpus)
    assert library.archived_corpora() == []
    assert_resource_removed(library, imported['resource_id'])
    with library.db() as db:
        assert db.get(Corpus, corpus) is None
        assert db.get(CorpusArchive, corpus) is None
    assert library.vectors.client.count('test').count == 0


def test_failed_cleanup_is_retryable_after_restart(tmp_path):
    settings = Settings(data_dir=tmp_path, preload=False, worker_enabled=False, dimensions=16, collection='test')
    lib = Library(settings, TestEmbedder())
    corpus = lib.create_corpus('可重试删除')
    imported = import_records(lib, corpus, [{'text': '需要删除'}])
    lib.process_one()

    def broken(_):
        raise RuntimeError('temporary vector-store failure')

    lib.vectors.delete_generations = broken
    with pytest.raises(DeletionPending):
        lib.delete_corpus(corpus)
    with lib.db() as db:
        assert db.get(PendingDeletion, corpus) is not None
        assert db.get(Resource, imported['resource_id']).visibility == 'deleting'
    assert lib.list_corpora() == []
    lib.close()
    lib = Library(settings, TestEmbedder())
    try:
        lib.process_deletions()
        assert_resource_removed(lib, imported['resource_id'])
        with lib.db() as db:
            assert db.get(Corpus, corpus) is None
            assert db.get(PendingDeletion, corpus) is None
        assert lib.vectors.client.count('test').count == 0
    finally:
        lib.close()


@pytest.mark.parametrize('whole_corpus', [False, True])
def test_delete_during_inference_never_recreates_vectors(library, whole_corpus):
    corpus = library.create_corpus('并发删除')
    records = [{'text': '正在编码的原文'}]
    imported = import_records(library, corpus, records)
    started, resume = threading.Event(), threading.Event()
    encoder = library.embedder
    outcomes = []

    class Waiting:
        def encode(self, texts, query=False):
            started.set()
            assert resume.wait(10)
            return encoder.encode(texts, query)

    library.embedder = Waiting()
    thread = threading.Thread(target=lambda: outcomes.append(library.process_one()))
    thread.start()
    try:
        assert started.wait(5)
        if whole_corpus:
            library.delete_corpus(corpus)
        else:
            library.delete_resource(corpus, imported['resource_id'])
            # Reupload uses the same resource ID but a new job; old inference must stay invalid.
            new = import_records(library, corpus, records)
            assert new['job_id'] != imported['job_id']
        resume.set()
        thread.join(10)
        assert not thread.is_alive() and outcomes == [False]
        assert library.vectors.client.count('test').count == 0
        if whole_corpus:
            assert_resource_removed(library, imported['resource_id'])
        else:
            library.embedder = encoder
            assert library.process_one()
            assert len(library.search(corpus, '原文')['results']) == 1
    finally:
        resume.set()
        thread.join(10)
        library.embedder = encoder


def test_deleted_builtin_book_is_not_bootstrapped_again(tmp_path, monkeypatch):
    from backend import service
    seed = tmp_path / 'resources'
    seed.mkdir()
    (seed / 'cuv.jsonl').write_text('{"text":"保留出处的原文","citation":{"book":"JHN","book_name":"约翰福音"}}\n', encoding='utf-8')
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    settings = Settings(data_dir=tmp_path / 'library', preload=False, worker_enabled=False, dimensions=16, collection='test')
    lib = Library(settings, TestEmbedder())
    lib.bootstrap()
    rid = lib.list_resources('corpus_cuv')[0]['resource_id']
    lib.delete_resource('corpus_cuv', rid)
    lib.close()
    lib = Library(settings, TestEmbedder())
    try:
        lib.bootstrap()
        assert lib.list_resources('corpus_cuv') == []
        with lib.db() as db:
            assert db.get(BuiltinExclusion, 'cuv:JHN') is not None
        assert_resource_removed(lib, rid)
    finally:
        lib.close()


def test_cleanup_failure_backs_off_and_still_releases_idle_model(library):
    first, second, idle = threading.Event(), threading.Event(), threading.Event()

    def unavailable():
        if first.is_set():
            second.set()
        first.set()
        raise DeletionPending('retry later')

    library.process_deletions = unavailable
    library.embedder.release_if_idle = idle.set
    library.start_worker()
    assert first.wait(5) and idle.wait(5)
    assert not second.wait(0.2)
    library.stop.set()
    library.wakeup.set()
    library.worker.join(5)
    assert not library.worker.is_alive()
