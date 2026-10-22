import os
import threading
from qdrant_client import QdrantClient, models


class Embedder:
    def __init__(self, settings):
        self.settings = settings
        self.model = None
        self.lock = threading.Lock()

    def encode(self, texts, query=False):
        with self.lock:
            if self.model is None:
                from fastembed import TextEmbedding
                self.model = TextEmbedding(model_name=self.settings.embedding_model,
                    cache_dir=os.getenv('MODEL_CACHE_DIR', str(self.settings.data_dir / 'models')), threads=4)
            method = self.model.query_embed if query else self.model.passage_embed
            return [v.tolist() for v in method(texts, batch_size=64)]


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
