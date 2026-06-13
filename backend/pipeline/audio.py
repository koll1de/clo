"""Audio signal — find loudness/excitement spikes (screams, hype, hard laughing).

Pure stdlib + numpy: reads the 16 kHz mono wav that the transcribe stage already
produced and computes short-time RMS energy. Sustained spikes above the stream's
own baseline are where he reacts loudly. These corroborate transcript moments
(boost their score + land a zoom punch-in on the peak) and surface gameplay
reactions the transcript brain alone would miss.
"""
from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import Paths
from ..ffmpeg import extract_audio


@dataclass
class Reaction:
    start: float        # seconds (source)
    end: float
    peak: float         # seconds of the loudest moment
    level: float        # how many times louder than baseline (≈ excitement)


def _load_wav_mono16k(wav_path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return data, sr


def _ensure_wav(vod_path: str, job_id: str) -> Path:
    """Reuse the transcribe stage's wav if present, else extract one."""
    existing = Paths.work / f"{job_id}.wav"
    if existing.exists():
        return existing
    out = Paths.work / f"{job_id}.audio.wav"
    if not out.exists():
        extract_audio(vod_path, out)
    return out


def find_reactions(
    vod_path: str,
    job_id: str,
    *,
    win_s: float = 0.5,
    factor: float = 2.2,      # RMS this many× the baseline counts as a spike
    min_gap_s: float = 2.0,   # merge spikes closer than this into one reaction
    floor_frac: float = 0.08, # ignore spikes whose absolute RMS is below this (near-silence)
) -> list[Reaction]:
    wav = _ensure_wav(vod_path, job_id)
    data, sr = _load_wav_mono16k(wav)
    if data.size == 0:
        return []

    step = max(1, int(win_s * sr))
    n_win = data.size // step
    if n_win < 4:
        return []
    frames = data[: n_win * step].reshape(n_win, step)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)

    baseline = float(np.median(rms))
    if baseline <= 0:
        baseline = float(np.mean(rms)) or 1e-6
    peak_rms = float(np.max(rms)) or 1e-6
    thresh = max(baseline * factor, peak_rms * floor_frac)

    hot = rms > thresh
    reactions: list[Reaction] = []
    i = 0
    gap_wins = int(min_gap_s / win_s)
    while i < n_win:
        if not hot[i]:
            i += 1
            continue
        j = i
        last_hot = i
        # extend through small gaps so one reaction isn't split into many
        while j < n_win and (hot[j] or (j - last_hot) <= gap_wins):
            if hot[j]:
                last_hot = j
            j += 1
        seg = rms[i : last_hot + 1]
        peak_idx = i + int(np.argmax(seg))
        reactions.append(Reaction(
            start=round(i * win_s, 2),
            end=round((last_hot + 1) * win_s, 2),
            peak=round(peak_idx * win_s, 2),
            level=round(float(np.max(seg)) / baseline, 2),
        ))
        i = j
    # strongest first
    reactions.sort(key=lambda r: r.level, reverse=True)
    return reactions
