import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.config import ROOT, Settings
from backend.main import create_app
from backend.models import Fragment, IngestionJob, Resource, ResourceVersion
from backend.parsers import index_spans, parse_records, parse_upload
from backend.service import Library


def test_collection_rename_preserves_existing_vectors(tmp_path):
    legacy = Library(Settings(data_dir=tmp_path, preload=False, worker_enabled=False,
        dimensions=16, collection='youyan_bge_small_zh_v1'), embedder=TestEmbedder())
    corpus = legacy.create_corpus('迁移验证')
    text, fragments = parse_records([{'text': '请给我水喝。'}], '迁移验证')
    legacy.import_parsed(corpus, '迁移验证', text, fragments)
    assert legacy.process_one()
    legacy.close()
    renamed = Library(Settings(data_dir=tmp_path, preload=False, worker_enabled=False,
        dimensions=16), embedder=TestEmbedder())
    try:
        assert renamed.search(corpus, '喝水')['results'][0]['text'] == '请给我水喝。'
    finally:
        renamed.close()


class TestEmbedder:
    """Deterministic test double; production always uses a neural embedding model."""
    __test__ = False
    def encode(self, texts, query=False):
        vectors = []
        for text in texts:
            vector = [0.0] * 16
            for char in text:
                vector[ord(char) % 16] += 1
            vectors.append(vector)
        return vectors


@pytest.fixture
def library(tmp_path):
    settings = Settings(data_dir=tmp_path, preload=False, worker_enabled=False, dimensions=16, collection='test')
    lib = Library(settings, TestEmbedder())
    yield lib
    lib.close()


def import_records(lib, corpus, records, title='随笔'):
    text, parts = parse_records(records, title)
    return lib.import_parsed(corpus, title, text, parts)


def test_default_fifty_and_no_scores(library):
    corpus = library.create_corpus('测试')
    import_records(library, corpus, [{'text': f'第{i}段文字，我想喝水。'} for i in range(70)])
    assert library.process_one()
    result = library.search(corpus, '我想喝水')
    assert len(result['results']) == 50
    assert [r['rank'] for r in result['results']] == list(range(1, 51))
    assert all('score' not in r and 'similarity' not in r for r in result['results'])


def test_small_corpus_is_complete_and_isolated(library):
    small, other = library.create_corpus('小语料'), library.create_corpus('另一个')
    imported = import_records(library, small, [{'text': '你要去哪里？'}, {'text': '请给我水喝。'}])
    import_records(library, other, [{'text': '不应泄露的另一份语料'}])
    while library.process_one():
        pass
    results = library.search(small, '喝水')['results']
    assert len(results) == 2
    assert all(r['resource_id'] == imported['resource_id'] for r in results)
    library.delete_resource(small, imported['resource_id'])
    assert library.search(small, '喝水')['results'] == []
    with pytest.raises(LookupError):
        library.context(other, results[0]['fragment_id'])


def test_index_publication_retry_and_duplicate(library):
    corpus = library.create_corpus('测试')
    records = [{'text': '耶稣说：「请你给我水喝。」'}]
    imported = import_records(library, corpus, records)
    duplicate = import_records(library, corpus, records)
    assert duplicate['duplicate'] and duplicate['resource_id'] == imported['resource_id']
    assert library.search(corpus, '水')['results'] == []
    library.process_one()
    original_results = library.search(corpus, '水')['results']
    assert len(original_results) == 1
    library.reindex(corpus, imported['resource_id'])
    assert library.search(corpus, '水')['results'] == original_results
    original_encoder = library.embedder
    class Broken:
        def encode(self, *args, **kwargs):
            raise RuntimeError('injected interruption')
    library.embedder = Broken()
    library.process_one()
    library.embedder = original_encoder
    assert library.search(corpus, '水')['results'] == original_results
    library.reindex(corpus, imported['resource_id'])
    library.process_one()
    assert len(library.search(corpus, '水')['results']) == 1


def test_offsets_quotes_and_context(library):
    corpus = library.create_corpus('测试')
    original = '# 标题\r\n第一句😀。第二句，保留空格。\r\n他说：「你要去哪里？」'
    text, parts = parse_upload(original.encode(), '测试.md')
    assert text == original
    imported = library.import_parsed(corpus, '测试.md', text, parts)
    with library.db() as db:
        for fragment in db.scalars(select(Fragment)):
            version = db.get(ResourceVersion, fragment.version_id)
            assert version.text[fragment.start_offset:fragment.end_offset] == fragment.text
    assert [(original[a:b]) for a, b in index_spans(original)][1] == '你要去哪里？'
    library.process_one()
    result = library.search(corpus, '去哪里')['results'][0]
    context = library.context(corpus, result['fragment_id'])
    assert any(part['selected'] for part in context)
    assert result['text'] in result['full_text']


