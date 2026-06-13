"""Download the two background-music beds the AI picks from.

    python download_music.py

Saves assets/music/calm.mp3 (Oblivion - Harvest Dawn, for boring/low-action and rage clips)
and assets/music/hype.mp3 (the high-energy track, for many-kills / good-play clips). The
renderer lays the chosen track UNDER the clip at low volume and sidechain-ducks it whenever
the streamer's voice gets loud (so it drops out during rages and comes back when he calms).

NOTE: these tracks are copyrighted — published Shorts/TikToks may get content-ID claims.
Replace the files in assets/music/ with your own anytime (keep the calm.mp3 / hype.mp3 names).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from backend.ffmpeg import ffmpeg_bin

ROOT = Path(__file__).resolve().parent
MUSIC_DIR = ROOT / "assets" / "music"
YTDLP = ROOT / ".venv" / "Scripts" / "yt-dlp.exe"

# (output stem, yt-dlp source). "ytsearch1:" picks the top hit for a query.
TRACKS = {
    "calm": "ytsearch1:The Elder Scrolls IV Oblivion Harvest Dawn soundtrack",
    "hype": "https://www.youtube.com/watch?v=3IOvCrL4ujo",
}


def fetch(stem: str, source: str) -> None:
    ff_dir = str(Path(ffmpeg_bin()).parent)
    out = str(MUSIC_DIR / f"{stem}.%(ext)s")
    cmd = [
        str(YTDLP),
        "--extractor-args", "youtube:player_client=tv_embedded",  # no-login (audio is fine)
        "--ffmpeg-location", ff_dir,
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "-o", out, "--no-playlist", source,
    ]
    print(f"[{stem}] downloading from: {source}")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"[{stem}] FAILED:\n{r.stderr[-1500:]}")
    else:
        print(f"[{stem}] ok -> {MUSIC_DIR / (stem + '.mp3')}")


def main() -> None:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    for stem, src in TRACKS.items():
        fetch(stem, src)


if __name__ == "__main__":
    main()
