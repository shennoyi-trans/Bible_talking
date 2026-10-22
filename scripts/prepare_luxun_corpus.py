"""Build traceable, importable Lu Xun text from the downloaded public transcription.

No database writes or model calls. Source cache: data/luxun-research/doosho-complete.txt.
Only standard library dependencies. Rebuild: python scripts/prepare_luxun_corpus.py
"""
import bisect
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/luxun-research/doosho-complete.txt'
DEST = ROOT / 'examples/corpora/lu-xun'
META = ROOT / 'resources/lu-xun'
SOURCE_URL = 'https://raw.githubusercontent.com/dooshu/shu/main/cn/116.txt'


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def clean(text):
    # These are the transcription's numbered editorial footnotes, not author prose.
    cut = re.search(r'(?m)^(?:注释|\[\d+\][ \u3000]).*$', text)
    if cut:
        text = text[:cut.start()]
    text = re.sub(r'\[\d+\]', '', text)
    return text.strip()


def locate_sections(source):
    toc_end = source.index('\n\n')
    positions = defaultdict(list)
    for match in re.finditer(r'(?m)^([^\n]+)$', source):
        if match.start() > toc_end:
            positions[match.group(1)].append((match.start(), match.end()))
    sections, counts, cursor = [], [0] * 12, toc_end
    for line in source[:toc_end].splitlines()[1:]:
        depth = len(line) - len(line.lstrip('\u3000'))
        title = line.strip()
        counts[depth] += 1
        counts[depth + 1:] = [0] * (11 - depth)
        candidates = positions[title]
        index = bisect.bisect_right(candidates, (cursor, len(source)))
        if index >= len(candidates):
            raise ValueError(f'Unmatched TOC entry: {title}')
        start, end = candidates[index]
        path = counts[1:depth + 1].copy()
        sections.append(dict(path=path, title=title, start=start, body=end))
        cursor = end
    for index, section in enumerate(sections):
        section['end'] = sections[index + 1]['start'] if index + 1 < len(sections) else len(source)
    return sections


def split_preamble(body):
    """Keep author prefaces hidden under a collection's editorial introduction."""
    headings = list(re.finditer(r'\n{5,}([^\n]+)\n{3,}', body))
    result = []
    for i, match in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        if re.sub(r'\[\d+\]', '', match.group(1)) in {'题记', '自序', '小引', '题辞', '序言', '前记'}:
            result.append((match.group(1), body[match.end():end], match.end(), end))
    return result


def collection_name(unit):
    if unit['kind'] == 'diaries':
        return '鲁迅日记'
    if unit['kind'] == 'letters':
        return '两地书' if unit['path'][:2] == [11, 1] else '书信'
    return unit['chain'][1].removeprefix('附录 ')


