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
from .. import store
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
    "4. big_reaction — a strong emotional spike (rage, shock, GENUINE hype) that reads well "
    "even without seeing the play. Beware sarcasm: a positive-sounding line ('nice', "
    "'impressive') right after a loss or a teammate's mistake is disappointment, not hype — "
    "don't flag that as a big_reaction.\n"
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


def _window_text(segments: list[dict], start: float, end: float, pad: float = 2.0) -> str:
    """The dialogue spoken within [start-pad, end+pad] as labelled lines — fed to the
    vision gate so it can judge verbal comedy/banter, not just what's on screen."""
    return "\n".join(
        f"[{s['start']:.0f}] {s['text'].strip()}"
        for s in segments
        if s["end"] > start - pad and s["start"] < end + pad and (s.get("text") or "").strip()
    )


def apply_audio_signal(
    job_id: str, clips: list[Clip], reactions: list, transcript_path: str
) -> list[Clip]:
    """Corroborate transcript clips with loudness spikes and surface strong
    reactions the transcript brain missed (the pure-gameplay-hype gap)."""
    scfg = CONFIG.get("signals", {}).get("audio", {})
    if not scfg.get("enabled", True) or not reactions:
        return clips
    min_level = float(scfg.get("min_reaction_level", 3.0))
    max_new = int(scfg.get("max_new_candidates", 4))
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
            c.signals.append("audio")  # tag only; the AI sets the score, not a boost
            c.audio_peak = round(min(max(r.peak, c.start), c.end), 2)
            c.audio_level = round(float(r.level), 2)  # how loud the vocal reaction was (x baseline)

    # 2) new candidates from strong, uncovered reactions
    new_count = 0
    for r in reactions:
        if new_count >= max_new or r.level < min_level:
            continue
        if overlaps_clip(r) is not None:
            continue
        # Window biased just before the peak (the action precedes the loud reaction),
        # kept tight enough that sampled frames land on the action. Vision picks the
        # final 15-45s cut inside it.
        start = max(0.0, r.peak - 22.0)
        end = r.peak + 8.0                          # ~30s window, peak ~3/4 through
        title = _nearest_text(segments, r.peak)[:80]
        conf = min(1.0, 0.5 + (r.level - min_level) * 0.1)
        clip = Clip(
            id=uuid.uuid4().hex[:12], job_id=job_id,
            start=round(start, 2), end=round(end, 2),
            kind="big_reaction",
            score=round(conf, 4),
            title=title, reason=f"Loud reaction ({r.level}x baseline) detected in audio.",
            audio_peak=round(r.peak, 2), audio_level=round(float(r.level), 2), signals=["audio"],
            status=ClipStatus.pending,
        )
        clips.append(clip)
        new_count += 1

    return _dedupe(clips)


def apply_chat_signal(
    job_id: str, clips: list[Clip], bursts: list, transcript_path: str
) -> list[Clip]:
    """Corroborate clips with Twitch chat bursts and surface big chat reactions
    the transcript brain missed. Mirrors apply_audio_signal."""
    scfg = CONFIG.get("signals", {}).get("chat", {})
    if not scfg.get("enabled", True) or not bursts:
        return clips
    min_level = float(scfg.get("min_burst_level", 3.0))
    max_new = int(scfg.get("max_new_candidates", 4))
    clip_cfg = CONFIG["clips"]
    segments = _load_transcript(transcript_path).get("segments", [])

    def overlaps_clip(b) -> Clip | None:
        for c in clips:
            if min(c.end, b.end) - max(c.start, b.start) > 0:
                return c
        return None

    for b in bursts:
        c = overlaps_clip(b)
        if c is not None and "chat" not in c.signals:
            c.signals.append("chat")  # tag only; the AI sets the score

    new_count = 0
    for b in bursts:
        if new_count >= max_new or b.level < min_level or overlaps_clip(b) is not None:
            continue
        half = clip_cfg["min_seconds"] / 2
        # chat reacts a beat late, so bias the window to start before the burst
        start = max(0.0, b.peak - half - 2.0)
        end = start + clip_cfg["min_seconds"]
        kind = "funny_interaction" if b.funny else "big_reaction"
        conf = min(1.0, 0.5 + (b.level - min_level) * 0.05)
        clips.append(Clip(
            id=uuid.uuid4().hex[:12], job_id=job_id,
            start=round(start, 2), end=round(end, 2), kind=kind,
            score=round(conf, 4),
            title=_nearest_text(segments, b.peak)[:80],
            reason=f"Chat {'laughter' if b.funny else 'hype'} burst ({b.level}x baseline).",
            signals=["chat"], status=ClipStatus.pending,
        ))
        new_count += 1

    return _dedupe(clips)


