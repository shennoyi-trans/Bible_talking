"""Wait for the vector service and cache the model before serving requests."""
import os
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import Settings
from backend.vectors import Embedder


def main():
    settings = Settings()
    settings.validate()
    if settings.qdrant_url:
        deadline = time.monotonic() + 120
        while True:
            try:
                with urllib.request.urlopen(settings.qdrant_url.rstrip('/') + '/readyz', timeout=5) as response:
                    if response.status == 200:
                        break
            except (OSError, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('Qdrant did not become ready within 120 seconds')
            time.sleep(2)
    print('Preparing embedding model; first start may download model files.', flush=True)
    Embedder(settings).encode(['可以给我水喝吗？'])
    # Exactly one worker: SQLite indexing jobs are process-local.
    os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'backend.main:app',
                            '--host', os.getenv('BIND_HOST', '127.0.0.1'), '--port', os.getenv('PORT', '8000'),
                            '--workers', '1', '--proxy-headers',
                            '--forwarded-allow-ips', os.getenv('FORWARDED_ALLOW_IPS', '127.0.0.1')])


if __name__ == '__main__':
    main()
