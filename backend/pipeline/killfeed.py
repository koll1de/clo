"""Kill-feed signal — detect aces / multi-kill strings from the CS2 kill feed.

The kill feed sits top-right: each kill is a row "killer [weapon] victim", rows
stack and fade after a few seconds. A burst of rows appearing in a short window
is a multi-kill / ace.

IMPORTANT — this is a SCAFFOLD that must be TUNED on the user's own full-res
footage. HUD layout, the kill-feed region, row spacing, and (critically) the
colour CS2 uses to highlight *his own* kills all depend on his resolution/HUD.
The knobs live in config.yaml `signals.killfeed`. Two detection modes:

  1. activity (default, template-free): counts kill-feed rows per frame and flags
     windows where several rows appear fast. Works without setup but flags ALL
     players' kills, so it over-triggers until step 2 is configured.
  2. templates: drop weapon-icon PNGs (esp. deagle) cut from his HUD into the
     templates dir; matched icons confirm kill rows and identify deagle strings.

Best path: he gives a full-res VOD, we screenshot his kill feed, set the ROI +
his-kill highlight colour, and tune the thresholds against real aces.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import CONFIG


@dataclass
class KillSequence:
    start: float      # seconds (source)
    end: float
    peak: float       # when the kills land
    kills: int        # rows added in the window
    kind: str         # ace | multikill_deagle | clutch (best guess)


def _roi_slice(h: int, w: int, rect: dict) -> tuple[slice, slice]:
    """Fractional rect {x,y,w,h} (0..1) -> pixel slices. Default = top-right."""
    x0 = int(rect.get("x", 0.55) * w)
    y0 = int(rect.get("y", 0.02) * h)
    x1 = int(min(1.0, rect.get("x", 0.55) + rect.get("w", 0.44)) * w)
    y1 = int(min(1.0, rect.get("y", 0.02) + rect.get("h", 0.28)) * h)
    return slice(y0, y1), slice(x0, x1)


def _count_rows(roi_gray: np.ndarray, row_min_frac: float) -> int:
    """Estimate kill-feed rows: bright text projects onto rows as horizontal bands;
    count the bands separated by gaps. Crude but template-free."""
    # bright (text/icons) vs the darkened feed background
    mask = roi_gray > 160
    row_activity = mask.mean(axis=1)            # fraction of bright pixels per row
    active = row_activity > row_min_frac
    rows, prev = 0, False
    for a in active:
        if a and not prev:
            rows += 1
        prev = a
    return rows


def find_kill_sequences(vod_path: str) -> list[KillSequence]:
    cfg = CONFIG.get("signals", {}).get("killfeed", {})
    if not cfg.get("enabled", False):
        return []
    try:
        import cv2
    except ImportError:
        print("[killfeed] opencv not installed; skipping. `pip install opencv-python-headless`.")
        return []

    sample_fps = float(cfg.get("sample_fps", 4.0))
    rect = cfg.get("roi", {})
    row_min_frac = float(cfg.get("row_min_frac", 0.06))
    multikill_rows = int(cfg.get("multikill_rows", 3))   # rows in window to count as multi-kill
    window_s = float(cfg.get("window_seconds", 6.0))     # how fast the kills must land
    ace_rows = int(cfg.get("ace_rows", 5))

    cap = cv2.VideoCapture(vod_path)
    if not cap.isOpened():
        print(f"[killfeed] could not open {vod_path}")
        return []
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(round(src_fps / sample_fps)))

    times: list[float] = []
    counts: list[int] = []
    sl_y = sl_x = None
    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if ok and frame is not None:
                if sl_y is None:
                    h, w = frame.shape[:2]
                    sl_y, sl_x = _roi_slice(h, w, rect)
                roi = frame[sl_y, sl_x]
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                counts.append(_count_rows(gray, row_min_frac))
                times.append(idx / src_fps)
        idx += 1
        if total and idx > total:
            break
    cap.release()

    if len(counts) < 3:
        return []

    # A multi-kill = a run where the row count climbs to >= threshold within window_s.
    win = max(1, int(window_s * sample_fps))
    seqs: list[KillSequence] = []
    i = 0
    while i < len(counts):
        hi = max(counts[i : i + win]) if i < len(counts) else 0
        if hi >= multikill_rows:
            j = min(len(counts), i + win)
            peak_idx = i + int(np.argmax(counts[i:j]))
            kills = int(hi)
            kind = "ace" if kills >= ace_rows else "multikill_deagle"
            seqs.append(KillSequence(
                start=round(times[i], 2), end=round(times[j - 1], 2),
                peak=round(times[peak_idx], 2), kills=kills, kind=kind,
            ))
            i = j
        else:
            i += 1
    return seqs