def vision_verify(job_id: str, vod_path: str, clips: list[Clip],
                  transcript_path: str = "") -> list[Clip]:
    """The gate: the vision model WATCHES each candidate (and reads what was SAID during it)
    and we keep only the ones it judges genuinely clipworthy, taking its title/kind/hook/score
    as authoritative. This is what removes the context-free 'clip of nothing' candidates."""
    from . import vision
    vcfg = CONFIG.get("signals", {}).get("vision", {})
    if not vcfg.get("enabled", True) or not clips:
        return clips
    min_score = float(vcfg.get("min_score", 0.6))
    frames = int(vcfg.get("frames_per_clip", 8))
    max_verify = int(vcfg.get("max_verify", 24))
    min_len = float(CONFIG["clips"]["min_seconds"])
    max_len = float(CONFIG["clips"]["max_seconds"])
    segments = _load_transcript(transcript_path).get("segments", []) if transcript_path else []

    # only spend vision compute on the most promising candidates
    cands = sorted(clips, key=lambda c: c.score, reverse=True)[:max_verify]
    kept: list[Clip] = []
    for c in cands:
        if store.is_cancelled(job_id):     # user killed the job — stop the (slow) vision pass
            break
        dialogue = _window_text(segments, c.start, c.end) if segments else ""
        v = vision.analyze_clip(vod_path, c.start, c.end, frames=frames,
                                min_len=min_len, max_len=max_len, transcript=dialogue,
                                audio_level=getattr(c, "audio_level", 0.0))
        if v is None:
            continue  # couldn't see it -> don't risk a bad clip
        if not v.clipworthy or v.score < min_score:
            print(f"[vision] dropped {c.start:.0f}-{c.end:.0f}s ({v.score:.2f} {v.kind}): {v.reason}")
            continue
        # adopt the AI-chosen tight cut (adaptive 15-45s)
        c.start, c.end = v.clip_start, v.clip_end
        c.kind = v.kind
        c.title = v.title or c.title
        c.hook = v.hook
        c.reason = v.reason or c.reason
        c.score = round(v.score, 4)
        c.sfx = v.sfx
        c.sfx_time = v.sfx_time
        c.music = v.music
        if "vision" not in c.signals:
            c.signals.append("vision")
        kept.append(c)
    print(f"[vision] kept {len(kept)}/{len(cands)} candidates")
    return _dedupe(kept)


def apply_killfeed_signal(
    job_id: str, clips: list[Clip], sequences: list, transcript_path: str
) -> list[Clip]:
    """Turn detected kill sequences (aces / multi-kill strings) into candidates and
    corroborate any spoken hype that overlaps them."""
    if not sequences:
        return clips
    segments = _load_transcript(transcript_path).get("segments", [])

    for ks in sequences:
        # corroborate an overlapping spoken moment (his hype during the play)
        for c in clips:
            if min(c.end, ks.end) - max(c.start, ks.start) > 0 and "killfeed" not in c.signals:
                c.signals.append("killfeed")  # tag only; the AI sets the score
        # peak-centred window so the vision pass can pick the tight 15-45s cut
        start = max(0.0, ks.peak - 22.0)
        end = ks.peak + 8.0
        clips.append(Clip(
            id=uuid.uuid4().hex[:12], job_id=job_id,
            start=round(start, 2), end=round(end, 2), kind=ks.kind,
            score=0.6,  # neutral triage prior; the vision gate sets the real score
            title=_nearest_text(segments, ks.peak)[:80] or "Kill feed action",
            reason=f"Kill-feed activity spike ({ks.kills}x baseline).",
            audio_peak=round(ks.peak, 2), signals=["killfeed"],
            status=ClipStatus.pending,
        ))
    return _dedupe(clips)


def find_transcript_moments(job_id: str, transcript_path: str) -> list[Clip]:
    cfg = CONFIG["llm"]
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
            # The AI owns scoring now: the brain's own confidence is the pre-vision triage
            # score; the vision gate sets the final score for clips it keeps.
            score = conf
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
