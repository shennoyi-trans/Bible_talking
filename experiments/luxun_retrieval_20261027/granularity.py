"""Post-primary exploratory experiment: add source-faithful sentence views."""
import os
os.environ['HF_HUB_OFFLINE']='1';os.environ['OMP_NUM_THREADS']='1';os.environ['OPENBLAS_NUM_THREADS']='1'
import json,re,sys,time,hashlib
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(HERE.parents[1]))
from backend.config import Settings
from backend.vectors import Embedder
def save(name,x):(HERE/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def read(name):return json.loads((HERE/name).read_text(encoding='utf8'))
def main():
    corpus=read('corpus.json');queries=read('queries.json')
    if (HERE/'granularity_results.json').exists():raise RuntimeError('Exploratory results already exist')
    views=[]
    for d in corpus:
        seen=set()
        for m in re.finditer(r'[^。！？!?；;]+[。！？!?；;]?',d['text']):
            text=m.group().strip()
            if len(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]',text))<8 or text==d['text'] or text in seen:continue
            seen.add(text);views.append({'parent_id':d['id'],'text':text,'start':m.start(),'end':m.end()})
    save('sentence_views.json',views)
    save('granularity_plan.json',{'status':'exploratory, specified after primary analysis; queries unchanged',
         'rule':'split at Chinese/ASCII sentence-final marks and semicolons; retain >=8 alphanumeric or Chinese characters; retain paragraph view; max score over views per original fragment',
         'n_additional_views':len(views),'query_sha256':hashlib.sha256((HERE/'queries.json').read_bytes()).hexdigest()})
    model=Embedder(Settings(embedding_batch_size=16,embedding_threads=2));start=time.perf_counter()
    vec=np.lib.format.open_memmap(HERE/'sentence_vectors.npy',mode='w+',dtype='float32',shape=(len(views),512))
    for a in range(0,len(views),256):
        v=np.asarray(model.encode([x['text'] for x in views[a:a+256]]),dtype='float32');v/=np.linalg.norm(v,axis=1,keepdims=True)
        vec[a:a+len(v)]=v;vec.flush();print(f'sentences {a+len(v)}/{len(views)} {time.perf_counter()-start:.1f}s',flush=True)
    model.close();elapsed=time.perf_counter()-start
    cv=np.load(HERE/'corpus_vectors.npy');qv=np.load(HERE/'queries_vectors.npy');parents=np.array([x['parent_id'] for x in views])
    results=[];top=[]
    for j,q in enumerate(queries):
        score=cv@qv[j];np.maximum.at(score,parents,vec@qv[j]);ordered=np.argsort(-score,kind='stable');rank=int(np.where(ordered==q['target_id'])[0][0])+1
        results.append({**q,'method':'semantic_sentence_max','rank':rank,'hit1':int(rank<=1),'hit5':int(rank<=5),'hit10':int(rank<=10),'mrr10':1/rank if rank<=10 else 0.})
        top.append({'query_id':q['id'],'top10':ordered[:10].tolist()})
    save('granularity_results.json',results);save('granularity_top10.json',top)
    summary=[{'kind':kind,'n':len(part),**{k:float(np.mean([r[k] for r in part])) for k in ['hit1','hit5','hit10','mrr10']}} for kind in ['all','literal','keyword','paraphrase','deletion'] if (part:=[r for r in results if kind=='all' or r['kind']==kind])]
    save('granularity_summary.json',{'index_extra_seconds':elapsed,'additional_views':len(views),'summary':summary})
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
