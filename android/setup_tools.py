"""Fetch official portable build tools into build/android-tools; no global installation."""
import concurrent.futures, hashlib, json, urllib.request, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'build/android-tools'
TOOLS.mkdir(parents=True, exist_ok=True)

def get(url):
    return urllib.request.urlopen(url, timeout=180).read()

def download(url, name, digest=None, algorithm='sha256', extract=None):
    target = TOOLS / name
    if not target.exists():
        print('Downloading', name, flush=True)
        data = get(url)
        if digest and hashlib.new(algorithm, data).hexdigest() != digest:
            raise RuntimeError('Checksum mismatch: ' + name)
        target.write_bytes(data)
    if digest and hashlib.new(algorithm, target.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Cached checksum mismatch: ' + name)
    if extract and not (TOOLS / extract).exists():
        with zipfile.ZipFile(target) as z: z.extractall(TOOLS / extract)
    print('Ready', name, flush=True)

def jdk():
    url = 'https://aka.ms/download-jdk/microsoft-jdk-17.0.20.1-windows-x64.zip'
    digest = get(url+'.sha256sum.txt').decode().split()[0]
    download(url, 'jdk.zip', digest, extract='jdk')

def sdk():
    root = ET.fromstring(get('https://dl.google.com/android/repository/repository2-1.xml'))
    for path, folder in [('build-tools;35.0.0', 'build-tools'), ('platforms;android-35', 'platform')]:
        package = next(p for p in root if p.tag.endswith('remotePackage') and p.attrib['path'] == path)
        archives = package.find('archives').findall('archive')
        archive = next(a for a in archives if a.findtext('host-os') in (None, 'windows'))
        complete = archive.find('complete')
        download('https://dl.google.com/android/repository/' + complete.findtext('url'), folder+'.zip',
                 complete.findtext('checksum'), 'sha1', folder)

def ort():
    base = 'https://repo.maven.apache.org/maven2/'
    for artifact, ext, folder in [('onnxruntime-android','aar','ort-android'), ('onnxruntime','jar',None)]:
        download(base+f'com/microsoft/onnxruntime/{artifact}/1.23.2/{artifact}-1.23.2.{ext}', artifact+'.'+ext, extract=folder)
    download(base+'org/json/json/20250517/json-20250517.jar', 'json.jar')

with concurrent.futures.ThreadPoolExecutor(3) as pool:
    for future in [pool.submit(fn) for fn in (jdk,sdk,ort)]: future.result()
print('Toolchain ready.', flush=True)
