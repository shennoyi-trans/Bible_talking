# Build with the project venv; no private corpus data is collected.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(root / 'frontend' / 'dist'), 'frontend/dist'), (str(root / 'resources'), 'resources')]
binaries, hiddenimports = [], ['uvicorn.logging', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl', 'uvicorn.lifespan.on']
for package in ['fastembed', 'tokenizers', 'onnxruntime', 'qdrant_client']:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
for package in ['fastembed', 'qdrant-client', 'huggingface-hub']:
    datas += copy_metadata(package)

a = Analysis([str(root / 'desktop' / 'launcher.py')], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, excludes=['pytest', 'IPython', 'matplotlib', 'torch', 'tensorflow',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cocoa'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Bible_talking', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, version=str(root / 'desktop' / 'version.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Bible_talking')
