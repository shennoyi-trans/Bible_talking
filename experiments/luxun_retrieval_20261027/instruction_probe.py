"""Exploratory 2x2 query-instruction and indexing-granularity comparison."""
import os
os.environ['HF_HUB_OFFLINE']='1';os.environ['OMP_NUM_THREADS']='1';os.environ['OPENBLAS_NUM_THREADS']='1'
import json,sys,time,hashlib
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;sys.dont_write_bytecode=True;sys.path.insert(0,str(HERE.parents[1]))
from backend.config import Settings
from backend.vectors import Embedder
def read(n):return json.loads((HERE/n).read_text(encoding='utf8'))
def save(n,x):(HERE/n).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def main():
    if (HERE/'instruction_results.json').exists():raise RuntimeError('Existing results retained')
    prefix='为这个句子生成表示以用于检索相关文章：'
    save('instruction_plan.json',{'status':'exploratory after primary results','prefix':prefix,'source':'https://huggingface.co/BAAI/bge-small-zh-v1.5','query_sha256':hashlib.sha256((HERE/'queries.json').read_bytes()).hexdigest(),'purpose':'original FastEmbed adapter inherits query_embed without adding model-card instruction; compare a fixed documented instruction, no tuning'})
    qs=read('queries.json');model=Embedder(Settings(embedding_batch_size=16,embedding_threads=2))
    qv=np.asarray(model.encode([prefix+q['text'] for q in qs],query=True),dtype='float32');qv/=np.linalg.norm(qv,axis=1,keepdims=True);model.close()
    np.save(HERE/'instruction_query_vectors.npy',qv)
    cv=np.load(HERE/'corpus_vectors.npy');sv=np.load(HERE/'sentence_vectors.npy');parents=np.array([v['parent_id'] for v in read('sentence_views.json')])
    rows=[]
    for i,q in enumerate(qs):
        for method in ['semantic_instruction','semantic_sentence_instruction']:
            score=cv@qv[i]
            if method.endswith('sentence_instruction'):np.maximum.at(score,parents,sv@qv[i])
            order=np.argsort(-score,kind='stable');rank=int(np.where(order==q['target_id'])[0][0])+1
            rows.append({**q,'method':method,'rank':rank,'hit1':int(rank<=1),'hit5':int(rank<=5),'hit10':int(rank<=10),'mrr10':1/rank if rank<=10 else 0.})
    save('instruction_results.json',rows)
    summary=[{'method':method,'kind':kind,**{k:float(np.mean([r[k] for r in part])) for k in ['hit1','hit5','hit10','mrr10']}} for method in ['semantic_instruction','semantic_sentence_instruction'] for kind in ['all','literal','keyword','paraphrase','deletion'] if (part:=[r for r in rows if r['method']==method and (kind=='all' or r['kind']==kind)])]
    save('instruction_summary.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
