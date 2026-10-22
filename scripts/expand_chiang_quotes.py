"""Build simplified import files from saved, attributable transcriptions.

Tool-only dependencies: beautifulsoup4==4.15.0, opencc-python-reimplemented==0.1.7.
Offsets always address ORIGINAL text in the saved paragraph snapshots, not simplified text.
Run from any directory; network access is not used by this builder.
"""
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from opencc import OpenCC

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.parsers import parse_upload

SOURCE = ROOT / 'resources/chiang-kai-shek/expanded-sources'
OUTPUT = ROOT / 'examples/corpora/chiang-kai-shek/简体扩充版'
CC = OpenCC('t2s')
VARIANTS = dict(zip('囘砲尙鬬効畧寃徧塲伕剏泒幵䜩', '回炮尚斗效略冤遍场夫创派开宴'))


def simplify(text):
    return CC.convert(text).translate(str.maketrans(VARIANTS))


# Opening date/location and editorial synopsis paragraphs, verified per downloaded page.
SKIP = {str(i).zfill(2): 2 for i in range(1, 28)}
SKIP.update({'20': 1, '21': 1, '22': 1, '24': 1, '26': 0})


def norm(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', simplify(text)) if c.isalnum())


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def build():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    previous = ROOT / 'examples/corpora/chiang-kai-shek/蒋介石语录-60条-原字版.jsonl'
    old = [json.loads(line) for line in previous.read_text(encoding='utf-8').splitlines()]
    for row in old:
        original = row['text']
        row['text'] = simplify(original)
        c = row['citation']
        c['original_text'] = original
        c['original_title'] = c['title']
        for key in ('author', 'title', 'label'):
            c[key] = simplify(c[key])
        c['edition'] = '维基文库录文，OpenCC t2s 简体转写及异体字统一'
        c['date_precision'] = 'day'
        c['context_language'] = 'source_original'
        c['verification'] = 'simplified_from_exact_substring_of_linked_transcription'
    manifest, candidates, rejected = [], [], []
    seen = {norm(row['text']) for row in old}
    downloads = json.loads((SOURCE / 'download-manifest.json').read_text(encoding='utf-8'))
    for source in downloads:
        file = SOURCE / source['file']
        soup = BeautifulSoup(file.read_text(encoding='utf-8'), 'html.parser')
        body = soup.select_one('.mw-parser-output')
        header = body.select_one('#headerContainer').get_text(' ', strip=True)
        assert '蔣中正' in header and source['pd'] and '公有領域' in body.get_text()
        date_match = re.search(r'(\d{4})年(?:(\d{1,2})月)?(?:(\d{1,2})日)?', header)
        assert date_match, header
        parts = [v for v in date_match.groups() if v]
        date = '-'.join([parts[0]] + [v.zfill(2) for v in parts[1:]])
        precision = ['year', 'month', 'day'][len(parts)-1]
        paragraphs = [p.get_text().strip() for p in body.find_all('p', recursive=False)]
        write_json(SOURCE / f'{file.stem}.paragraphs.json', paragraphs)
        source['header'] = header
        revision = parse_qs(urlparse(source['url']).query)['oldid'][0]
        count_before = len(candidates)
        for number, paragraph in enumerate(paragraphs, 1):
            if number <= SKIP[file.stem]:
                continue
            # Keep contiguous sentence / semicolon-clause spans, preserving punctuation.
            for seq, match in enumerate(re.finditer(r'[^。！？!?；;]+[。！？!?；;]+[」』”’）)]*', paragraph), 1):
                original = match.group().strip()
                start = match.start() + len(match.group()) - len(match.group().lstrip())
                end = start + len(original)
                key = f'{file.stem}-{number}-{seq}'
                text = simplify(original)
                reason = None
                if not 12 <= len(text) <= 180:
                    reason = 'length'
                elif re.search(r'[A-Za-z0-9\u00c0-\u024f*|�]', text):
                    reason = 'suspected_transcription_artifact'
                elif any(text.count(left) != text.count(right) for left, right in [('「','」'),('『','』'),('“','”'),('‘','’'),('（','）'),('(',')'),('【','】')]):
                    reason = 'unbalanced_quotation_or_parenthesis'
                elif text.startswith(('」','』','”','，','、','：','——')):
                    reason = 'fragment_or_editorial_heading'
                elif norm(text) in seen:
                    reason = 'duplicate'
                if reason:
                    rejected.append({'id': key, 'reason': reason})
                    continue
                seen.add(norm(text))
                c = {'scheme': 'historical_speech', 'author': '蒋中正（蒋介石）',
                     'title': simplify(source['title']), 'original_title': source['title'],
                     'date': date, 'date_precision': precision,
                     'label': f'蒋中正《{simplify(source["title"])}》 · {date} · 录文第 {number} 段节选',
                     'edition': '维基文库录文，OpenCC t2s 简体转写及异体字统一',
                     'url': source['url'], 'source_revision': revision,
                     'source_paragraph': number, 'source_start_offset': start, 'source_end_offset': end,
                     'offset_unit': 'unicode_codepoint', 'offset_interval': '[start,end)',
                     'context_before': paragraph[max(0,start-100):start],
                     'context_after': paragraph[end:end+100], 'context_language': 'source_original',
                     'original_text': original, 'excerpt': True, 'record_id': key,
                     'verification': 'simplified_from_exact_substring_of_linked_transcription'}
                assert paragraph[start:end] == original and simplify(original) == text
                candidates.append({'text': text, 'citation': c})
        manifest.append({**source, 'date': date, 'date_precision': precision,
                         'candidate_count': len(candidates)-count_before,
                         'html_sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
    (SOURCE / 'candidates.txt').write_text('\n'.join(f'{r["citation"]["record_id"]}\t{r["text"]}' for r in candidates), encoding='utf-8')
    exclusion_file = SOURCE / 'review-exclusions.json'
    exclusions = json.loads(exclusion_file.read_text(encoding='utf-8')) if exclusion_file.exists() else {}
    added = [r for r in candidates if r['citation']['record_id'] not in exclusions]
    all_rows = old + added
    assert len({norm(r['text']) for r in all_rows}) == len(all_rows)
    files = []
    for name, rows in [('蒋介石语录-简体完整版.jsonl', all_rows), ('蒋介石语录-简体仅新增.jsonl', added)]:
        path = OUTPUT / name
        path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
        assert path.stat().st_size < 10 * 1024 * 1024
        source_text, parsed = parse_upload(path.read_bytes(), path.name)
        assert len(parsed) == len(rows)
        assert all(p.text == row['text'] and p.citation == row['citation'] and source_text[p.start:p.end] == p.text for p,row in zip(parsed,rows))
        files.append({'file': name, 'count': len(rows), 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    for source in manifest:
        source['included_count'] = sum(r['citation']['url'] == source['url'] for r in added)
    old_manifest = json.loads((previous.parent / 'sources.json').read_text(encoding='utf-8'))
    write_json(OUTPUT / '来源与校验.json', {'retrieved_at': '2026-10-21', 'files': files,
        'previous_sources': old_manifest['sources'], 'added_sources': manifest,
        'conversion': {'library': 'opencc-python-reimplemented', 'version': '0.1.7', 'config': 't2s', 'variant_mapping': VARIANTS},
        'quality_note': '演讲录文的连续句段，不是逐条人工考证的名言集；原字与出处保留，未逐页对照初刊扫描。未擅自改正原录文错字。',
        'offset_note': '新增条目偏移对应 expanded-sources/NN.paragraphs.json 原字段落；此前60条偏移沿用原来源。',
        'automatic_exclusions': rejected, 'review_exclusions': exclusions})
    print(json.dumps({'candidates': len(candidates), 'added': len(added), 'total': len(all_rows), 'sources': len(manifest)+4, 'files': files}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    build()
