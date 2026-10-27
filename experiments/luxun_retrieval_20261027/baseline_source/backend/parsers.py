"""Lossless quote boundaries, measured in Python Unicode code points [start, end)."""
import json
import re
from dataclasses import dataclass


@dataclass
class ParsedFragment:
    text: str
    start: int
    end: int
    citation: dict


def trimmed_span(text, start, end):
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def parse_text(text, title):
    result = []
    heading = ''
    for paragraph, match in enumerate(re.finditer(r'[^\r\n]+', text), 1):
        if match.group().lstrip().startswith('#'):
            heading = match.group().lstrip('# ').strip()
            continue
        start, end = trimmed_span(text, match.start(), match.end())
        # Retain paragraph boundaries; split long paragraphs at sentence boundaries.
        cursor = start
        while cursor < end:
            stop = min(cursor + 220, end)
            if stop < end:
                boundaries = list(re.finditer(r'[。！？!?；;]', text[cursor:stop]))
                if boundaries:
                    stop = cursor + boundaries[-1].end()
            left, right = trimmed_span(text, cursor, stop)
            if right > left:
                result.append(ParsedFragment(text[left:right], left, right, {
                    'scheme': 'document', 'title': title, 'paragraph': paragraph, 'heading': heading,
                    'label': f'{title} · {heading + " · " if heading else ""}第 {paragraph} 段'
                }))
            cursor = stop
    return text, result


def parse_records(records, title):
    if not isinstance(records, list) or not records:
        raise ValueError('JSON 需要非空数组，每条记录包含 text 和可选的 citation。')
    texts, result, offset = [], [], 0
    for i, item in enumerate(records):
        if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not item['text'].strip():
            raise ValueError(f'第 {i + 1} 条记录缺少有效的 text。')
        content = item['text']
        citation = item.get('citation') or {}
        if not isinstance(citation, dict):
            raise ValueError('citation 必须是对象。')
        citation = dict(citation)
        citation.setdefault('scheme', 'document')
        citation.setdefault('label', f'{title} · 第 {i + 1} 条')
        if not isinstance(citation['label'], str) or len(citation['label']) > 500:
            raise ValueError('出处 label 必须是 500 字以内的文本。')
        # Long records are split without changing the source or its locator.
        _, parts = parse_text(content, title) if len(content) > 400 else (content, [ParsedFragment(content, 0, len(content), citation)])
        for part in parts:
            result.append(ParsedFragment(part.text, offset + part.start, offset + part.end, citation))
        texts.append(content)
        offset += len(content) + 1
    return '\n'.join(texts), result


def parse_upload(raw, filename):
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('请上传 UTF-8 编码的文本。') from exc
    suffix = filename.rsplit('.', 1)[-1].lower()
    try:
        if suffix == 'json':
            return parse_records(json.loads(text), filename)
        if suffix == 'jsonl':
            return parse_records([json.loads(line) for line in text.splitlines() if line.strip()], filename)
        if suffix in {'txt', 'md'}:
            return parse_text(text, filename)
    except json.JSONDecodeError as exc:
        raise ValueError(f'JSON 格式错误：第 {exc.lineno} 行。') from exc
    raise ValueError('支持 TXT、Markdown、JSON、JSONL 文件。')


def index_spans(text):
    """Index whole passages and exact short speech excerpts. Never synthesize quotes."""
    spans = [(0, len(text))]
    for match in re.finditer(r'[「“]([^」”\n]{2,160})[」”]', text):
        start, end = trimmed_span(text, match.start(1), match.end(1))
        # Avoid equivalent full-passage vectors with only quote marks removed.
        if end - start < len(text) - 4:
            spans.append((start, end))
    return list(dict.fromkeys(spans))

