"""Audio signal — find loudness/excitement spikes (screams, hype, hard laughing).

Pure stdlib + numpy: reads the 16 kHz mono wav that the transcribe stage already
produced and computes short-time RMS energy. Sustained spikes above the stream's
own baseline are where he reacts loudly. These corroborate transcript moments
(boost their score + land a zoom punch-in on the peak) and surface gameplay
reactions the transcript brain alone would miss.
"""
from __future__ import annotations

import functools
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import CONFIG, Paths
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


@functools.lru_cache(maxsize=2)
def _load_job_wav(job_id: str) -> tuple[np.ndarray, int]:
    """The transcribe-stage wav for a job (cached — segment_has_music is called per clip)."""
    for name in (f"{job_id}.wav", f"{job_id}.audio.wav"):
        p = Paths.work / name
        if p.exists():
            return _load_wav_mono16k(p)
    return np.zeros(0, dtype=np.float32), 16000


def _onset_envelope(seg: np.ndarray, win: int = 1024, hop: int = 512) -> np.ndarray:
    """Spectral-flux onset strength per frame — the rhythmic 'pulse' of the audio."""
    if seg.size < win * 4:
        return np.zeros(0, dtype=np.float32)
    n = 1 + (seg.size - win) // hop
    w = np.hanning(win).astype(np.float32)
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(seg[idx] * w, axis=1))
    return np.maximum(0.0, mag[1:] - mag[:-1]).sum(axis=1)


def segment_has_music(job_id: str, start: float, end: float) -> bool:
    """Best-effort: does the SOURCE already have music playing in [start,end]? Music has a
    steady beat, so the onset envelope auto-correlates strongly at a musical tempo (50-200
    BPM); speech and sporadic game audio don't. Used to avoid laying our bed over a part
    where he already has a track on (no double music). Conservative — returns False when
    unsure so we don't wrongly suppress the bed on a silent/ambiguous clip."""
    if not job_id:
        return False
    data, sr = _load_job_wav(job_id)
    if data.size == 0:
        return False
    seg = data[max(0, int(start * sr)): min(data.size, int(end * sr))]
    if seg.size < sr * 3:                                   # too short to judge a tempo
        return False
    if float(np.sqrt(np.mean(seg * seg) + 1e-12)) < 0.01:  # near-silence -> no music
        return False
    flux = _onset_envelope(seg)
    if flux.size < 40:
        return False
    flux = flux - flux.mean()
    ac = np.correlate(flux, flux, mode="full")[flux.size - 1:]
    if ac[0] <= 0:
        return False
    ac = ac / ac[0]
    hop_s = 512 / sr
    lo = max(1, int(round(0.30 / hop_s)))                  # 200 BPM
    hi = min(ac.size - 1, int(round(1.20 / hop_s)))        # 50 BPM
    if hi <= lo:
        return False
    strength = float(np.max(ac[lo:hi]))                    # 0..1; higher = more beat-like
    thresh = float(CONFIG.get("music", {}).get("source_detect_strength", 0.32))
    return strength >= thresh
