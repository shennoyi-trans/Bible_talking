"""Rebuild the bundled corpus from the upstream USFX; do not paraphrase the text."""
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
source = ROOT / 'data/sources/chi-cuv-simp.usfx.xml'
target = ROOT / 'resources'
target.mkdir(exist_ok=True)
records = []
for book in ET.parse(source).getroot().findall('book'):
    title = book.findtext('h')
    chapter = None
    for element in book:
        if element.tag == 'c':
            chapter = int(element.attrib['id'])
        elif element.tag == 'v':
            verse = int(element.attrib['id'])
            text = (element.tail or '').strip()
            if not text:
                raise ValueError(f'Empty verse {title} {chapter}:{verse}')
            records.append({'text': text, 'citation': {'scheme': 'bible', 'edition_id': 'cuv-simp-open-bibles',
                'edition': '和合本（简体）', 'book': book.attrib['id'], 'book_name': title,
                'chapter': chapter, 'verse_start': verse, 'verse_end': verse,
                'label': f'{title} {chapter}:{verse}'}})
assert len(records) == 31100, f'Upstream verse count changed: {len(records)}'
with (target / 'cuv.jsonl').open('w', encoding='utf-8', newline='\n') as output:
    for record in records:
        output.write(json.dumps(record, ensure_ascii=False) + '\n')
manifest = {'name': 'Chinese Union Version (Simplified)', 'edition_id': 'cuv-simp-open-bibles',
    'source_url': 'https://github.com/seven1m/open-bibles/blob/master/chi-cuv-simp.usfx.xml',
    'license_statement_url': 'https://github.com/seven1m/open-bibles#translation-list',
    'upstream_license': 'Public Domain', 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'corpus_sha256': hashlib.sha256((target / 'cuv.jsonl').read_bytes()).hexdigest(),
    'books': 66, 'verses': len(records), 'parser': 'prepare_bible.py v1',
    'notes': 'Preserves the upstream wording and book names; counts follow this specific source, without filling missing verses.'}
(target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Prepared {len(records)} verses in {len(set(r["citation"]["book"] for r in records))} books.')
