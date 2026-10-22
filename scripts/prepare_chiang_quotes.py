"""Verify curated, contiguous excerpts against saved Wikisource transcriptions."""
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.parsers import parse_upload

SOURCES = [
    ('軍校的使命與革命的人生', '1924-05-08', '2638621', [
        '你看這件事是多麼難的事，何等大的事呢！',
        '所以我們不能不十分努力奮鬥。',
        '因為一個人如果要做頂天立地的事，就要從九死一生當中磨練出來。',
        '是從什麼地方做起呢？',
        '說起來實在是很容易，很淺近的事，並非一件難事，不過要在我們自己身上先做起來就好了。',
        '怎樣做法呢？',
        '因為要革人家的命，先要革自家的命，如果自家不能改革自家，還想改革別人嗎？',
        '怎麼改革法子呢？',
        '就是要照正理做去，要上軌道去走。',
        '一個人如果沒有意義，並且不曉得來求做人的意義，那就是做了百年的人，也是枉費的，也是如同沒有生命的一個樣子的。',
        '不然，天地之間，何貴乎有人呢？',
        '如果我們的志向能夠真正的堅決，那我們的事業與理想，沒有不可成功，不可實行的道理。',
        '你們要曉得我們生活的目的，不單是顧著自己一個人的。',
        '比方說，只有我一個人有飯吃，其餘的人統沒有吃，那你一個人還能夠安安穩穩的吃飯嗎？',
        '就是你可安穩吃飯過去，那你的心可以安樂嗎？',
        '請各位要記住這兩句話。',
        '同志的意義，就是志同道合之謂。',
        '所謂志同道合者，決不是一時之權利可以苟合的。',
        '我們應該怎麼樣呢？',
        '其餘的話，且到下次再說',
    ]),
    ('革命警察的職責', '1928-02-27', '437707', [
        '有幾句要緊的話要對你們說明，希望各位切記做到。',
        '大家這樣的勞苦困難，是為甚麼呢？',
        '我們知道現在的辛苦困難是暫時的',
        '這個說法是不對的。',
        '現在雖然得不到薪水，領不到錢，然而要比從前更加努力，才可算是革命的警察！',
        '我們要使一般老百姓個個人都得到幸福，才是我們自己真正的幸福！',
        '現在常常看到這樣的毛病，這樣的警察還是沒有警察好得多，你們千萬不可這樣！',
        '還可以不盡職務嗎？',
        '現在我講你們的毛病，並不是譏笑或責備你們，因為從前沒有人對你們講，所以你們不加註意，現在我舉出你們的缺點，解釋給你們聽，你們照我的話來改正，這比求三年學問還要好。',
        '你們要詳細的記住才好！',
        '但是現在怎樣呢？',
        '這是最不好了。',
        '如果自己無法處置，就要報告區長，不可隨便讓他在路旁睡覺，如遇到臨時有病的百姓，一定要好好的看護他，或者僱車送他回家去。',
        '這些事情本是很容易改良的，不必花一個錢。',
        '有什麼用處？',
        '現在馬路上真髒得不成樣子！',
        '不要嚇他罵他，這是警察的責任。',
        '倘若不然，警察不能行使職權，還要警察幹什麼？',
        '今天到什麼人沒有？',
        '大家要曉得，做壞事的不一定是窮人，每有穿得很好的人做壞事。',
        '今天最後的話，請大家留心注意：',
        '我可以負責任懲辦他的！',
    ]),
    ('以整齊嚴肅的治軍精神治政', '1930-11-25', '437712', [
        '即或有局部之振作，仍難救全盤之散漫。',
        '然真富於責任之同志，仍應各自檢查其本身之過失而不得悉諉過於外緣之障礙；',
        '不能再蹈荒廢鬆懈之惡習。',
        '任人必求公平，律己必求廉潔',
        '勿以公帑為不足愛惜，而任意虛糜',
        '以後各部會皆須於此整個計劃之中，分工合作，以求進步。',
        '各部會長官，更應視其所屬員司之失職，即為其自身之失職。',
        '必如此，而後政治有清明之望。',
    ]),
    ('對盧溝橋事件之嚴正聲明', '1937-07-17', '2578839', [
        '我們是弱國，對自己國家力量要忠實估計。',
        '國家為進行建設，絕對的需要和平，過去數年中，不惜委曲忍痛，對外保持和平，即是此理。',
        '我們既是一個弱國，如果臨到最後關頭，便只有拚全民族的生命，以求國家的生存；',
        '可想見這一次的事件，並不是偶然的。',
        '換言之，就是人為刀俎，我為魚肉！',
        '這在世界上稍有人格的民族，都無法忍受的。',
        '萬一真到了無可避免的最後關頭，我們當然只有犧牲，只有抗戰！',
        '在和平根本絕望之前一秒鐘，我們還是希望和平的，希望由和平的外交方法，求得盧事的解決。',
        '我們希望和平，而不求苟安；準備應戰，而決不求戰。',
        '如果戰端一開，那就是地無分南北，年無分老幼，無論何人，皆有守土抗戰之責任，皆應抱定犧牲一切之決心。',
    ]),
]


class Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.items = []

    def handle_starttag(self, tag, attrs):
        if tag == 'p':
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'p' and self.current is not None:
            text = ''.join(self.current).strip()
            if text:
                self.items.append(text)
            self.current = None


def main():
    output = ROOT / 'examples' / 'corpora' / 'chiang-kai-shek'
    output.mkdir(parents=True, exist_ok=True)
    rows, manifest = [], []
    for title, date, revision, quotes in SOURCES:
        source = ROOT / 'resources' / 'chiang-kai-shek' / 'sources' / (title + '.html')
        raw = source.read_bytes()
        html = raw.decode('utf-8')
        assert f'oldid={revision}' in html
        assert '公有領域' in html
        parser = Paragraphs()
        parser.feed(html)
        # Only the actual speech, ending before the page's license notice.
        end = next(i for i, p in enumerate(parser.items) if p.startswith('中華民國《著作權法》'))
        paragraphs = parser.items[:end]
        source_url = f'https://zh.wikisource.org/w/index.php?title={quote(title)}&oldid={revision}'
        for text in quotes:
            matches = [(i, p) for i, p in enumerate(paragraphs, 1) if text in p]
            assert len(matches) == 1, (title, text, len(matches))
            paragraph_number, paragraph = matches[0]
            start = paragraph.index(text)
            rows.append({'text': text, 'citation': {
                'scheme': 'historical_speech', 'author': '蔣中正（蔣介石）', 'title': title, 'date': date,
                'label': f'蔣中正《{title}》 · {date} · 录文第 {paragraph_number} 段节选',
                'edition': '维基文库录文（原字）', 'url': source_url, 'source_revision': revision,
                'source_paragraph': paragraph_number,
                'source_start_offset': start, 'source_end_offset': start + len(text),
                'offset_unit': 'unicode_codepoint', 'offset_interval': '[start,end)',
                'context_before': paragraph[max(0, start - 100):start],
                'context_after': paragraph[start + len(text):start + len(text) + 100],
                'excerpt': True, 'verification': 'exact_substring_of_linked_transcription',
            }})
        manifest.append({'title': title, 'date': date, 'url': source_url, 'revision': revision,
            'quote_count': len(quotes), 'html_sha256': hashlib.sha256(raw).hexdigest(),
            'rights_note': '来源页面以公文/职务演讲标示为公有领域；未收录页面编辑说明。'})
    assert len(rows) == 60 and len({r['text'] for r in rows}) == 60
    target = output / '蒋介石语录-60条-原字版.jsonl'
    target.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    source_text, parsed = parse_upload(target.read_bytes(), target.name)
    assert len(parsed) == len(rows)
    assert all(p.text == row['text'] and p.citation == row['citation'] for p, row in zip(parsed, rows))
    assert all(source_text[p.start:p.end] == p.text for p in parsed)
    (output / 'sources.json').write_text(json.dumps({'retrieved_at': '2026-10-21', 'sources': manifest,
        'quotes': len(rows), 'corpus_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'verification': '60 exact contiguous excerpts; Python import parser passed; no facsimile collation'},
        ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Verified {len(rows)} excerpts from {len(manifest)} sources; import parser passed.')
    print(target)


if __name__ == '__main__':
    main()
