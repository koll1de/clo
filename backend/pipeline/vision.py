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
        "clip_start": {"type": "number"},
        "clip_end": {"type": "number"},
    },
    "required": ["clipworthy", "score", "kind", "title", "description", "clip_start", "clip_end"],
}

_SYSTEM = (
    "You are the editor for a viral CS2 YouTube Shorts / TikTok channel in the style of "
    "Renyan. You are shown frames sampled in chronological order from a window of a "
    "Counter-Strike 2 stream; each frame is labelled with its timestamp in seconds. The "
    "streamer's webcam is usually in a corner; the kill feed is top-right; the "
    "scoreboard/timer is top-centre; a radar is bottom-left.\n\n"
    "CRITICAL CONTEXT — you know Counter-Strike 2. The competitive maps (Mirage, Inferno, "
    "Ancient, Dust2, Nuke, Anubis, Vertigo, Overpass, Train) have FIXED, well-known layouts: "
    "bombsites A and B, mid, connectors, and named callout areas (e.g. Ancient has Mid, "
    "Donut, Cave, B ramp, 'red room'/temple; Mirage has Palace, Connector, Window, Apps). "
    "Players constantly WALK, ROTATE and REPOSITION through these rooms and corridors — this "
    "is completely ROUTINE. NEVER describe moving through a normal part of a map as a "
    "'discovery', 'hidden passage', 'secret room', 'mystery' or 'exploration'. That is wrong "
    "and makes a terrible clip. If all you see is the player walking/rotating with no kill, "
    "no clutch and no genuine reaction, it is NOT clipworthy.\n\n"
    "What IS clipworthy: aces, clutches (winning when outnumbered), multi-kills, insane or "
    "lucky shots, big GENUINE reactions on camera (real hype/rage/shock/laughter), or funny "
    "moments. What is NOT: routine walking/rotating/buying, plain aim with no payoff, menus, "
    "sponsor/ad reads, dead time. Be selective and skip the boring/routine windows — but do "
    "NOT reject a genuine kill streak, clutch, or real funny/hype reaction. Score honestly: "
    "give strong moments a high score and weak ones a low one.\n\n"
    "Also choose the TIGHT cut for the highlight using the frame timestamps. The clip must "
    "run 15-45 seconds: start a beat before the action builds and end just after the payoff "
    "or reaction. Do not pad with dead time.\n\n"
    "Return JSON:\n"
    "- clipworthy: true only if genuinely worth posting (apply the rules above).\n"
    "- score: 0..1 confidence it performs as a Short.\n"
    "- kind: best-fitting label.\n"
    "- title: punchy, specific to what actually happens (no hashtags/quotes); use a real map/"
    "site name ONLY if you are sure; never invent intrigue that isn't there.\n"
    "- hook: 2-4 word on-screen opener (UPPERCASE ok), or empty.\n"
    "- description: one sentence on what literally happens.\n"
    "- reason: one sentence on why it will or won't work.\n"
    "- clip_start, clip_end: absolute seconds (from the frame timestamps) bounding the "
    "highlight, 15-45s apart."
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
    clip_start: float       # absolute seconds (the AI-chosen tight cut)
    clip_end: float


def _sample_frames(vod_path: str, start: float, end: float, n: int, max_w: int = 768):
    """Return (base64_jpeg, timestamp_seconds) for n frames evenly spanning [start,end]."""
    import cv2
    cap = cv2.VideoCapture(vod_path)
    if not cap.isOpened():
        return []
    out: list[tuple[str, float]] = []
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
            out.append((base64.b64encode(buf.tobytes()).decode("ascii"), round(t, 1)))
    cap.release()
    return out


def analyze_clip(vod_path: str, start: float, end: float, *, frames: int = 8,
                 min_len: float = 15.0, max_len: float = 45.0) -> VisionVerdict | None:
    sampled = _sample_frames(vod_path, start, end, frames)
    if not sampled:
        return None
    imgs = [b for b, _ in sampled]
    stamps = [t for _, t in sampled]
    labels = ", ".join(f"frame {i+1}={t}s" for i, t in enumerate(stamps))
    user = (
        f"These {len(imgs)} frames span {start:.0f}s to {end:.0f}s of the stream, in order "
        f"({labels}). Judge whether this is a clipworthy CS2 Short and pick the tight 15-45s "
        f"cut using those timestamps."
    )
    try:
        r = llm.chat_vision(_SYSTEM, user, imgs, _SCHEMA)
    except llm.OllamaError as e:
        print(f"[vision] analyze failed @ {start:.0f}s: {e}")
        return None

    # adaptive cut bounds, clamped to the window and to a sane 15-45s length
    cs = float(r.get("clip_start", start))
    ce = float(r.get("clip_end", end))
    if not (start - 1 <= cs < ce <= end + 1):     # model gave junk -> fall back to window
        cs, ce = start, min(end, start + max_len)
    cs = max(start, cs)
    ce = min(end, ce)
    if ce - cs < min_len:
        ce = min(end, cs + min_len)
        if ce - cs < min_len:                      # window itself too short at the tail
            cs = max(start, ce - min_len)
    if ce - cs > max_len:
        ce = cs + max_len

    return VisionVerdict(
        clipworthy=bool(r.get("clipworthy")),
        score=max(0.0, min(1.0, float(r.get("score", 0.0)))),
        kind=str(r.get("kind", "nothing")),
        title=str(r.get("title", "")).strip(),
        hook=str(r.get("hook", "")).strip(),
        description=str(r.get("description", "")).strip(),
        reason=str(r.get("reason", "")).strip(),
        clip_start=round(cs, 2),
        clip_end=round(ce, 2),
    )
