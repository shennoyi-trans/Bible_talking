"""Prepare a source-linked evaluation corpus without opening application databases."""
import hashlib, json, random, sys
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from backend.parsers import parse_upload

BOOKS = ['呐喊','彷徨','野草','朝花夕拾','故事新编']
SEED = 20261027

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(name, obj):
    (HERE/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def main():
    corpus, files, counts = [], [], {}
    seen = set()
    for book in BOOKS:
        path = ROOT/'examples/corpora/lu-xun'/f'{book}.jsonl'
        _, fragments = parse_upload(path.read_bytes(), path.name)
        start = len(corpus)
        for j, f in enumerate(fragments):
            if f.text in seen: continue
            seen.add(f.text)
            corpus.append({'id':len(corpus),'book':book,'fragment_index':j,'text':f.text,
                           'citation':f.citation,'start':f.start,'end':f.end})
        counts[book]={'parsed':len(fragments),'unique':len(corpus)-start}
        files.append({'path':str(path.relative_to(ROOT)),'sha256':sha(path)})
    save('corpus.json', corpus)
    rng=random.Random(SEED)
    targets=[]
    for book in BOOKS:
        pool=[d for d in corpus if d['book']==book and 60<=len(d['text'])<=220]
        chosen=rng.sample(pool,12)
        for d in chosen:
            targets.append({'target_no':len(targets)+1, **d})
    save('targets.json',targets)
    save('corpus_manifest.json',{'seed':SEED,'books':counts,'total_unique':len(corpus),
         'selection':'12 uniformly sampled unique fragments per collection, length 60..220 Unicode characters; no result-based filtering',
         'sources':files,'parser_sha256':sha(ROOT/'backend/parsers.py'),
         'vectors_sha256':sha(ROOT/'backend/vectors.py'),'corpus_sha256':sha(HERE/'corpus.json')})
    for d in targets:
        print(f"{d['target_no']:02d} | {d['id']} | {d['citation']['label']}\n{d['text']}\n")
    print(json.dumps(counts,ensure_ascii=False))

if __name__=='__main__': main()
