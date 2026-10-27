import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from test_library import TestEmbedder

ORIGIN = 'https://bible.example.com'
HEADERS = {'Origin': ORIGIN, 'X-Bible-Request': '1'}


@pytest.fixture
def server(tmp_path):
    settings = Settings(data_dir=tmp_path, preload=False, worker_enabled=False,
                        dimensions=16, collection='test', deployment='server', public_origin=ORIGIN)
    with TestClient(create_app(settings, TestEmbedder()), base_url=ORIGIN) as client:
        yield client


def test_server_configuration_validation():
    for origin in ['', 'bible.example.com', 'https://bible.example.com/path',
                   'https://user:pass@bible.example.com', 'https://bible.example.com?query=1']:
        with pytest.raises(ValueError):
            create_app(Settings(deployment='server', public_origin=origin))
    with pytest.raises(ValueError):
        Settings(deployment='typo').validate()
    Settings(deployment='server', public_origin='http://127.0.0.1:5173').validate()


def test_open_shared_library_without_login(server):
    assert server.get('/api/health').json()['deployment'] == 'server'
    assert server.get('/api/corpora').json() == []
    response = server.post('/api/corpora', headers=HEADERS, json={'name': '共享语料'})
    assert response.status_code == 201
    assert 'set-cookie' not in response.headers
    corpus = response.json()['corpus_id']
    url = f'/api/corpora/{corpus}'
    uploaded = server.post(url + '/resources', headers=HEADERS,
                           files={'file': ('example.txt', '请给我水喝。\n愿你平安。'.encode())})
    assert uploaded.status_code == 202
    server.app.state.library.process_one()
    server.cookies.clear()  # A different anonymous browser has the same access.
    assert server.get('/api/corpora').json()[0]['corpus_id'] == corpus
    results = server.post('/api/search', headers=HEADERS,
                          json={'corpus_id': corpus, 'query': '水'}).json()['results']
    assert len(results) == 2
    assert server.get(url + '/context', params={'fragment_id': results[0]['fragment_id']}).status_code == 200
    assert server.get(url + '/resources').status_code == 200
    assert server.delete(url, headers=HEADERS).status_code == 200
    assert server.get('/api/corpora').json() == []
    assert server.post(url + '/restore', headers=HEADERS).status_code == 410
    assert server.get('/api/corpora').json() == []


def test_server_origin_check_and_explicit_api_requests(server):
    for origin in ['https://unrelated.example', 'null', 'http://127.0.0.1:5173']:
        response = server.post('/api/corpora', headers={**HEADERS, 'Origin': origin}, json={'name': 'cross-site'})
        assert response.status_code == 403
    assert server.post('/api/corpora', json={'name': 'form-submit'}).status_code == 403
    # API clients do not need a login or Origin; the marker is public, not a credential.
    assert server.post('/api/corpora', headers={'X-Bible-Request': '1'}, json={'name': 'api-client'}).status_code == 201
    response = server.get('/api/corpora')
    assert len(response.json()) == 1
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert server.get('/api/missing').status_code == 404


def test_config_generator_preserves_existing_file(tmp_path, monkeypatch):
    from scripts import configure_server
    monkeypatch.setattr(configure_server, 'ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['configure_server.py', '--origin', ORIGIN, '--port', '8100'])
    configure_server.main()
    config = (tmp_path / '.env').read_text()
    assert f'PUBLIC_ORIGIN={ORIGIN}' in config and 'PORT=8100' in config
    assert 'PASSWORD' not in config
    with pytest.raises(SystemExit):
        configure_server.main()
    assert (tmp_path / '.env').read_text() == config
