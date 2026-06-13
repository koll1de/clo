"""Vision signal — the AI actually WATCHES candidate moments.

Cheap signals (audio spikes, transcript hype, kill-feed) only say *where to look*.
This module samples frames across a candidate window and asks a local vision model
(qwen2.5vl on the 3090) what is actually happening — so we keep only genuinely
entertaining, self-contained moments and give each a real title/hook. This is what
stops the "random clip of nothing" problem.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

from .. import llm
from ..config import CONFIG

KINDS = [
    "ace", "clutch", "multikill", "insane_play", "funny_interaction",
    "big_reaction", "rage", "fail_whiff", "tips_to_chat", "nothing",
]

_SCHEMA = {
    "type": "object",
    "properties": {
        "clipworthy": {"type": "boolean"},
        "score": {"type": "number"},
        "kind": {"type": "string", "enum": KINDS},
        "title": {"type": "string"},
        "hook": {"type": "string"},
        "description": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["clipworthy", "score", "kind", "title", "description"],
}

_SYSTEM = (
    "You are the editor for a viral CS2 YouTube Shorts / TikTok channel in the style of "
    "Renyan. You are shown several frames sampled in chronological order from one "
    "candidate moment of a Counter-Strike 2 stream (the streamer's webcam is usually in "
    "a corner; the kill feed is top-right; the scoreboard/timer is top-centre).\n\n"
    "Decide if this moment would make an ENTERTAINING, self-contained vertical Short. "
    "Great moments: aces / clutches / multi-kills / insane or lucky plays, big genuine "
    "reactions (hype, rage, shock), funny moments, or him reacting on camera. Boring "
    "moments: routine walking/buying, nothing happening, plain aim with no payoff, menus, "
    "dead time. BE STRICT — most candidates are NOT clipworthy. Quality over quantity.\n\n"
    "Return JSON:\n"
    "- clipworthy: true only if it's genuinely worth posting.\n"
    "- score: 0..1 confidence it will perform as a Short.\n"
    "- kind: the best-fitting label.\n"
    "- title: a punchy, curiosity-driving title (no hashtags, no quotes).\n"
    "- hook: 2-4 word on-screen opener (UPPERCASE ok), or empty.\n"
    "- description: one sentence on what literally happens in the frames.\n"
    "- reason: one sentence on why it will or won't work as a Short."
)


@dataclass
class VisionVerdict:
    clipworthy: bool
    score: float
    kind: str
    title: str
    hook: str
    description: str
    reason: str


def _sample_frames(vod_path: str, start: float, end: float, n: int, max_w: int = 768):
    import cv2
    cap = cv2.VideoCapture(vod_path)
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames_b64: list[str] = []
    dur = max(0.1, end - start)
    for k in range(n):
        t = start + dur * (k + 0.5) / n
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        h, w = frame.shape[:2]
        if w > max_w:
            frame = cv2.resize(frame, (max_w, int(h * max_w / w)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            frames_b64.append(base64.b64encode(buf.tobytes()).decode("ascii"))
    cap.release()
    return frames_b64


def analyze_clip(vod_path: str, start: float, end: float, *, frames: int = 6) -> VisionVerdict | None:
    imgs = _sample_frames(vod_path, start, end, frames)
    if not imgs:
        return None
    user = (
        f"These {len(imgs)} frames span {end - start:.0f} seconds of one candidate moment, "
        f"in chronological order. Judge it as a CS2 Short."
    )
    try:
        r = llm.chat_vision(_SYSTEM, user, imgs, _SCHEMA)
    except llm.OllamaError as e:
        print(f"[vision] analyze failed @ {start:.0f}s: {e}")
        return None
    return VisionVerdict(
        clipworthy=bool(r.get("clipworthy")),
        score=max(0.0, min(1.0, float(r.get("score", 0.0)))),
        kind=str(r.get("kind", "nothing")),
        title=str(r.get("title", "")).strip(),
        hook=str(r.get("hook", "")).strip(),
        description=str(r.get("description", "")).strip(),
        reason=str(r.get("reason", "")).strip(),
    )
