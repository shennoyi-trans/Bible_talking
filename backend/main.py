from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ROOT, Settings
from .parsers import parse_upload
from .service import Library


class CorpusCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=500)


class SearchRequest(BaseModel):
    corpus_id: str
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=50, ge=1, le=100)


def create_app(settings=None, embedder=None):
    settings = settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        library = Library(settings, embedder)
        app.state.library = library
        if settings.preload:
            library.bootstrap()
        if settings.worker_enabled:
            library.start_worker()
        yield
        library.close()

    app = FastAPI(title='Bible_talking · 语料检索', lifespan=lifespan)

    @app.middleware('http')
    async def local_origin(request: Request, call_next):
        # Single-user localhost application. Do not expose without an auth adapter.
        origin = request.headers.get('origin')
        if request.url.path.startswith('/api') and origin:
            from urllib.parse import urlparse
            if urlparse(origin).netloc != request.headers.get('host') and origin not in {'http://127.0.0.1:5173', 'http://localhost:5173'}:
                return JSONResponse({'detail': '不允许此来源访问本地语料库。'}, status_code=403)
        return await call_next(request)

    @app.exception_handler(LookupError)
    async def missing(_, exc):
        return JSONResponse({'detail': str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        return JSONResponse({'detail': str(exc)}, status_code=422)

    def library():
        return app.state.library

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'vector_store': 'qdrant-server' if settings.qdrant_url else 'qdrant-local',
            'embedding_model': settings.embedding_model}

    @app.get('/api/corpora')
    def corpora():
        return library().list_corpora()

    @app.post('/api/corpora', status_code=201)
    def create_corpus(body: CorpusCreate):
        if not body.name.strip():
            raise ValueError('请填写语料库名称。')
        return {'corpus_id': library().create_corpus(body.name.strip(), body.description.strip())}

    @app.get('/api/corpora/{corpus_id}/resources')
    def resources(corpus_id: str):
        return library().list_resources(corpus_id)

    @app.get('/api/corpora/archived')
    def archived_corpora():
        return library().archived_corpora()

    @app.delete('/api/corpora/{corpus_id}')
    def archive_corpus(corpus_id: str):
        library().archive_corpus(corpus_id)
        return {'archived': True}

    @app.post('/api/corpora/{corpus_id}/restore')
    def restore_corpus(corpus_id: str):
        library().restore_corpus(corpus_id)
        return {'restored': True}

    @app.get('/api/corpora/{corpus_id}/resources/{resource_id}/content')
    def resource_content(corpus_id: str, resource_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        return library().resource_content(corpus_id, resource_id, offset, limit)

    @app.post('/api/corpora/{corpus_id}/preview')
    def preview(corpus_id: str, file: UploadFile = File(...)):
        with library().db() as db:
            library().require_corpus(db, corpus_id)
        raw = file.file.read(settings.max_upload + 1)
        if len(raw) > settings.max_upload:
            raise HTTPException(413, '文件不能超过 10 MB。')
        _, parts = parse_upload(raw, Path(file.filename or 'untitled.txt').name)
        if not parts:
            raise ValueError('文件中没有可切分的正文。')
        return {'count': len(parts), 'preview': [{'text': p.text, 'citation': p.citation} for p in parts[:5]]}

    @app.post('/api/corpora/{corpus_id}/resources', status_code=202)
    def upload(corpus_id: str, file: UploadFile = File(...)):
        raw = file.file.read(settings.max_upload + 1)
        if len(raw) > settings.max_upload:
            raise HTTPException(413, '文件不能超过 10 MB。')
        name = Path(file.filename or 'untitled.txt').name[:200]
        text, fragments = parse_upload(raw, name)
        return library().import_parsed(corpus_id, name, text, fragments, raw=raw)

    @app.post('/api/corpora/{corpus_id}/resources/{resource_id}/reindex', status_code=202)
    def reindex(corpus_id: str, resource_id: str):
        return library().reindex(corpus_id, resource_id)

    @app.delete('/api/corpora/{corpus_id}/resources/{resource_id}')
    def archive(corpus_id: str, resource_id: str):
        library().archive(corpus_id, resource_id)
        return {'archived': True}

    @app.post('/api/search')
    def search(body: SearchRequest):
        if not body.query.strip():
            raise ValueError('先写下你想说的话。')
        return library().search(body.corpus_id, body.query.strip(), body.top_k)

    @app.get('/api/corpora/{corpus_id}/context')
    def context(corpus_id: str, fragment_id: str):
        return library().context(corpus_id, fragment_id)

    # API misses must remain JSON errors instead of returning the SPA.
    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'DELETE', 'PUT', 'PATCH'])
    def api_not_found(path: str):
        raise HTTPException(404, '接口不存在。')

    dist = ROOT / 'frontend' / 'dist'
    if dist.exists():
        app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
    return app


app = create_app()
