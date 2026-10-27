import gc
import os
import sys
import threading
import time
from qdrant_client import QdrantClient, models


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
        gc.collect()
        # glibc may retain freed inference buffers even after the ONNX session dies.
        # Optional on Linux; other allocators/platforms release memory themselves.
        if sys.platform == 'linux':
            import ctypes
            try:
                trim = ctypes.CDLL(None).malloc_trim
                trim.argtypes = [ctypes.c_size_t]
                trim.restype = ctypes.c_int
                trim(0)
            except (AttributeError, OSError):
                pass

    def close(self):
        with self.lock:
            if self.model is not None:
                self._release_model()


class VectorStore:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.client = QdrantClient(url=settings.qdrant_url, timeout=60) if settings.qdrant_url else QdrantClient(
            path=str(settings.data_dir / 'qdrant'), force_disable_check_same_thread=True)
        # Preserve indexes created before the product rename; never create an empty replacement.
        legacy_collection = 'youyan_bge_small_zh_v1'
        if (settings.collection == 'Bible_talking_bge_small_zh_v1'
                and not self.client.collection_exists(settings.collection)
                and self.client.collection_exists(legacy_collection)):
            self.client.update_collection_aliases([models.CreateAliasOperation(create_alias=models.CreateAlias(
                collection_name=legacy_collection, alias_name=settings.collection))])
        if not self.client.collection_exists(settings.collection):
            self.client.create_collection(settings.collection, vectors_config=models.VectorParams(
                size=settings.dimensions, distance=models.Distance.COSINE))
            if settings.qdrant_url:
                self.client.create_payload_index(settings.collection, 'generation', models.PayloadSchemaType.KEYWORD)

    def upsert(self, points):
        with self.lock:
            self.client.upsert(self.settings.collection, points, wait=True)

    def search(self, vector, generations, limit):
        if not generations:
            return []
        with self.lock:
            return self.client.query_points(self.settings.collection, query=vector,
                query_filter=models.Filter(must=[models.FieldCondition(key='generation', match=models.MatchAny(any=generations))]),
                limit=limit, with_payload=True).points

    def delete_generation(self, generation):
        with self.lock:
            self.client.delete(self.settings.collection, points_selector=models.FilterSelector(filter=models.Filter(
                must=[models.FieldCondition(key='generation', match=models.MatchValue(value=generation))])), wait=True)

    def close(self):
        self.client.close()
