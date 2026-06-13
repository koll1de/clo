"""Stage 1 — get the VOD (and chat) onto disk.

Local file: referenced in place.
Twitch VOD url: downloaded with yt-dlp into data/vods/.
Chat download is handled later (separate slice); chat_path stays None for now.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..config import Paths
from ..ffmpeg import ffmpeg_bin
from ..models import Job


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _ytdlp_extra_args(url: str) -> list[str]:
    """Per-site flags. ffmpeg location is always passed (it may not be on PATH);
    YouTube needs the tv_embedded client to get past its bot-gate."""
    args = ["--ffmpeg-location", os.path.dirname(ffmpeg_bin())]
    if "youtube.com" in url or "youtu.be" in url:
        args += ["--extractor-args", "youtube:player_client=tv_embedded"]
    return args


def ingest(job: Job) -> Job:
    if job.source_type == "local":
        p = Path(job.source)
        if not p.exists():
            raise FileNotFoundError(f"VOD not found: {p}")
        job.vod_path = str(p)
        return job

    if job.source_type == "twitch":
        if not _is_url(job.source):
            raise ValueError(f"Not a URL: {job.source}")
        out = Paths.vods / f"{job.id}.mp4"
        # yt-dlp handles Twitch VODs; keep it to a single mp4.
        cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", str(out),
            job.source,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp failed:\n{proc.stderr[-2000:]}")
        if not out.exists():
            raise RuntimeError("yt-dlp finished but no output file was produced")
        job.vod_path = str(out)
        return job

    raise ValueError(f"Unknown source_type: {job.source_type}")
