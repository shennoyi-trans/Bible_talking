"""Assemble a clean portable folder after PyInstaller and seed verification."""
import importlib.metadata
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
target = ROOT / 'release' / 'Bible_talking'
assert (target / 'Bible_talking.exe').is_file()
report = json.loads((ROOT / 'build' / 'seed-verification.json').read_text(encoding='utf-8'))
assert report['private_corpora_included'] is False
assert report['corpora'][0]['indexed_resources'] == 66
for name in ('models', 'data'):
    if (target / name).exists():
        raise RuntimeError(f'{target / name} already exists: refusing to overwrite possible user data.')
shutil.copytree(ROOT / 'data' / 'models', target / 'models', ignore=shutil.ignore_patterns('.locks', '*.lock'))
shutil.copytree(ROOT / 'build' / 'bible-seed', target / 'data' / 'library',
    ignore=shutil.ignore_patterns('.lock', '*-wal', '*-shm'))
shutil.copyfile(ROOT / 'desktop' / '使用说明.txt', target / '使用说明.txt')
(target / 'portable.txt').write_text('User data is stored in ./data. Keep data and models when updating.\n', encoding='utf-8')
shutil.copytree(ROOT / 'desktop' / 'licenses', target / 'licenses', dirs_exist_ok=True)
notices = ['Dependency licenses are retained in licenses/.',
    'Bible source and public-domain statement: _internal/resources/manifest.json',
    'Model: BAAI/bge-small-zh-v1.5 (MIT); https://huggingface.co/BAAI/bge-small-zh-v1.5',
    'ONNX conversion: https://huggingface.co/Qdrant/bge-small-zh-v1.5',
    'FlagEmbedding MIT license: https://github.com/FlagOpen/FlagEmbedding/blob/master/LICENSE',
    'WebView2 distribution: https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution', '']
for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
    name = dist.metadata['Name']
    notices.append(f'{name} {dist.version}')
    for file in dist.files or []:
        if any(word in file.name.lower() for word in ['license', 'copying', 'notice']) and file.suffix.lower() not in {'.py', '.pyc'}:
            source = Path(dist.locate_file(file))
            if source.is_file():
                dest = target / 'licenses' / name / str(file).replace('..', '_')
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
for file in Path(sys.base_prefix).glob('LICENSE*'):
    if file.is_file():
        shutil.copyfile(file, target / 'licenses' / file.name)
for name in ['vue', '@vue/runtime-core', '@vue/runtime-dom', '@vue/reactivity', '@vue/shared', 'lucide-vue-next']:
    package = ROOT / 'frontend' / 'node_modules' / name
    for file in package.glob('LICENSE*'):
        if file.is_file():
            dest = target / 'licenses' / name.replace('/', '_') / file.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, dest)
(target / 'THIRD-PARTY-NOTICES.txt').write_text('\n'.join(notices), encoding='utf-8')
print('Portable folder assembled without private corpora.')
