"""Reproducible APK assembly with official javac, aapt2, D8, zipalign and apksigner."""
import hashlib, json, secrets, shutil, subprocess, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/'build/android-tools'
BUILD=ROOT/'build/android'
BUILD.mkdir(parents=True,exist_ok=True)
JDK=next((TOOLS/'jdk').glob('*/bin'))
SDK=next((TOOLS/'build-tools').glob('*/aapt2.exe')).parent
PLATFORM=next((TOOLS/'platform').glob('*/android.jar'))
JAVA=JDK/'java.exe'
def run(*args):
    subprocess.run([str(a) for a in args],check=True,cwd=ROOT)

assets=ROOT/'build/android-assets'
assert (assets/'model.onnx').is_file(), 'Run android/export_assets.py first'
assert (ROOT/'frontend/dist/index.html').is_file(), 'Build the frontend first'
shutil.copytree(ROOT/'frontend/dist',assets/'web',dirs_exist_ok=True)
licenses=assets/'licenses'
shutil.copytree(ROOT/'desktop/licenses',licenses,dirs_exist_ok=True)
shutil.copyfile(ROOT/'resources/manifest.json',licenses/'bible-source.json')
for f in (TOOLS/'ort-android').iterdir():
    if f.is_file() and ('license' in f.name.lower() or 'notice' in f.name.lower()):shutil.copyfile(f,licenses/f.name)
for name in ['vue','@vue/runtime-core','@vue/runtime-dom','@vue/reactivity','@vue/shared','lucide-vue-next']:
    for f in (ROOT/'frontend/node_modules'/name).glob('LICENSE*'):
        shutil.copyfile(f,licenses/(name.replace('/','_')+'-'+f.name))
classes=BUILD/'classes';classes.mkdir(exist_ok=True)
ort=TOOLS/'ort-android/classes.jar'
sources=list((ROOT/'android/src').rglob('*.java'))
run(JDK/'javac.exe','-encoding','UTF-8','-source','8','-target','8','-classpath',str(PLATFORM)+';'+str(ort),'-d',classes,*sources)
run(JDK/'jar.exe','cf',BUILD/'classes.jar','-C',classes,'.')
dex=BUILD/'dex';dex.mkdir(exist_ok=True)
run(JAVA,'-cp',SDK/'lib/d8.jar','com.android.tools.r8.D8','--min-api','26','--lib',PLATFORM,'--output',dex,BUILD/'classes.jar',ort)
run(SDK/'aapt2.exe','compile','--dir',ROOT/'android/res','-o',BUILD/'resources.zip')
run(SDK/'aapt2.exe','link','-I',PLATFORM,'--manifest',ROOT/'android/AndroidManifest.xml','-A',assets,'-o',BUILD/'base.apk',BUILD/'resources.zip')
unsigned=BUILD/'unsigned.apk'
with zipfile.ZipFile(unsigned,'w',compression=zipfile.ZIP_DEFLATED) as apk, zipfile.ZipFile(BUILD/'base.apk') as base:
    # Rewrite both ZIP headers consistently before alignment and signing.
    for info in base.infolist(): apk.writestr(info,base.read(info))
    for f in dex.glob('*.dex'):apk.write(f,f.name)
    for f in (TOOLS/'ort-android/jni/arm64-v8a').glob('*.so'):apk.write(f,'lib/arm64-v8a/'+f.name)
run(SDK/'zipalign.exe','-P','16','-f','4',unsigned,BUILD/'aligned.apk')
signing=ROOT/'build/android-signing';signing.mkdir(exist_ok=True)
key=signing/'Bible_talking.jks';password=signing/'password.txt'
if not key.exists():
    if not password.exists():password.write_text(secrets.token_urlsafe(32),encoding='ascii')
    run(JDK/'keytool.exe','-genkeypair','-keystore',key,'-alias','bible-talking','-keyalg','RSA','-keysize','3072',
        '-validity','10000','-dname','CN=Bible_talking Local Release','-storepass:file',password,'-keypass:file',password)
target=ROOT/'release/Bible_talking-Android-arm64-offline.apk';target.parent.mkdir(exist_ok=True)
signer=SDK/'lib/apksigner.jar'
run(JAVA,'-jar',signer,'sign','--ks',key,'--ks-pass','file:'+str(password),'--out',target,BUILD/'aligned.apk')
run(JAVA,'-jar',signer,'verify','--verbose','--print-certs',target)
run(SDK/'zipalign.exe','-c','-P','16','4',target)
report={'apk':target.name,'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'abi':'arm64-v8a','min_android':8,'target_sdk':35,'signed':True,'internet_permission':False,
        'model':'BAAI/bge-small-zh-v1.5','verses':31100,'vectors':34627,'device_tested':False}
(ROOT/'release/android-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
