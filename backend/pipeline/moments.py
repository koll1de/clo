"""Stage 3a — find clip-worthy moments by reading the transcript with the local LLM.

This is one of several moment signals (audio laughter, chat spikes, and kill-feed
come from sibling modules). It focuses on what was *said*: funny interactions with
teammates, jokes, talking to chat / giving tips, and real-life interruptions
(screaming -> parents walk in). Kill-based moments (aces, clutches, deagle strings)
are detected from the kill-feed, not here, though spoken hype reactions are caught.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from ..config import CONFIG
from .. import llm
from ..models import Clip, ClipStatus

# Moment kinds the transcript can reveal (kill-based kinds come from the kill-feed).
TRANSCRIPT_KINDS = [
    "funny_interaction",
    "irl_interruption",
    "tips_to_chat",
    "big_reaction",
    "story_banter",
]

_SCHEMA = {
    "type": "object",
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "kind": {"type": "string", "enum": TRANSCRIPT_KINDS},
                    "title": {"type": "string"},
                    "reason": {"type": "string"},
                    "quote": {"type": "string"},
                    "question_username": {"type": "string"},
                    "question_highlights": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
                "required": ["start", "end", "kind", "title", "reason", "confidence"],
            },
        }
    },
    "required": ["moments"],
}

_SYSTEM = (
    "You are an expert short-form editor for a Russian-speaking Counter-Strike 2 "
    "Twitch streamer (Premier mode), in the style of creators like Renyan. You find "
    "the moments in a stream that would make great vertical YouTube Shorts / TikTok "
    "clips for a Russian audience. The streamer has no facecam.\n\n"
    "You are given a timestamped transcript chunk (Russian, sometimes English when he "
    "talks to teammates). Each line is '[<seconds>] text'. Identify self-contained "
    "clip-worthy moments. Prioritise, in order:\n"
    "1. funny_interaction — jokes, funny banter with Premier teammates, funny things "
    "from chat or friends, or him laughing hard.\n"
    "2. irl_interruption — he screams/reacts loudly and a parent or family member comes "
    "in / is talked to. This is viral gold; flag it whenever you see him suddenly "
    "talking to someone in the room.\n"
    "3. tips_to_chat — he addresses chat directly, gives a tip, tells a short story, or "
    "answers a question (this maps to an on-screen question card).\n"
    "4. big_reaction — a strong emotional spike (rage, shock, hype) that reads well even "
    "without seeing the play.\n"
    "5. story_banter — a short funny/interesting self-contained tangent.\n\n"
    "Rules:\n"
    "- start/end MUST be in seconds, taken from the line timestamps; start at the line "
    "where the setup begins, end where the payoff finishes.\n"
    "- Each moment should be roughly 8-45 seconds of content. Skip dead air and routine "
    "gameplay chatter that isn't entertaining.\n"
    "- title: a punchy Russian title for the Short (the audience is Russian).\n"
    "- reason: one short English sentence explaining why it's clip-worthy (for the editor).\n"
    "- quote: the funniest/key line, verbatim from the transcript. For a tips_to_chat "
    "moment this MUST be the question or tip he is answering, phrased as a short "
    "on-screen line (it becomes a question card).\n"
    "- question_username: for tips_to_chat, the chat viewer's name he is replying to if "
    "he says it (else \"\"). Empty for other kinds.\n"
    "- question_highlights: for tips_to_chat, 1-3 key words from `quote` to emphasise in "
    "gold on the card (else []). Empty for other kinds.\n"
    "- confidence: 0..1, how strong this clip is. Be selective; quality over quantity.\n"
    "- If nothing in this chunk is clip-worthy, return an empty list."
)


def _load_transcript(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _chunks(segments: list[dict], chunk_s: float, overlap_s: float):
    """Yield (lines_text, win_start, win_end) windows over the transcript."""
    if not segments:
        return
    total_end = segments[-1]["end"]
    win_start = 0.0
    while win_start < total_end:
        win_end = win_start + chunk_s
        lines = [
            f"[{s['start']:.0f}] {s['text']}"
            for s in segments
            if s["end"] > win_start and s["start"] < win_end and s["text"]
        ]
        if lines:
            yield "\n".join(lines), win_start, win_end
        win_start = win_end - overlap_s


def _overlaps(a: Clip, b: Clip) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    shorter = min(a.end - a.start, b.end - b.start) or 1.0
    return inter / shorter


def _dedupe(clips: list[Clip]) -> list[Clip]:
    """Drop near-duplicate moments from overlapping windows; keep the strongest."""
    kept: list[Clip] = []
    for c in sorted(clips, key=lambda x: x.score, reverse=True):
        if all(_overlaps(c, k) < 0.5 for k in kept):
            kept.append(c)
    return sorted(kept, key=lambda x: x.start)


def _nearest_text(segments: list[dict], t: float) -> str:
    """The transcript line closest to time t — used to title an audio-only candidate."""
    best, best_d = "", 1e9
    for s in segments:
        mid = (s["start"] + s["end"]) / 2
        d = abs(mid - t)
        if d < best_d and (s.get("text") or "").strip():
            best, best_d = s["text"].strip(), d
    return best


def apply_audio_signal(
    job_id: str, clips: list[Clip], reactions: list, transcript_path: str
) -> list[Clip]:
    """Corroborate transcript clips with loudness spikes and surface strong
    reactions the transcript brain missed (the pure-gameplay-hype gap)."""
    scfg = CONFIG.get("signals", {}).get("audio", {})
    if not scfg.get("enabled", True) or not reactions:
        return clips
    boost = float(scfg.get("corroborate_boost", 1.2))
    min_level = float(scfg.get("min_reaction_level", 3.0))
    max_new = int(scfg.get("max_new_candidates", 4))
    weights = CONFIG["priority"]
    clip_cfg = CONFIG["clips"]
    data = _load_transcript(transcript_path)
    segments = data.get("segments", [])

    def overlaps_clip(r) -> Clip | None:
        for c in clips:
            if min(c.end, r.end) - max(c.start, r.start) > 0:
                return c
        return None

    # 1) corroborate existing clips (reactions are sorted strongest-first, so the
    #    first overlap is the loudest beat — that's the one we punch in on)
    for r in reactions:
        c = overlaps_clip(r)
        if c is not None and "audio" not in c.signals:
            c.signals.append("audio")
            c.score = round(min(c.score * boost, 1.5), 4)
            c.audio_peak = round(min(max(r.peak, c.start), c.end), 2)

    # 2) new candidates from strong, uncovered reactions
    new_count = 0
    for r in reactions:
        if new_count >= max_new or r.level < min_level:
            continue
        if overlaps_clip(r) is not None:
            continue
        # build a clip window around the peak within the configured bounds
        half = clip_cfg["min_seconds"] / 2
        start = max(0.0, r.peak - half - 1.0)   # a beat of lead-in before the peak
        end = start + clip_cfg["min_seconds"]
        title = _nearest_text(segments, r.peak)[:80]
        conf = min(1.0, 0.5 + (r.level - min_level) * 0.1)
        clip = Clip(
            id=uuid.uuid4().hex[:12], job_id=job_id,
            start=round(start, 2), end=round(end, 2),
            kind="big_reaction",
            score=round(conf * float(weights.get("big_reaction", 0.8)), 4),
            title=title, reason=f"Loud reaction ({r.level}x baseline) detected in audio.",
            audio_peak=round(r.peak, 2), signals=["audio"],
            status=ClipStatus.pending,
        )
        clips.append(clip)
        new_count += 1

    return _dedupe(clips)


def find_transcript_moments(job_id: str, transcript_path: str) -> list[Clip]:
    cfg = CONFIG["llm"]
    weights = CONFIG["priority"]
    clip_cfg = CONFIG["clips"]
    data = _load_transcript(transcript_path)
    segments = data.get("segments", [])

    raw: list[Clip] = []
    for lines, win_start, win_end in _chunks(
        segments, cfg["chunk_minutes"] * 60, cfg["overlap_seconds"]
    ):
        user = (
            f"Transcript chunk covering {win_start:.0f}s to {win_end:.0f}s of the stream:\n\n"
            f"{lines}\n\nFind the clip-worthy moments."
        )
        try:
            result = llm.chat_json(_SYSTEM, user, _SCHEMA)
        except llm.OllamaError as e:
            # One bad chunk shouldn't sink the whole VOD; skip it and keep going.
            print(f"[moments] chunk {win_start:.0f}-{win_end:.0f}s failed: {e}")
            continue
        for m in result.get("moments", []):
            start = max(0.0, float(m["start"]))
            end = float(m["end"])
            if end <= start:
                continue
            # enforce clip length bounds
            dur = end - start
            if dur < clip_cfg["min_seconds"]:
                end = start + clip_cfg["min_seconds"]
            elif dur > clip_cfg["max_seconds"]:
                end = start + clip_cfg["max_seconds"]
            kind = m["kind"]
            conf = max(0.0, min(1.0, float(m.get("confidence", 0.5))))
            score = conf * float(weights.get(kind, 0.5))
            raw.append(Clip(
                id=uuid.uuid4().hex[:12],
                job_id=job_id,
                start=round(start, 2),
                end=round(end, 2),
                kind=kind,
                score=round(score, 4),
                title=m.get("title", "").strip(),
                reason=m.get("reason", "").strip(),
                quote=m.get("quote", "").strip(),
                question_username=m.get("question_username", "").strip(),
                question_highlights=[h.strip() for h in m.get("question_highlights", []) if h.strip()],
                status=ClipStatus.pending,
            ))

    return _dedupe(raw)
