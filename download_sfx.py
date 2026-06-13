"""Build a small sound-effects library from myinstants.com for the AI to pick from.

    python download_sfx.py            # ~24 trending sounds
    python download_sfx.py 40         # download up to 40

Saves .mp3 files into assets/sfx/. The vision gate sees the file names (e.g. 'vine-boom',
'bruh') and may attach ONE to a clip when it fits a punchline/fail/clutch. Re-run anytime
to refresh the library; delete files you don't want the AI to use.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
SFX_DIR = ROOT / "assets" / "sfx"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
# trending pages (US + global) give a good spread of recognisable meme sounds
PAGES = [
    "https://www.myinstants.com/en/index/us/",
    "https://www.myinstants.com/en/index/global/",
]


def _clean(stem: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-").lower()
    return stem[:40] or "sound"


def main(limit: int = 24) -> None:
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    saved = 0
    for page in PAGES:
        if saved >= limit:
            break
        try:
            html = requests.get(page, headers=HEADERS, timeout=20).text
        except Exception as e:
            print(f"  could not fetch {page}: {e}")
            continue
        for rel in re.findall(r"/media/sounds/[^\"']+\.mp3", html):
            if saved >= limit or rel in seen:
                continue
            seen.add(rel)
            name = _clean(Path(rel).stem)
            dst = SFX_DIR / f"{name}.mp3"
            if dst.exists():
                continue
            url = "https://www.myinstants.com" + rel
            try:
                data = requests.get(url, headers=HEADERS, timeout=20).content
                if len(data) < 1000:        # skip empties / error pages
                    continue
                dst.write_bytes(data)
                saved += 1
                print(f"  [{saved}] {name}.mp3 ({len(data)//1024} KB)")
            except Exception as e:
                print(f"  skip {name}: {e}")
    print(f"done — {saved} new sounds in {SFX_DIR}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    main(n)