def collection_filename(collection):
    suffix = {'书信': '（1904—1936）', '鲁迅日记': '（1912—1936）'}.get(collection, '')
    return collection + suffix + '.jsonl'


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    META.mkdir(parents=True, exist_ok=True)
    previous_manifest = json.loads((META / 'manifest.json').read_text(encoding='utf-8')) if (META / 'manifest.json').exists() else {}
    raw = SOURCE.read_bytes()
    source = raw.decode('utf-8-sig')
    sections = locate_sections(source)
    lookup = {tuple(s['path']): s for s in sections}
    units, excluded = [], []

    def add(section, title, body, kind, start=None, end=None):
        body = clean(body)
        if not body:
            return
        path = section['path']
        chain = [re.sub(r'\[\d+\]', '', lookup[tuple(path[:n])]['title']) for n in range(1, len(path) + 1)]
        if path[0] == 8:
            chain.insert(1, '集外集拾遗补编')
        if path[0] in (12, 13, 14):
            chain.insert(1, '书信')
        if title != section['title']:
            chain.append(re.sub(r'\[\d+\]', '', title))
        units.append(dict(id='.'.join(map(str, path)) + f'.{len(units)+1}', path=path,
                          title=re.sub(r'\[\d+\]', '', title), chain=chain, kind=kind,
                          source_url='https://doosho.com/cn/116/' + '/'.join(map(str, path)),
                          source_start=section['body'] if start is None else start,
                          source_end=section['end'] if end is None else end, text=body))

    for section in sections:
        path, title = section['path'], section['title']
        volume = path[0]
        body = source[section['body']:section['end']]
        ancestors = [lookup[tuple(path[:n])]['title'] for n in range(1, len(path)+1)]
        reason = None
        if volume >= 17:
            reason = '现代人物书刊注释、年表及索引，不作为鲁迅正文'
        elif any(t == '注释' for t in ancestors):
            reason = '现代编注'
        elif len(path) == 1:
            reason = '卷首版权页、插图说明及编者导言'
        elif tuple(path) == (6, 3, 2, 22):
            reason = '许广平所作后记'
        elif volume == 14 and path[1] >= 2:
            reason = '外文信中译文或附录混合材料，须核对翻译者和作者范围'
        if reason:
            excluded.append(dict(path=path, title=title, reason=reason))
            continue
        # Collections have modern bibliographical introductions followed by author prefaces.
        if ((volume <= 10 and len(path) == 2 and volume != 8) or path == [11, 1]):
            prefaces = split_preamble(body)
            for heading, content, offset, end_offset in prefaces:
                add(section, heading, content, 'works' if volume <= 10 else 'letters', section['body']+offset, section['body']+end_offset)
            if path == [9, 2]:
                # This opening has no separate TOC heading; only its first paragraph is editorial.
                marker = '我所讲的是中国小说的历史的变迁。'
                offset = body.index(marker)
                add(section, '开场', body[offset:], 'works', section['body']+offset)
            excluded.append(dict(path=path, title=title, reason='去除文集编者导言；其中作者自序另行保留', retained_prefaces=len(prefaces)))
            continue
        if path[:2] == [11, 2] and len(path) == 2:
            excluded.append(dict(path=path, title=title, reason='书信集现代编辑说明'))
            continue
        if path[:2] == [11, 1]:
            if len(path) < 4:
                continue
            text = clean(body)
            # The first two series address Guangping; third series uses her initials.
            is_luxun = text.startswith(('广平兄：', '广平仁兄大人', 'H.M.D', 'H.D：', 'D.H：', 'D.H.M：', 'D.L.ET D.H.M：'))
            is_luxun = is_luxun or tuple(path) in {(11, 1, 1, 32), (11, 1, 2, 5)}
            if not is_luxun:
                excluded.append(dict(path=path, title=title, reason='《两地书》许广平来信或合写/署名待核；不并入鲁迅原文库'))
                continue
            add(section, title, body, 'letters')
        elif volume <= 10:
            # Empty year/part containers are skipped; their actual children remain.
            if body.strip():
                add(section, title, body, 'works')
        elif volume <= 14:
            if re.match(r'^[0-9〇]{6}', title):
                add(section, title, body, 'letters')
        else:
            add(section, title, body, 'diaries')

    # Keep original work/collection names visible as resource filenames.
    records_by_collection = defaultdict(list)
    collection_volumes = defaultdict(set)
    unit_inventory, duplicates = [], []
    hashes = {}
    for unit in units:
        digest = hashlib.sha256(unit['text'].encode('utf-8')).hexdigest()
        if digest in hashes:
            duplicates.append(dict(id=unit['id'], duplicate_of=hashes[digest], title=unit['title']))
            continue
        hashes[digest] = unit['id']
        collection = collection_name(unit)
        collection_volumes[collection].add(unit['path'][0])
        display_chain = unit['chain'][1:]
        if unit['kind'] == 'diaries':
            display_chain = [collection] + display_chain
        else:
            display_chain = [collection] + display_chain[1:]
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', unit['text']) if p.strip()]
        year = None
        if unit['kind'] == 'diaries':
            v, i = unit['path']
            year = (1911+i if i <= 10 else 1912+i) if v == 15 else (1926+i if i <= 10 else 1922)
        retained_characters, retained_paragraphs = 0, 0
        for number, paragraph in enumerate(paragraphs, 1):
            if re.search('[\ufffd\ue000-\uf8ff]', paragraph):
                excluded.append(dict(path=unit['path'], title=unit['title'], paragraph=number,
                                     reason='本段含替换字符或私用区字符，暂缓导入；同篇其余段落保留'))
                continue
            citation = dict(scheme='document', author='鲁迅', label='鲁迅 · ' + ' · '.join(display_chain) + f' · 第{number}段',
                            title=unit['title'], collection=collection, source_volume=unit['path'][0], collection_path=unit['chain'], paragraph=number,
                            source_url=unit['source_url'], source_id=unit['id'],
                            edition='读书网所标2005年版网络转录；未逐字校勘',
                            text_role='作品文本，可能包含人物对白、他人引文或编译内容')
            if year:
                citation['year'] = year
                if year == 1922:
                    citation['completeness'] = '仅存世断片'
            records_by_collection[collection].append(dict(text=paragraph, citation=citation))
            retained_characters += len(paragraph)
            retained_paragraphs += 1
        unit_inventory.append({k: v for k, v in unit.items() if k != 'text'} | dict(collection=collection, file=collection_filename(collection), characters=retained_characters, paragraphs=retained_paragraphs, source_paragraphs=len(paragraphs), sha256=digest))

    files = []
    for collection, records in records_by_collection.items():
        name = collection_filename(collection)
        payload = ''.join(json.dumps(r, ensure_ascii=False, separators=(',', ':'))+'\n' for r in records).encode('utf-8')
        if len(payload) >= 10 * 1024 * 1024:
            raise ValueError(f'{name} exceeds upload limit')
        (DEST / name).write_bytes(payload)
        files.append(dict(file=name, collection=collection, source_volumes=sorted(collection_volumes[collection]), records=len(records), characters=sum(len(r['text']) for r in records), bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()))

    # Remove only obsolete generated files still matching their recorded hashes.
    current_names = {f['file'] for f in files}
    obsolete = []
    for old in previous_manifest.get('files', []):
        if old['file'] in current_names:
            continue
        path = (DEST / old['file']).resolve()
        if path.parent != DEST.resolve():
            raise ValueError('Previous manifest contains a path outside the corpus directory')
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != old['sha256']:
                raise ValueError(f'Preserving modified obsolete file: {path}')
            obsolete.append(path)
    for path in obsolete:
        path.unlink()

    dump(META / 'sections.json', [s | dict(source_url='https://doosho.com/cn/116/'+'/'.join(map(str,s['path']))) for s in sections])
    dump(META / 'works.json', unit_inventory)
    dump(META / 'excluded.json', excluded)
    dump(META / 'duplicates.json', duplicates)
    manifest = dict(created_date='2026-10-22', source_url=SOURCE_URL,
                    source_index='https://doosho.com/cn/116', source_cache=str(SOURCE.relative_to(ROOT)),
                    source_sha256=hashlib.sha256(raw).hexdigest(), source_bytes=len(raw), source_characters=len(source),
                    toc_entries=len(sections), retained_text_units=len(unit_inventory),
                    records=sum(f['records'] for f in files), characters=sum(f['characters'] for f in files),
                    file_grouping='original_collection', files=files, excluded_entries=len(excluded), duplicate_units=len(duplicates),
                    transformations=['依据原文件目录顺序定位全部条目', '去除现代导言、注释、脚注锚点', '段首尾去空白，保留原段落和措辞，不繁简转换、不补写、不润色', '按文集/篇目/段落保留出处；卷8补充集名', '完全相同的文本单元去重；内容相近的不同版本不强制合并'],
                    limitations=['网络转录版，非出版社认证数字底本，未与纸本逐字校勘', '篇目含角色对白及他人引文，不应将每段视为鲁迅本人观点', '排除外国人士书信和第14卷附录等待核材料；译文集、辑录古籍和科学著作尚未纳入', '1922年日记仅存世断片；统计为文本单元和段落数，不是独立作品篇数', '原作、现代注释、译文和网站内容许可分别处理，不能把全套现代版标作无条件公版'])
    dump(META / 'manifest.json', manifest)
    with (META / 'catalog.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['id', '卷', '文集', '导入文件', '标题路径', '类别', '字符数', '段落数', '来源'])
        for unit in unit_inventory:
            writer.writerow([unit['id'], unit['path'][0], unit['collection'], unit['file'], ' / '.join(unit['chain']), unit['kind'], unit['characters'], unit['paragraphs'], unit['source_url']])
    print(json.dumps({k:v for k,v in manifest.items() if k not in {'files','limitations','transformations'}}, ensure_ascii=False, indent=2))
    print('Files:', [(f['file'], f['records'], f['bytes']) for f in files])


if __name__ == '__main__':
    main()
