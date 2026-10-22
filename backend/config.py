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
    collection: str = 'Bible_talking_bge_small_zh_v1'
    preload: bool = field(default_factory=lambda: os.getenv('PRELOAD_BIBLE', '1') == '1')
    worker_enabled: bool = True
    max_upload: int = 10 * 1024 * 1024
    deployment: str = field(default_factory=lambda: os.getenv('DEPLOYMENT_MODE', 'local'))
    public_origin: str = field(default_factory=lambda: os.getenv('PUBLIC_ORIGIN', '').rstrip('/'))

    def validate(self):
        from urllib.parse import urlsplit
        if self.deployment not in {'local', 'server'}:
            raise ValueError('DEPLOYMENT_MODE must be local or server')
        if self.deployment == 'server':
            origin = urlsplit(self.public_origin)
            if (origin.scheme not in {'http', 'https'} or not origin.hostname
                    or origin.username or origin.password or origin.path or origin.query or origin.fragment):
                raise ValueError('Server mode requires PUBLIC_ORIGIN=https://your-domain')

