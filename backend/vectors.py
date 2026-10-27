import gc
import os
import sys
import threading
import time
from qdrant_client import QdrantClient, models


def release_unused_memory():
    gc.collect()
    if sys.platform == 'linux':
        import ctypes
        try:
            trim = ctypes.CDLL(None).malloc_trim
            trim.argtypes = [ctypes.c_size_t]
            trim.restype = ctypes.c_int
            trim(0)
        except (AttributeError, OSError):
            pass


class Embedder:
    def __init__(self, settings):
        self.settings = settings
        self.model = None
        self.lock = threading.Lock()
        self.last_used = 0.0

    def encode(self, texts, query=False):
        with self.lock:
            if self.model is None:
                from fastembed import TextEmbedding
                self.model = TextEmbedding(model_name=self.settings.embedding_model,
                    cache_dir=os.getenv('MODEL_CACHE_DIR', str(self.settings.data_dir / 'models')),
                    threads=self.settings.embedding_threads, enable_cpu_mem_arena=False)
            method = self.model.query_embed if query else self.model.passage_embed
            try:
                return [v.tolist() for v in method(texts, batch_size=self.settings.embedding_batch_size)]
            finally:
                self.last_used = time.monotonic()

    def release_if_idle(self):
        # Never interrupt or queue behind a search/indexing call.
        if not self.lock.acquire(blocking=False):
            return
        try:
            if self.model is not None and time.monotonic() - self.last_used >= self.settings.embedding_idle_seconds:
                self._release_model()
        finally:
            self.lock.release()

    def _release_model(self):
        self.model = None
        release_unused_memory()

    def close(self):
        with self.lock:
            if self.model is not None:
                self._release_model()


class VectorStore:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self._client = None
        self.last_used = 0.0
        self._closed = False
        self._ownership = None
        if not settings.qdrant_url:
            # Keep application ownership while the Qdrant cache is unloaded.
            # Otherwise a second worker could start against the same job queue.
            import portalocker
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            self._ownership = portalocker.Lock(str(settings.data_dir / '.library.lock'), mode='a', timeout=0)
            try:
                self._ownership.acquire()
            except portalocker.exceptions.LockException as exc:
                raise RuntimeError('此数据目录已由另一个进程使用，请只启动一个应用进程。') from exc

    def _initialize_collection(self, client):
        settings = self.settings
        # Preserve indexes created before the product rename; never create an empty replacement.
        legacy_collection = 'youyan_bge_small_zh_v1'
        if (settings.collection == 'Bible_talking_bge_small_zh_v1'
                and not client.collection_exists(settings.collection)
                and client.collection_exists(legacy_collection)):
            client.update_collection_aliases([models.CreateAliasOperation(create_alias=models.CreateAlias(
                collection_name=legacy_collection, alias_name=settings.collection))])
        if not client.collection_exists(settings.collection):
            client.create_collection(settings.collection, vectors_config=models.VectorParams(
                size=settings.dimensions, distance=models.Distance.COSINE))
            if settings.qdrant_url:
                client.create_payload_index(settings.collection, 'generation', models.PayloadSchemaType.KEYWORD)

    @property
    def client(self):
        with self.lock:
            if self._closed:
                raise RuntimeError('Vector store is closed')
            if self._client is None:
                client = QdrantClient(url=self.settings.qdrant_url, timeout=60) if self.settings.qdrant_url else QdrantClient(
                    path=str(self.settings.data_dir / 'qdrant'), force_disable_check_same_thread=True)
                try:
                    self._initialize_collection(client)
                except Exception:
                    client.close()
                    raise
                self._client = client
            self.last_used = time.monotonic()
            return self._client

    def cache_status(self):
        # A health check must not load the cache or extend its lifetime.
        if self.settings.qdrant_url:
            return None
        return {'loaded': self._client is not None, 'idle_seconds': self.settings.vector_cache_idle_seconds}

    def upsert(self, points):
        with self.lock:
            try:
                self.client.upsert(self.settings.collection, points, wait=True)
            finally:
                self.last_used = time.monotonic()

    def search(self, vector, generations, limit):
        if not generations:
            return []
        with self.lock:
            try:
                return self.client.query_points(self.settings.collection, query=vector,
                    query_filter=models.Filter(must=[models.FieldCondition(key='generation', match=models.MatchAny(any=generations))]),
                    limit=limit, with_payload=True).points
            finally:
                self.last_used = time.monotonic()

    def delete_generation(self, generation):
        self.delete_generations([generation])

    def delete_generations(self, generations):
        with self.lock:
            try:
                for start in range(0, len(generations), 256):
                    self.client.delete(self.settings.collection, points_selector=models.FilterSelector(filter=models.Filter(
                        must=[models.FieldCondition(key='generation', match=models.MatchAny(any=generations[start:start+256]))])), wait=True)
            finally:
                self.last_used = time.monotonic()

    def _unload(self):
        if self._client is not None:
            self._client.close()
            self._client = None
            release_unused_memory()

    def release_if_idle(self):
        if self.settings.qdrant_url or not self.lock.acquire(blocking=False):
            return
        try:
            if self._client is not None and time.monotonic() - self.last_used >= self.settings.vector_cache_idle_seconds:
                self._unload()
        finally:
            self.lock.release()

    def compact_deleted(self):
        # Drop tombstones and vector slots now; reload remaining points on demand.
        if not self.settings.qdrant_url:
            with self.lock:
                self._unload()

    def close(self):
        with self.lock:
            self._unload()
            self._closed = True
            if self._ownership is not None:
                self._ownership.release()
                self._ownership = None
