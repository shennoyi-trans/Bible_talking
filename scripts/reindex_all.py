"""Run with the API stopped, e.g. after switching Qdrant storage backends."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import Settings
from backend.service import Library

if __name__ == '__main__':
    library = Library(Settings(worker_enabled=False))
    try:
        for corpus in library.list_corpora():
            for resource in library.list_resources(corpus['corpus_id']):
                library.reindex(corpus['corpus_id'], resource['resource_id'])
        while library.process_one():
            pass
        print(library.list_corpora())
    finally:
        library.close()
