"""ffmpeg/ffprobe helpers.

Resolves the binaries even when they aren't on PATH (common right after a winget
install, before the shell is restarted): we check PATH first, then the known
winget package location, then a config override.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=2)
def _resolve(name: str) -> str:
    # 1) explicit override via env var (set by launch.bat if needed)
    env = os.environ.get(f"CLIPMAKER_{name.upper()}")
    if env and Path(env).exists():
        return env
    # 2) on PATH
    found = shutil.which(name)
    if found:
        return found
    # 3) winget package install location (Gyan.FFmpeg)
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        pkgs = Path(local) / "Microsoft" / "WinGet" / "Packages"
        hits = list(pkgs.glob(f"Gyan.FFmpeg_*/**/bin/{name}.exe"))
        if hits:
            return str(hits[0])
    # fall back to bare name and let the OS error if truly missing
    return name


def ffmpeg_bin() -> str:
    return _resolve("ffmpeg")


def ffprobe_bin() -> str:
    return _resolve("ffprobe")


def run(args: list[str]) -> subprocess.CompletedProcess:
    """Run an ffmpeg/ffprobe command, raising with stderr on failure."""
    proc = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{proc.stderr[-2000:]}")
    return proc


def probe_duration(path: str | Path) -> float:
    """Return media duration in seconds."""
    proc = run([
        ffprobe_bin(), "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(path),
    ])
    return float(json.loads(proc.stdout)["format"]["duration"])


def extract_audio(src: str | Path, dst: str | Path, sample_rate: int = 16000) -> Path:
    """Extract mono PCM wav suitable for speech models."""
    dst = Path(dst)
    run([
        ffmpeg_bin(), "-y", "-i", str(src),
        "-vn", "-ac", "1", "-ar", str(sample_rate),
        "-c:a", "pcm_s16le", str(dst),
    ])
    return dst
