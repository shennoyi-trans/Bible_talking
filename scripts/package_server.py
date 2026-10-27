"""Package a prebuilt web release, excluding personal data and development files."""
from datetime import datetime
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise SystemExit('Build first: npm --prefix frontend run build')
    files = [ROOT / name for name in ['Dockerfile', '.dockerignore', 'compose.server.yaml',
             'requirements-lock.txt', 'README.md', 'docs/server-deployment.md', 'docs/inner-office-deployment.md',
             'docs/low-resource-verification.md', 'scripts/benchmark_embedding_memory.py',
             'scripts/benchmark_vector_cache.py',
             'resources/cuv.jsonl', 'resources/manifest.json',
             'scripts/warm_model.py', 'scripts/reindex_all.py',
             'scripts/configure_server.py', 'scripts/server_entrypoint.py']]
    files.extend((ROOT / 'backend').glob('*.py'))
    files.extend((ROOT / 'deploy').glob('*'))
    files.extend(p for p in (ROOT / 'frontend/dist').rglob('*') if p.is_file())
    output = ROOT / 'release' / f'Bible_talking-Web-{datetime.now():%Y%m%d-%H%M%S}.zip'
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{digest}  {output.name}\n', encoding='ascii')
    print(output)
    print(f'SHA256 {digest}')


if __name__ == '__main__':
    main()
