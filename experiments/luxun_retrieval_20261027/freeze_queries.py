import hashlib,json,re,random
from pathlib import Path
HERE=Path(__file__).resolve().parent
def main():
    targets=json.loads((HERE/'targets.json').read_text(encoding='utf8'))
    specs={int(a):(b,c) for a,b,c in (line.split('|') for line in (HERE/'query_specs.txt').read_text(encoding='utf8').splitlines() if line.strip())}
    assert set(specs)==set(range(1,61))
    queries=[]
    rng=random.Random(20261027)
    for t in targets:
        clauses=re.findall(r'[\u4e00-\u9fffA-Za-z0-9]+',t['text'])
        clause=max(clauses,key=len)
        a=max(0,(len(clause)-16)//2)
        literal=clause[a:a+16]
        keyword,paraphrase=specs[t['target_no']]
        eligible=[i for i,c in enumerate(paraphrase) if '\u4e00'<=c<='\u9fff']
        pos=rng.choice(eligible)
        deleted=paraphrase[:pos]+paraphrase[pos+1:]
        for kind,text in [('literal',literal),('keyword',keyword),('paraphrase',paraphrase),('deletion',deleted)]:
            queries.append({'id':f"T{t['target_no']:02d}-{kind}",'target_no':t['target_no'],'target_id':t['id'],
                            'book':t['book'],'kind':kind,'text':text,
                            'deleted_position':pos if kind=='deletion' else None})
    out=HERE/'queries.json'
    if out.exists():raise RuntimeError('Frozen queries already exist')
    out.write_text(json.dumps(queries,ensure_ascii=False,indent=2),encoding='utf8')
    manifest={'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'n_targets':60,'n_queries':240,
      'authorship':'keyword and paraphrase queries drafted by an AI assistant from randomly selected source fragments before retrieval outputs were computed; not collected from users',
      'gold':'one known target fragment per query; measures known-item retrieval, not exhaustive semantic relevance',
      'literal':'up to 16 consecutive characters from middle of longest unpunctuated clause',
      'deletion':'one uniformly selected Chinese character deleted from each paraphrase; seed 20261027',
      'fixed_parameters':{'bm25_k1':1.5,'bm25_b':0.75,'rrf_k':60,'rrf_depth':100},
      'analysis':'Hit@1,5,10, MRR@10; paired bootstrap over 60 target groups; separate query-type and collection analyses; 5 warm timing repetitions; corpus sizes 1000,2000,3784; all targets retained'}
    (HERE/'query_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(manifest,ensure_ascii=False))
if __name__=='__main__':main()
