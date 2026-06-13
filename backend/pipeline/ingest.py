"""Stage 1 — get the VOD (and chat) onto disk.

Local file: referenced in place.
Twitch VOD url: downloaded with yt-dlp into data/vods/.
Twitch chat (if config ingest.download_chat and the chat-downloader package is
installed) is saved to data/work/<job>.chat.json for the chat signal.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from ..config import CONFIG, Paths
from ..ffmpeg import ffmpeg_bin
from ..models import Job


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _download_chat(url: str, job_id: str) -> str | None:
    """Save Twitch VOD chat to <job>.chat.json. Optional: needs the chat-downloader
    package. Returns the path, or None if unavailable/empty (a missing chat must not
    fail the job)."""
    try:
        from chat_downloader import ChatDownloader
    except ImportError:
        print("[ingest] chat-downloader not installed; skipping chat. "
              "`pip install chat-downloader` to enable the chat signal.")
        return None
    try:
        chat = ChatDownloader().get_chat(url)
        msgs = []
        for m in chat:
            t = m.get("time_in_seconds")
            if t is None:
                continue
            msgs.append({"t": float(t), "text": m.get("message") or ""})
    except Exception as e:
        print(f"[ingest] chat download failed (continuing without chat): {e}")
        return None
    if not msgs:
        return None
    out = Paths.work / f"{job_id}.chat.json"
    out.write_text(json.dumps(msgs, ensure_ascii=False), encoding="utf-8")
    print(f"[ingest] downloaded {len(msgs)} chat messages")
    return str(out)


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
        if CONFIG.get("ingest", {}).get("download_chat"):
            job.chat_path = _download_chat(job.source, job.id)
        return job

    raise ValueError(f"Unknown source_type: {job.source_type}")
