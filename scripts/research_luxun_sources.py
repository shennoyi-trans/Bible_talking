"""Fetch a small, fixed set of public source pages for corpus inspection."""
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
URLS = {
    'doosho-complete.txt': 'https://raw.githubusercontent.com/dooshu/shu/main/cn/116.txt',
    'doosho-diary.html': 'https://doosho.com/cn/116/15/1',
    'doosho-letters.html': 'https://doosho.com/cn/116/11/2',
}

if __name__ == '__main__':
    dest = ROOT / 'data/luxun-research'
    dest.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        if (dest / name).exists():
            print(name, 'cached; preserved', flush=True)
            continue
        try:
            response = requests.get(url, timeout=90)
            response.raise_for_status()
            (dest / name).write_bytes(response.content)
            print(name, response.status_code, len(response.content), flush=True)
        except requests.RequestException as exc:
            print(name, type(exc).__name__, str(exc), flush=True)
