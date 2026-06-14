"""Kill-feed signal — detect aces / multi-kill strings from the CS2 kill feed.

The kill feed sits top-right: each kill is a right-aligned row "killer [weapon]
victim"; rows stack and fade after a few seconds. A burst of rows in a short window
is a multi-kill / ace. CS2 outlines the LOCAL player's OWN kills in RED — we detect that
red outline as a reliable "the streamer himself is getting these kills" cue, to float
HIS multikills/aces above kills his teammates got.

TUNED (2026-06-14) against a real 1080p Murzofix FACEIT VOD (in-game name `sss-rank-`):
  - ROI is the top-right feed box only (excludes the top-centre scoreboard).
  - Activity = density of *coloured text edges* (team-coloured names that are also
    local edges). This is robust to bright sky / pale walls, which fooled the old
    brightness metric (a bright Nuke wall scored higher than a real 3-kill burst).
  - Detection stays an ACTIVITY PROXY: it nominates candidate windows; the vision
    gate (Claude) judges what each window actually is (ace / clutch / nothing).
NOTE: the calibration VOD was an edited compilation, so confirm the ROI on a raw
single-HUD stream VOD if his layout differs. All knobs live in config `signals.killfeed`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import CONFIG

# ROI defaults (fractions of the frame): the top-right kill-feed box in his HUD.
ROI_DEFAULT = {"x": 0.70, "y": 0.06, "w": 0.30, "h": 0.26}


@dataclass
class KillSequence:
    start: float      # seconds (source)
    end: float
    peak: float       # when the kills land
    kills: float      # activity at the peak relative to baseline (ranking score)
    kind: str         # ace | multikill_deagle | clutch (best guess; vision relabels)
    involves_him: bool = False   # the local-player highlight (red border) showed in the window


def _roi_slice(h: int, w: int, rect: dict) -> tuple[slice, slice]:
    """Fractional rect {x,y,w,h} (0..1) -> pixel slices. Default = top-right feed box."""
    x = rect.get("x", ROI_DEFAULT["x"]); y = rect.get("y", ROI_DEFAULT["y"])
    rw = rect.get("w", ROI_DEFAULT["w"]); rh = rect.get("h", ROI_DEFAULT["h"])
    x0, y0 = int(x * w), int(y * h)
    x1, y1 = int(min(1.0, x + rw) * w), int(min(1.0, y + rh) * h)
    return slice(y0, y1), slice(x0, x1)


def _activity(roi_bgr: np.ndarray) -> float:
    """How much kill-feed TEXT is on screen: the fraction of pixels that are a coloured
    edge — i.e. a saturated (team-coloured name) pixel that also sits on a local edge.
    Flat bright sky/walls have ~no edges; flat grey scenery has ~no saturation; only the
    crisp coloured kill-feed text lights both up. Far more robust than raw brightness,
    which spiked on Nuke's bright surfaces."""
    import cv2
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.dilate((cv2.Canny(gray, 80, 160) > 0).astype("uint8"),
                       np.ones((2, 2), "uint8")) > 0
    return float((edges & (sat > 60)).mean())


def _his_involvement(roi_bgr: np.ndarray) -> float:
    """Fraction of the ROI covered by CS2's saturated-red outline — the mark CS2 draws on
    the local player's OWN kill-feed rows. Near-zero on teammates'/enemies' rows; spikes
    when the streamer himself is getting the kills, so it flags windows to credit to HIM."""
    import cv2
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    red = ((h < 10) | (h > 170)) & (s > 120) & (v > 90)
    return float(red.mean())


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
    rect = {**ROI_DEFAULT, **(cfg.get("roi") or {})}
    window_s = float(cfg.get("window_seconds", 4.0))   # min gap between separate spikes
    spike_factor = float(cfg.get("spike_factor", 4.0))  # × baseline to count as a spike
    # Absolute floor on the coloured-edge density below which there is no real feed text.
    # The new metric runs ~0.003 idle vs ~0.04-0.10 on a kill burst, so the median-relative
    # threshold alone is too twitchy near zero — the floor anchors it.
    min_activity = float(cfg.get("min_activity", 0.025))
    max_candidates = int(cfg.get("max_candidates", 14))
    hi_cfg = cfg.get("his_highlight", {})
    hi_enabled = bool(hi_cfg.get("enabled", True))
    hi_boost = float(hi_cfg.get("boost", 1.6))          # rank HIS windows above generic combat
    hi_floor = float(hi_cfg.get("involve_floor", 0.003))  # red fraction = he's in the feed

    W, H = _probe_dims(vod_path)
    # kill-feed crop rectangle in source pixels (even dims for the decoder)
    cw = (int(rect["w"] * W) // 2) * 2
    ch = (int(rect["h"] * H) // 2) * 2
    cx = int(rect["x"] * W)
    cy = int(rect["y"] * H)

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
    involve: list[float] = []
    i = 0
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        roi = np.frombuffer(buf, dtype=np.uint8).reshape(ch, cw, 3)
        activity.append(_activity(roi))
        involve.append(_his_involvement(roi) if hi_enabled else 0.0)
        times.append(round(i / sample_fps, 2))
        i += 1
    proc.stdout.close()
    proc.wait()

    if len(activity) < 8:
        return []

    # Combat fills the kill feed, so coloured-text activity spikes above the map's baseline
    # mark candidate windows. We don't trust an exact kill count — the vision model judges
    # what each window actually is. Keep only the strongest, well-separated spikes.
    a = np.array(activity)
    inv = np.array(involve)
    baseline = float(np.median(a)) or 1e-6
    thresh = max(min_activity, baseline * spike_factor)

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
        involves_him = bool(hi_enabled and inv[i:j].max() >= hi_floor)
        score = round(a[peak_idx] / baseline, 1)
        if involves_him:
            score = round(score * hi_boost, 1)   # float his own moments up the capped list
        raw.append(KillSequence(
            start=times[i], end=times[min(len(times) - 1, j)],
            peak=times[peak_idx], kills=score,
            kind="multikill",   # generic; the vision gate relabels (ace/clutch/etc.)
            involves_him=involves_him,
        ))
        i = j
    # strongest spikes first (his-involved windows already boosted), capped
    raw.sort(key=lambda s: s.kills, reverse=True)
    return raw[:max_candidates]
