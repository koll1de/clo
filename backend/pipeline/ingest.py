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
from ..ffmpeg import ffmpeg_bin, probe_duration
from ..models import Job


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _safe_remove(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
    except Exception:
        pass


def _set_duration(job: Job) -> None:
    """Record the VOD length so the UI can show real footage hours. Best-effort —
    a probe failure must never fail the job."""
    try:
        if job.vod_path:
            job.duration = probe_duration(job.vod_path)
    except Exception as e:
        print(f"[ingest] duration probe failed (continuing): {e}")


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
    """Per-site flags. --ffmpeg-location is always passed (ffmpeg may not be on PATH, and
    yt-dlp needs it to merge video+audio). YouTube increasingly demands authentication
    ('Sign in to confirm you're not a bot'); the reliable bypass is the user's logged-in
    cookies — a cookies.txt (cookies_file) or pulled live from a browser profile
    (cookies_from_browser: chrome|edge|firefox|brave|...). Both configured under `ingest`."""
    args = ["--ffmpeg-location", os.path.dirname(ffmpeg_bin())]
    icfg = CONFIG.get("ingest", {})
    cookies_file = str(icfg.get("cookies_file") or "").strip()
    browser = str(icfg.get("cookies_from_browser") or "").strip()
    if cookies_file:
        args += ["--cookies", cookies_file]
    elif browser:
        args += ["--cookies-from-browser", browser]
    return args


def ingest(job: Job) -> Job:
    if job.source_type == "local":
        p = Path(job.source)
        if not p.exists():
            raise FileNotFoundError(f"VOD not found: {p}")
        job.vod_path = str(p)
        _set_duration(job)
        return job

    if job.source_type == "twitch":
        if not _is_url(job.source):
            raise ValueError(f"Not a URL: {job.source}")
        out = Paths.vods / f"{job.id}.mp4"
        # Cap at 1080p and prefer h264 (avc1): the output is a downscaled 9:16 clip,
        # so pulling a multi-GB AV1/4K master is pure waste and slows every later stage.
        # _ytdlp_extra_args supplies --ffmpeg-location (ffmpeg isn't on PATH here, so
        # without it yt-dlp can't MERGE the separate video+audio streams into one mp4).
        cmd = [
            "yt-dlp",
            "-f", ("bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]/"
                   "bestvideo[height<=1080]+bestaudio/"
                   "best[height<=1080]/best[ext=mp4]/best"),
            "--merge-output-format", "mp4",
            "-o", str(out),
            *_ytdlp_extra_args(job.source),
            job.source,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp failed:\n{proc.stderr[-2000:]}")
        if not out.exists():
            # yt-dlp can exit 0 yet leave unmerged stream fragments (e.g. when the
            # merge step silently can't run). Surface what landed, then clean it up so
            # a multi-GB orphan doesn't pile up in data/vods on every retry.
            leftovers = sorted(Paths.vods.glob(f"{job.id}*"))
            names = ", ".join(p.name for p in leftovers) or "nothing"
            for p in leftovers:
                _safe_remove(p)
            raise RuntimeError(
                "yt-dlp finished but produced no merged mp4 (likely the audio/video "
                f"merge failed). Leftover files (now removed): {names}\n"
                f"{(proc.stderr or '')[-1200:]}")
        job.vod_path = str(out)
        _set_duration(job)
        if CONFIG.get("ingest", {}).get("download_chat"):
            job.chat_path = _download_chat(job.source, job.id)
        return job

    raise ValueError(f"Unknown source_type: {job.source_type}")
