"""Download publicly accessible Wikisource speeches linked from the 1925 collection.

Tool-only dependencies: requests, beautifulsoup4. Cached HTML is never overwritten.
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'resources/chiang-kai-shek/expanded-sources'


def main():
    soup = BeautifulSoup((DEST / 'collection.html').read_text(encoding='utf-8'), 'html.parser')
    content = soup.select_one('.mw-parser-output')
    links = []
    for a in content.select('a[href]'):
        href = a['href']
        title = unquote(href.removeprefix('/wiki/'))
        if (href.startswith('/wiki/') and ':' not in title and
                ('訓' in title or '演說' in title or '講演' in title or '談話' in title) and
                'new' not in a.get('class', []) and title not in [x[0] for x in links]):
            links.append((title, urljoin('https://zh.wikisource.org', href)))
    manifest = []
    # The delivered edition uses the first 27 speeches; expand deliberately after review.
    for number, (title, url) in enumerate(links[:27], 1):
        path = DEST / f'{number:02d}.html'
        if not path.exists():
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=40)
            response.raise_for_status()
            path.write_bytes(response.content)
            time.sleep(3)
        page = BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
        permanent = page.select_one('#t-permalink a')['href']
        body = page.select_one('.mw-parser-output')
        header = body.select_one('#headerContainer')
        # Header has the attribution and date; retain the literal header as evidence.
        manifest.append({'requested_title': title, 'title': page.select_one('#firstHeading').get_text(),
                         'url': urljoin(url, permanent), 'file': path.name,
                         'header': header.get_text(' ', strip=True) if header else '',
                         'pd': '公有領域' in body.get_text()})
        print(number, manifest[-1], flush=True)
        (DEST / 'download-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
