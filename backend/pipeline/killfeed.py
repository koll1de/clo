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
    x0 = int(rect.get("x", 0.60) * w)
    y0 = int(rect.get("y", 0.03) * h)
    x1 = int(min(1.0, rect.get("x", 0.60) + rect.get("w", 0.40)) * w)
    y1 = int(min(1.0, rect.get("y", 0.03) + rect.get("h", 0.22)) * h)
    return slice(y0, y1), slice(x0, x1)


def _activity(roi_bgr: np.ndarray) -> float:
    """How much 'kill-feed text' is on screen: the fraction of vivid-colour or bright-white
    pixels in the ROI. Reliably counting exact kill rows from raw pixels is a much harder CV
    problem (needs weapon-icon templates); activity is a robust proxy for combat — it rises
    when the feed fills up, and we let the vision model judge what actually happened."""
    import cv2
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    mask = ((s > 90) & (v > 120)) | (v > 230)   # vivid colour OR bright white text
    return float(mask.mean())


def _probe_dims(vod_path: str) -> tuple[int, int]:
    """(width, height) of the source via ffprobe."""
    import json as _json
    from ..ffmpeg import ffprobe_bin, run
    proc = run([ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "json", vod_path])
    s = _json.loads(proc.stdout)["streams"][0]
    return int(s["width"]), int(s["height"])


def find_kill_sequences(vod_path: str) -> list[KillSequence]:
    import subprocess
    from ..ffmpeg import ffmpeg_bin

    cfg = CONFIG.get("signals", {}).get("killfeed", {})
    if not cfg.get("enabled", False):
        return []

    sample_fps = float(cfg.get("sample_fps", 4.0))
    rect = cfg.get("roi", {})
    row_min_frac = float(cfg.get("row_min_frac", 0.06))
    multikill_rows = int(cfg.get("multikill_rows", 3))   # rows in window to count as multi-kill
    window_s = float(cfg.get("window_seconds", 6.0))     # how fast the kills must land
    ace_rows = int(cfg.get("ace_rows", 5))

    W, H = _probe_dims(vod_path)
    # kill-feed crop rectangle in source pixels (even dims for the decoder)
    cw = (int(rect.get("w", 0.40) * W) // 2) * 2
    ch = (int(rect.get("h", 0.22) * H) // 2) * 2
    cx = int(rect.get("x", 0.60) * W)
    cy = int(rect.get("y", 0.03) * H)

    # Decode the file ONCE and have ffmpeg emit only the sampled ROI crops as raw BGR.
    # Far faster than decoding every frame of a multi-hour 60fps VOD in Python.
    cmd = [
        ffmpeg_bin(), "-v", "error", "-i", vod_path,
        "-vf", f"fps={sample_fps},crop={cw}:{ch}:{cx}:{cy}",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    frame_bytes = cw * ch * 3

    times: list[float] = []
    activity: list[float] = []
    i = 0
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        roi = np.frombuffer(buf, dtype=np.uint8).reshape(ch, cw, 3)
        activity.append(_activity(roi))
        times.append(round(i / sample_fps, 2))
        i += 1
    proc.stdout.close()
    proc.wait()

    if len(activity) < 8:
        return []

    # Combat fills the kill feed, so activity spikes above the map's own baseline mark
    # candidate windows. We don't trust an exact kill count — the vision model judges
    # what each window actually is. Keep only the strongest, well-separated spikes.
    factor = float(cfg.get("spike_factor", 1.6))
    max_candidates = int(cfg.get("max_candidates", 14))
    a = np.array(activity)
    baseline = float(np.median(a)) or 1e-6
    thresh = baseline * factor

    win = max(1, int(window_s * sample_fps))
    raw: list[KillSequence] = []
    i = 0
    while i < len(a):
        if a[i] < thresh:
            i += 1
            continue
        j = i
        while j < len(a) and a[j] >= thresh:
            j += 1
        peak_idx = i + int(np.argmax(a[i:j]))
        raw.append(KillSequence(
            start=times[i], end=times[min(len(times) - 1, j)],
            peak=times[peak_idx], kills=round(a[peak_idx] / baseline, 1),
            kind="multikill",   # generic; the vision gate relabels (ace/clutch/etc.)
        ))
        i = j
    # strongest spikes first, capped
    raw.sort(key=lambda s: s.kills, reverse=True)
    return raw[:max_candidates]
