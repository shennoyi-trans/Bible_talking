import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('DATA_DIR', ROOT / 'data')))
    qdrant_url: str = field(default_factory=lambda: os.getenv('QDRANT_URL', ''))
    embedding_model: str = 'BAAI/bge-small-zh-v1.5'
    embedding_revision: str = 'fastembed-0.9-bge-small-zh-v1.5'
    dimensions: int = 512
    embedding_batch_size: int = field(default_factory=lambda: int(os.getenv('EMBEDDING_BATCH_SIZE', '8')))
    embedding_threads: int = field(default_factory=lambda: int(os.getenv('EMBEDDING_THREADS', '1')))
    embedding_idle_seconds: int = field(default_factory=lambda: int(os.getenv('EMBEDDING_IDLE_SECONDS', '60')))
    vector_cache_idle_seconds: int = field(default_factory=lambda: int(os.getenv('VECTOR_CACHE_IDLE_SECONDS', '30')))
    index_batch_pause: float = field(default_factory=lambda: float(os.getenv('INDEX_BATCH_PAUSE', '0.1')))
    collection: str = 'Bible_talking_bge_small_zh_v1'
    preload: bool = field(default_factory=lambda: os.getenv('PRELOAD_BIBLE', '1') == '1')
    worker_enabled: bool = True
    max_upload: int = 10 * 1024 * 1024
    deployment: str = field(default_factory=lambda: os.getenv('DEPLOYMENT_MODE', 'local'))
    public_origin: str = field(default_factory=lambda: os.getenv('PUBLIC_ORIGIN', '').rstrip('/'))

    def validate(self):
        import math
        from urllib.parse import urlsplit
        if self.embedding_batch_size < 1 or self.embedding_threads < 1:
            raise ValueError('EMBEDDING_BATCH_SIZE and EMBEDDING_THREADS must be positive')
        if self.embedding_idle_seconds < 1:
            raise ValueError('EMBEDDING_IDLE_SECONDS must be positive')
        if self.vector_cache_idle_seconds < 1:
            raise ValueError('VECTOR_CACHE_IDLE_SECONDS must be positive')
        if not math.isfinite(self.index_batch_pause) or self.index_batch_pause < 0:
            raise ValueError('INDEX_BATCH_PAUSE must be finite and non-negative')
        if self.deployment not in {'local', 'server'}:
            raise ValueError('DEPLOYMENT_MODE must be local or server')
        if self.deployment == 'server':
            origin = urlsplit(self.public_origin)
            if (origin.scheme not in {'http', 'https'} or not origin.hostname
                    or origin.username or origin.password or origin.path or origin.query or origin.fragment):
                raise ValueError('Server mode requires PUBLIC_ORIGIN=https://your-domain')

