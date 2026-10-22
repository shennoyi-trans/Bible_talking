"""Verify delivered corpus provenance, upload compatibility, coverage and counts."""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.parsers import parse_upload
from scripts.prepare_luxun_corpus import clean


def main():
    meta = ROOT / 'resources/lu-xun'
    manifest = json.loads((meta / 'manifest.json').read_text(encoding='utf-8'))
    raw = (ROOT / manifest['source_cache']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest['source_sha256']
    source = raw.decode('utf-8-sig')
    units = json.loads((meta / 'works.json').read_text(encoding='utf-8'))
    by_id = {unit['id']: unit for unit in units}
    paragraphs = {}
    for unit in units:
        text = clean(source[unit['source_start']:unit['source_end']])
        assert hashlib.sha256(text.encode()).hexdigest() == unit['sha256'], unit['id']
        paragraphs[unit['id']] = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    records_total, parsed_total, char_total = 0, 0, 0
    file_results = []
    actual_files = {p.name for p in (ROOT / 'examples/corpora/lu-xun').glob('*.jsonl')}
    assert actual_files == {f['file'] for f in manifest['files']}
    for item in manifest['files']:
        path = ROOT / 'examples/corpora/lu-xun' / item['file']
        payload = path.read_bytes()
        assert len(payload) < 10 * 1024 * 1024
        assert hashlib.sha256(payload).hexdigest() == item['sha256']
        records = [json.loads(line) for line in payload.decode('utf-8').splitlines()]
        assert len(records) == item['records']
        for record in records:
            text, citation = record['text'], record['citation']
            unit = by_id[citation['source_id']]
            assert paragraphs[unit['id']][citation['paragraph']-1] == text
            assert not re.search('[\ufffd\ue000-\uf8ff]', text)
            assert not re.match(r'^\[\d+\]', text)
            assert citation['source_url'] == unit['source_url']
            assert unit['file'] == path.name
            assert citation['collection'] == item['collection'] == unit['collection']
            assert citation['source_volume'] == unit['path'][0]
            assert citation['label'].startswith('鲁迅 · ' + item['collection'] + ' · ')
            assert not re.search(r'鲁迅全集\.\d+', citation['label'])
            assert '许广平所作后记' not in citation['label']
        text, fragments = parse_upload(payload, path.name)
        assert all(text[f.start:f.end] == f.text for f in fragments)
        records_total += len(records)
        parsed_total += len(fragments)
        char_total += sum(len(r['text']) for r in records)
        file_results.append(dict(file=path.name, records=len(records), parsed_fragments=len(fragments), bytes=len(payload)))
    assert records_total == manifest['records']
    assert char_total == manifest['characters']
    expected = {
        '呐喊': ['狂人日记','孔乙己','药','明天','一件小事','头发的故事','风波','故乡','阿Q正传','端午节','白光','兔和猫','鸭的喜剧','社戏'],
        '彷徨': ['祝福','在酒楼上','幸福的家庭','肥皂','长明灯','示众','高老夫子','孤独者','伤逝','弟兄','离婚'],
        '故事新编': ['补天','奔月','理水','采薇','铸剑','出关','非攻','起死'],
    }
    for collection, titles in expected.items():
        observed = {heading for u in units if collection in u['chain'] for heading in u['chain']}
        assert set(titles) <= observed, (collection, set(titles)-observed)
    assert len([u for u in units if u['kind']=='diaries']) == 25
    assert not any(u['path'] == [6,3,2,22] for u in units)
    report = dict(verified_date='2026-10-22', records=records_total, parsed_fragments=parsed_total,
                  characters=char_total, files=file_results,
                  checks=['原始缓存与全部导入文件SHA-256一致', '每段与可定位的源文本经声明清洗后完全一致',
                          '按原文集名称分文件，段落文集与文件名逐条匹配；无旧分卷文件残留',
                          '所有文件通过项目parse_upload，字符偏移逐条核对通过', '单文件均低于10MiB',
                          '三部小说集14+11+8篇标题齐备', '25个日记年度单元齐备（1922仅断片）',
                          '无替换字符、私用区字符和数字注释段落', '许广平末编后记未混入'],
                  not_verified=['未逐字与纸本校勘', '未批量检查在线链接未来可用性', '未建立向量索引或评价真实模型召回率', '未完成逐段引文/译文作者判定'])
    (meta / 'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='files'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
