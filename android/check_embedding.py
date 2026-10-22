import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/'build/android-tools'
JDK=next((TOOLS/'jdk').glob('*/bin'))
out=ROOT/'build/android-embedding-check';out.mkdir(exist_ok=True)
classpath=str(TOOLS/'onnxruntime.jar')+';'+str(TOOLS/'json.jar')
sources=[ROOT/'android/src/org/bibletalking/app'/f for f in ['BertTokenizer.java','Encoder.java']]
sources.append(ROOT/'android/tests/EmbeddingCheck.java')
subprocess.run([str(JDK/'javac.exe'),'-encoding','UTF-8','-cp',classpath,'-d',str(out),*map(str,sources)],check=True)
result=subprocess.run([str(JDK/'java.exe'),'-cp',classpath+';'+str(out),'org.bibletalking.app.EmbeddingCheck',
    str(ROOT/'build/android-assets/model.onnx'),str(ROOT/'build/android-assets/vocab.txt'),str(ROOT/'build/android-embedding-fixtures.json')],check=True,capture_output=True,text=True)
print(result.stdout)
(ROOT/'build/android-embedding-check.txt').write_text(result.stdout,encoding='utf-8')