def test_api_validation_and_preview(tmp_path):
    settings = Settings(data_dir=tmp_path, preload=False, worker_enabled=False, dimensions=16, collection='test')
    with TestClient(create_app(settings, TestEmbedder())) as client:
        corpus = client.post('/api/corpora', json={'name': '上传测试'}).json()['corpus_id']
        url = f'/api/corpora/{corpus}'
        preview = client.post(url + '/preview', files={'file': ('sample.txt', '甲\n乙'.encode())})
        assert preview.status_code == 200 and preview.json()['count'] == 2
        assert client.get(url + '/resources').json() == []
        assert client.post(url + '/resources', files={'file': ('sample.txt', '甲\n乙'.encode())}).status_code == 202
        client.app.state.library.process_one()
        assert len(client.post('/api/search', json={'query': '甲', 'corpus_id': corpus}).json()['results']) == 2
        assert client.post('/api/search', json={'query': '  ', 'corpus_id': corpus}).status_code == 422
        assert client.post('/api/search', json={'query': '甲', 'corpus_id': corpus, 'top_k': 101}).status_code == 422
        assert client.post(url + '/resources', files={'file': ('bad.json', b'{')}).status_code == 422
        assert client.post(url + '/resources', files={'file': ('bad.txt', b'\xff\xfe')}).status_code == 422
        assert client.post('/api/corpora', json={'name': '跨站'}, headers={'Origin': 'https://unrelated.example'}).status_code == 403
        assert client.get('/api/missing').status_code == 404


def test_bundled_corpus_provenance():
    raw = (ROOT / 'resources/cuv.jsonl').read_bytes()
    manifest = json.loads((ROOT / 'resources/manifest.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(raw).hexdigest() == manifest['corpus_sha256']
    records = [json.loads(line) for line in raw.decode().splitlines()]
    assert len(records) == 31100
    assert len({r['citation']['book'] for r in records}) == 66
    assert len({(r['citation']['book'], r['citation']['chapter'], r['citation']['verse_start']) for r in records}) == 31100
    john = next(r for r in records if r['citation']['book'] == 'JHN' and r['citation']['chapter'] == 4 and r['citation']['verse_start'] == 7)
    assert '请你给我水喝' in john['text']


def test_reupload_after_hard_delete_creates_new_job(library):
    corpus = library.create_corpus('测试')
    records = [{'text': '请给我一杯水。'}]
    original = import_records(library, corpus, records)
    library.delete_resource(corpus, original['resource_id'])
    assert not library.process_one()
    restored = import_records(library, corpus, records)
    assert restored['resource_id'] == original['resource_id']
    assert restored['job_id'] != original['job_id']
    assert library.process_one()
    assert len(library.search(corpus, '喝水')['results']) == 1


def test_corpus_hard_deletion_and_reader(tmp_path):
    settings = Settings(data_dir=tmp_path, preload=False, worker_enabled=False, dimensions=16, collection='test')
    with TestClient(create_app(settings, TestEmbedder())) as client:
        lib = client.app.state.library
        corpus = lib.create_corpus('可删除的语料库')
        other = lib.create_corpus('保留的语料库')
        record = import_records(lib, corpus, [{'text': f'原文第{i}段'} for i in range(55)])
        lib.process_one()
        pending = import_records(lib, corpus, [{'text': '等待索引的原文'}], title='待处理')
        untouched = import_records(lib, other, [{'text': '另一个语料库'}])
        url = f'/api/corpora/{corpus}'
        content_url = url + f'/resources/{record["resource_id"]}/content'
        first = client.get(content_url).json()
        assert first['total'] == 55 and len(first['fragments']) == 50
        last = client.get(content_url + '?offset=50').json()
        assert len(last['fragments']) == 5 and last['fragments'][0]['text'] == '原文第50段'
        assert client.get(content_url + '?offset=-1').status_code == 422
        assert client.get(f'/api/corpora/{other}/resources/{record["resource_id"]}/content').status_code == 404
        assert client.delete(url).status_code == 200
        assert [c['corpus_id'] for c in client.get('/api/corpora').json()] == [other]
        assert client.get('/api/corpora/archived').json() == []
        assert client.get(content_url).status_code == 404
        assert client.post('/api/search', json={'corpus_id': corpus, 'query': '原文'}).status_code == 404
        with lib.db() as db:
            assert db.get(IngestionJob, pending['job_id']) is None
            assert db.get(IngestionJob, untouched['job_id']).status == 'pending'
        assert client.post(url + '/restore').status_code == 410
        assert client.get('/api/corpora/archived').json() == []
        with lib.db() as db:
            assert db.get(IngestionJob, pending['job_id']) is None
        assert client.delete('/api/corpora/missing').status_code == 404


def test_deleted_builtin_stays_deleted_after_restart(tmp_path):
    settings = Settings(data_dir=tmp_path, preload=False, worker_enabled=False, dimensions=16, collection='test')
    lib = Library(settings, TestEmbedder())
    lib.create_corpus('圣经', builtin=True, corpus_id='corpus_cuv')
    lib.delete_corpus('corpus_cuv')
    lib.close()
    lib = Library(settings, TestEmbedder())
    try:
        lib.bootstrap()
        assert lib.list_corpora() == []
        assert lib.archived_corpora() == []
    finally:
        lib.close()
