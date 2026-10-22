import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import Settings
from backend.vectors import Embedder

if __name__ == '__main__':
    model = Embedder(Settings())
    vectors = model.encode(['可以给我水喝吗？'])
    print(f'Embedding ready: {len(vectors[0])} dimensions')
