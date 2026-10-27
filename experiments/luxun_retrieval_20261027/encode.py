import os
os.environ['HF_HUB_OFFLINE']='1'
os.environ['OMP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
import hashlib, json, sys, time
from pathlib import Path
import numpy as np
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from backend.config import Settings
from backend.vectors import Embedder

def main():
    kind=sys.argv[1] if len(sys.argv)>1 else 'corpus'
    data=json.loads((HERE/f'{kind}.json').read_text(encoding='utf8'))
    settings=Settings(embedding_batch_size=16,embedding_threads=2)
    model=Embedder(settings)
    texts=[x['text'] for x in data]
    out=HERE/f'{kind}_vectors.npy'
    if out.exists(): raise RuntimeError('Output already exists; preserve it or select a new experiment directory')
    vectors=np.lib.format.open_memmap(out,mode='w+',dtype='float32',shape=(len(texts),512))
    start=time.perf_counter()
    for a in range(0,len(texts),128):
        arr=np.asarray(model.encode(texts[a:a+128],query=kind=='queries'),dtype='float32')
        arr/=np.linalg.norm(arr,axis=1,keepdims=True)
        vectors[a:a+len(arr)]=arr
        vectors.flush()
        print(f'{kind}: {a+len(arr)}/{len(texts)}; elapsed={time.perf_counter()-start:.1f}s',flush=True)
    report={'count':len(texts),'dimensions':512,'seconds':time.perf_counter()-start,
        'batch':16,'threads':2,'model':settings.embedding_model,
        'input_sha256':hashlib.sha256((HERE/f'{kind}.json').read_bytes()).hexdigest(),
        'vector_sha256':hashlib.sha256(out.read_bytes()).hexdigest()}
    (HERE/f'{kind}_encoding.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    model.close()

if __name__=='__main__':main()
