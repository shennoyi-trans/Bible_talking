"""Frozen known-item retrieval benchmark. Never fits or tunes on evaluation queries."""
import os
os.environ['HF_HUB_OFFLINE']='1'
os.environ['OMP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
import collections,csv,hashlib,importlib.metadata,json,platform,random,re,sys,time
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(HERE/'vendor'),str(ROOT)]
import jieba
jieba.setLogLevel(40)
jieba.dt.tmp_dir=str(HERE)
from backend.config import Settings
from backend.vectors import Embedder

KINDS=['literal','keyword','paraphrase','deletion']
METHODS=['bm25_word','bm25_bigram','semantic','hybrid']
def read(name):return json.loads((HERE/name).read_text(encoding='utf8'))
def save(name,obj):(HERE/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def norm(s):return ''.join(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]',s.lower()))
def words(s):return [t.lower() for t in jieba.cut(s,HMM=False) if re.search(r'[\u4e00-\u9fffA-Za-z0-9]',t)]
def bigrams(s):
    chunks=re.findall(r'[\u4e00-\u9fffA-Za-z0-9]+',s.lower())
    return [c[i:i+2] for c in chunks for i in range(max(1,len(c)-1))]

class BM25:
    def __init__(self,docs,tokenizer):
        self.tokenizer=tokenizer
        tokens=[tokenizer(d) for d in docs]
        self.n=len(tokens)
        lens=np.array([len(x) for x in tokens])
        self.length_norm=1.5*(.25+.75*lens/max(lens.mean(),1))
        postings=collections.defaultdict(list)
        for i,ts in enumerate(tokens):
            for token,tf in collections.Counter(ts).items():postings[token].append((i,tf))
        self.postings={}
        for token,values in postings.items():
            ids=np.array([a for a,b in values],dtype='int32')
            tf=np.array([b for a,b in values],dtype='float64')
            idf=np.log(1+(self.n-len(ids)+.5)/(len(ids)+.5))
            self.postings[token]=(ids,idf*tf*2.5/(tf+self.length_norm[ids]))
    def score(self,text):
        out=np.zeros(self.n,dtype='float64')
        for t in set(self.tokenizer(text)):
            if t in self.postings:
                ids,values=self.postings[t];out[ids]+=values
        return out

def order(scores,positive=False):
    ids=np.argsort(-scores,kind='stable')
    return ids[scores[ids]>0] if positive else ids
def fuse(a,b,n):
    score=np.zeros(n,dtype='float64')
    for ranking in [a[:100],b[:100]]:
        score[ranking]+=1/(60+np.arange(1,len(ranking)+1))
    return order(score,True)
def metrics(rank):return {'hit1':float(rank<=1),'hit5':float(rank<=5),'hit10':float(rank<=10),'mrr10':1/rank if rank<=10 else 0.0}
def rankings(w,b,vec,qvec,text):
    a=order(w.score(text),True);c=order(b.score(text),True);s=order(vec@qvec)
    return {'bm25_word':a,'bm25_bigram':c,'semantic':s,'hybrid':fuse(a,s,len(vec))}

def validate():
    bm=BM25(['aa aa bb','bb cc'],str.split)
    expected=np.log(1+(2-1+.5)/(1+.5))*2*2.5/(2+1.5*(.25+.75*3/2.5))
    assert abs(bm.score('aa')[0]-expected)<1e-12
    assert len(order(bm.score('absent'),True))==0
    assert list(fuse(np.array([0,1]),np.array([1,2]),3))==[1,0,2]
    assert list(order(np.array([1.,1.,0.])))==[0,1,2]

def bootstrap_summary(rows):
    rng=np.random.default_rng(20261027)
    # Stratified target-cluster bootstrap: preserve 12 targets per collection.
    samples=np.concatenate([rng.choice(np.arange(i*12,(i+1)*12),size=(4000,12)) for i in range(5)],axis=1)
    by={}
    for kind in ['all']+KINDS:
        for method in METHODS:
            part=[r for r in rows if r['method']==method and (kind=='all' or r['kind']==kind)]
            arr=np.array([[np.mean([r[k] for r in part if r['target_no']==t]) for k in ['hit1','hit5','hit10','mrr10']] for t in range(1,61)])
            boot=arr[samples].mean(axis=1)
            by[kind,method]=arr
            yield {'kind':kind,'method':method,'n_queries':len(part),**{k:float(arr[:,j].mean()) for j,k in enumerate(['hit1','hit5','hit10','mrr10'])},
                   'ci95':{k:np.quantile(boot[:,j],[.025,.975]).tolist() for j,k in enumerate(['hit1','hit5','hit10','mrr10'])}}
    diffs=[]
    for kind in ['all']+KINDS:
        for a,b in [('semantic','bm25_word'),('hybrid','semantic'),('bm25_bigram','bm25_word')]:
            arr=by[kind,a]-by[kind,b];boot=arr[samples].mean(axis=1)
            diffs.append({'kind':kind,'comparison':a+' minus '+b,
              'hit5_difference':float(arr[:,1].mean()),'hit5_ci95':np.quantile(boot[:,1],[.025,.975]).tolist(),
              'mrr10_difference':float(arr[:,3].mean()),'mrr10_ci95':np.quantile(boot[:,3],[.025,.975]).tolist()})
    save('paired_differences.json',diffs)

def main():
    validate()
    corpus=read('corpus.json');queries=read('queries.json');manifest=read('query_manifest.json')
    assert sha(HERE/'queries.json')==manifest['sha256']
    cv=np.load(HERE/'corpus_vectors.npy');qv=np.load(HERE/'queries_vectors.npy')
    assert cv.shape==(len(corpus),512) and qv.shape==(len(queries),512)
    assert np.isfinite(cv).all() and np.isfinite(qv).all()
    assert np.allclose(np.linalg.norm(cv,axis=1),1,atol=1e-5)
    assert all(q['text'] in corpus[q['target_id']]['text'] for q in queries if q['kind']=='literal')
    started=time.perf_counter();w=BM25([d['text'] for d in corpus],words);word_build=time.perf_counter()-started
    started=time.perf_counter();b=BM25([d['text'] for d in corpus],bigrams);bigram_build=time.perf_counter()-started
    rows=[];details=[]
    for i,q in enumerate(queries):
        ranks=rankings(w,b,cv,qv[i],q['text'])
        for method,ordered in ranks.items():
            loc=np.where(ordered==q['target_id'])[0];rank=int(loc[0])+1 if len(loc) else len(corpus)+1
            rows.append({**q,'method':method,'rank':rank,**metrics(rank)})
            details.append({'query_id':q['id'],'method':method,'top10':ordered[:10].tolist(),'target_rank':rank})
    save('query_results.json',rows);save('top10_results.json',details)
    summary=list(bootstrap_summary(rows));save('summary.json',summary)
    with (HERE/'query_results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    books=[]
    for book in dict.fromkeys(d['book'] for d in corpus):
        for method in METHODS:
            part=[r for r in rows if r['book']==book and r['method']==method]
            books.append({'book':book,'method':method,**{k:float(np.mean([r[k] for r in part])) for k in ['hit1','hit5','hit10','mrr10']}})
    save('by_book.json',books)
    # Nested distractor pools, retaining every target. Rebuild lexical IDF per size.
    target_ids=sorted(set(q['target_id'] for q in queries));others=[i for i in range(len(corpus)) if i not in target_ids]
    random.Random(20261027).shuffle(others)
    scale=[]
    for n in [1000,2000,len(corpus)]:
        ids=np.array(sorted(target_ids+others[:n-len(target_ids)]));local={int(v):i for i,v in enumerate(ids)}
        ww=BM25([corpus[i]['text'] for i in ids],words);bb=BM25([corpus[i]['text'] for i in ids],bigrams)
        part=[]
        for j,q in enumerate(queries):
            for method,ordered in rankings(ww,bb,cv[ids],qv[j],q['text']).items():
                loc=np.where(ordered==local[q['target_id']])[0];rank=int(loc[0])+1 if len(loc) else n+1
                part.append({'n':n,'query_id':q['id'],'kind':q['kind'],'method':method,'rank':rank,**metrics(rank)})
        scale.extend(part)
        print('corpus-size',n,flush=True)
    save('scale_results.json',scale)
    # Warm single-query elapsed time includes tokenization/encoding/scoring/sorting.
    model=Embedder(Settings(embedding_batch_size=16,embedding_threads=2))
    model.encode([queries[0]['text']],query=True)
    timing=[]
    for rep in range(5):
        sequence=list(range(len(queries)));random.Random(20261027+rep).shuffle(sequence)
        for j in sequence:
            q=queries[j];start=time.perf_counter();a=order(w.score(q['text']),True);tw=time.perf_counter()-start
            start=time.perf_counter();bb=order(b.score(q['text']),True);tb=time.perf_counter()-start
            start=time.perf_counter();vv=np.asarray(model.encode([q['text']],query=True)[0],dtype='float32');vv/=np.linalg.norm(vv)
            s=order(cv@vv);ts=time.perf_counter()-start
            assert np.max(np.abs(vv-qv[j]))<1e-5
            start=time.perf_counter();fuse(a,s,len(corpus));tf=time.perf_counter()-start
            timing.append({'rep':rep,'query_id':q['id'],'bm25_word_ms':tw*1000,'bm25_bigram_ms':tb*1000,'semantic_ms':ts*1000,
                           'hybrid_components_ms':(tw+ts+tf)*1000,'fusion_only_ms':tf*1000})
        print('timing repetition',rep+1,flush=True)
    model.close();save('timings.json',timing)
    packages={n:importlib.metadata.version(n) for n in ['numpy','fastembed','onnxruntime','qdrant-client','jieba']}
    save('run_manifest.json',{'platform':platform.platform(),'python':sys.version,'processor':platform.processor(),
      'packages':packages,'query_sha256':sha(HERE/'queries.json'),'corpus_sha256':sha(HERE/'corpus.json'),
      'evaluator_sha256':sha(Path(__file__)),'word_index_seconds':word_build,'bigram_index_seconds':bigram_build,
      'implementation':'numpy exact cosine on normalized embeddings; custom posting-list BM25 with positive log1p IDF; jieba HMM=False, no stoplist; deterministic ID tie-break; word BM25 + semantic top100 RRF(k=60)',
      'validation':'BM25 hand calculation, zero-overlap rejection, RRF hand case, stable ties, literal containment, finite unit vectors, repeated single/batch query vector consistency passed',
      'timing_notes':'5 warm repetitions, 240 queries each; hybrid is sequential measured component sum, model load/index build excluded; no HTTP/UI overhead; CPU only'})
    print(json.dumps([s for s in summary if s['kind']=='all'],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
