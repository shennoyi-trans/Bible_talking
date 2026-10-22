"""Export the cached BGE model for offline deployment, without application data."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    cache = ROOT / 'data' / 'models'
    candidates = [p for p in cache.iterdir() if p.name.lower() == 'models--qdrant--bge-small-zh-v1.5']
    if len(candidates) != 1:
        raise SystemExit('Cache the model with scripts/warm_model.py before packaging.')
    source = candidates[0]
    revision = (source / 'refs' / 'main').read_text().strip()
    if not revision or any(c not in '0123456789abcdef' for c in revision):
        raise SystemExit('Invalid cached model revision.')
    snapshot = source / 'snapshots' / revision
    for name in ['model_optimized.onnx', 'config.json', 'tokenizer.json',
                 'tokenizer_config.json', 'special_tokens_map.json']:
        if not (snapshot / name).is_file():
            raise SystemExit(f'Missing model file: {name}')
    output = ROOT / 'release' / f'Bible_talking-Model-{revision[:12]}.zip'
    output.parent.mkdir(exist_ok=True)
    hashes = {}
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob('*')):
            if not path.is_file() or '.locks' in path.parts or path.suffix in {'.lock', '.incomplete'}:
                continue
            relative = Path('models') / source.name / path.relative_to(source)
            content = path.read_bytes()  # Materialize cache symlinks for cross-platform use.
            if path.name == 'files_metadata.json':
                # FastEmbed on Windows stores backslashes; Linux needs POSIX keys.
                metadata = json.loads(content)
                content = json.dumps({key.replace('\\', '/'): value for key, value in metadata.items()},
                                     ensure_ascii=False).encode('utf-8')
            archive.writestr(relative.as_posix(), content)
            hashes[relative.as_posix()] = hashlib.sha256(content).hexdigest()
        archive.write(ROOT / 'desktop/licenses/BGE-LICENSE.txt', 'BGE-LICENSE.txt')
        archive.writestr('model-manifest.json', json.dumps({
            'model': 'BAAI/bge-small-zh-v1.5', 'revision': revision, 'sha256': hashes,
        }, indent=2))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{digest}  {output.name}\n', encoding='ascii')
    print(output)
    print(f'Size: {output.stat().st_size / 1024 / 1024:.1f} MiB; SHA256: {digest}')


if __name__ == '__main__':
    main()
