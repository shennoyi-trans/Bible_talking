"""Export only the verified Bible seed, including exact float32 vectors and citations."""
import json, shutil, sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.config import Settings
from backend.service import Library
from backend.models import Fragment, Resource
from sqlalchemy import select

out=ROOT/'build/android-assets'
(out/'web/offline').mkdir(parents=True,exist_ok=True)
model=next((ROOT/'data/models').rglob('model_optimized.onnx'))
shutil.copyfile(model,out/'model.onnx')
tokenizer=json.loads((model.parent/'tokenizer.json').read_text(encoding='utf-8'))
assert tokenizer['normalizer']=={'type':'BertNormalizer','clean_text':True,'handle_chinese_chars':True,'strip_accents':None,'lowercase':False}, tokenizer['normalizer']
vocab=tokenizer['model']['vocab']
(out/'vocab.txt').write_text('\n'.join(sorted(vocab,key=vocab.get))+'\n',encoding='utf-8')
lib=Library(Settings(data_dir=ROOT/'build/bible-seed',preload=False,worker_enabled=False))
try:
    corpora=lib.list_corpora()
    assert len(corpora)==1 and corpora[0]['corpus_id']=='corpus_cuv' and corpora[0]['fragment_count']==31100
    resources=lib.list_resources('corpus_cuv')
    with lib.db() as db:
        parts=list(db.scalars(select(Fragment).order_by(Fragment.resource_id,Fragment.fragment_index)))
        fragments=[{k:getattr(f,k) for k in ('fragment_id','resource_id','version_id','fragment_index','text','start_offset','end_offset','citation')} for f in parts]
        generations={r.active_generation for r in db.scalars(select(Resource))}
    lookup={f['fragment_id']:i for i,f in enumerate(fragments)}
    spans=[]; offset=None
    with (out/'web/offline/vectors.bin').open('wb') as dest:
        while True:
            points,offset=lib.vectors.client.scroll(lib.settings.collection,limit=512,offset=offset,with_vectors=True)
            for p in points:
                if p.payload['generation'] not in generations:continue
                spans.append([lookup[p.payload['fragment_id']],p.payload['start'],p.payload['end']])
                dest.write(np.asarray(p.vector,dtype='<f4').tobytes())
            if offset is None:break
    assert len(spans)==34627
    payload={'corpora':corpora,'resources':resources,'fragments':fragments,'spans':spans,'dimensions':512}
    (out/'web/offline/seed.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print('Exported 66 books, 31100 verses,',len(spans),'vectors; no private corpora.')
finally:lib.close()

# Compatibility fixtures exercise Unicode, punctuation, special tokens and truncation.
from fastembed import TextEmbedding
embedding=TextEmbedding('BAAI/bge-small-zh-v1.5',specific_model_path=str(model.parent),threads=2)
texts=['可以给我水喝吗？','有人出卖了我','Café hello WORLD!','𠀀😀你好\t[CLS] [MASK]','a\u0000b\u200bc','x'*101,'测试 '*600]
fixtures=[]
for text in texts:
    tokens=embedding.model.tokenizer.encode(text).ids
    vector=next(embedding.query_embed(text)).tolist()
    fixtures.append({'text':text,'tokens':tokens,'vector':vector})
(ROOT/'build/android-embedding-fixtures.json').write_text(json.dumps(fixtures,ensure_ascii=False),encoding='utf-8')
