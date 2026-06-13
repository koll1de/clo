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
from ..config import CONFIG, ROOT


def _sfx_names() -> list[str]:
    """Names (file stems) of the sound effects the AI may choose from, or [] if disabled."""
    scfg = CONFIG.get("sfx", {})
    if not scfg.get("enabled", True):
        return []
    d = ROOT / scfg.get("dir", "assets/sfx")
    return sorted(p.stem for p in d.glob("*.mp3")) if d.exists() else []

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

# The Renyan grounding below (moment mix, tone, title style) comes from researching his
# channel — those three are well-sourced. His opening-hook, exact pacing, and on-screen
# visual treatment could NOT be verified (YouTube/TikTok block scraping), so we don't make
# claims about them here; the reframe/edit logic stays in config.yaml + render.py.
_SYSTEM = (
    "You are the editor for a CS2 YouTube Shorts / TikTok channel in the style of Renyan — "
    "a skilled Norwegian CS2 player whose clips are COMEDY- and PERSONALITY-first, not a "
    "serious highlight reel. You are shown frames sampled in chronological order from a "
    "window of a Counter-Strike 2 stream; each frame is labelled with its timestamp in "
    "seconds. The streamer's webcam is usually in a corner; the kill feed is top-right; the "
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
    "CS2 GAMEPLAY YOU SHOULD RECOGNISE (judge plays by real CS2 skill standards):\n"
    "- Peeks & aim: wide-swing (wide peek), jiggle/shoulder peek (baiting info), holding an "
    "off-angle, jump-peeks, pre-fires, spray control and spray-transfers (sweeping one spray "
    "across several enemies), one-taps, AWP flicks/quickscopes/no-scopes, jumping/airborne "
    "shots, wallbangs (pre-firing through a wall), and collaterals (two kills with one bullet).\n"
    "- Utility & strats: executes (a coordinated site take with smokes/flashes/molotovs), "
    "defaults, rushes, retakes, after-plant holds, lurks, fakes, trade kills, stacking a site, "
    "the buy economy (eco / force-buy / full-buy / save), and 'smoke-criminal' kills (killing "
    "through a smoke). A pop-flash or one-way smoke setting up a kill is skilful.\n"
    "- Genuinely clip-worthy plays: an ACE (all 5 enemies killed), a CLUTCH (winning a 1vX when "
    "outnumbered — especially 1v3/1v4/1v5), a ninja defuse, an insane flick or lucky shot, or a "
    "clean spray-down of several enemies.\n"
    "MULTI-KILL RULE (be strict): a kill streak only counts as a clip-worthy 'multikill' if it "
    "is at least 4 kills (a 4K or an ACE) — EXCEPT with the Desert Eagle (Deagle), where 3+ "
    "kills is enough (a 3-Deagle string is impressive). A 2-3 kill streak with rifles/SMGs/AWP "
    "is routine and NOT clip-worthy on its own; only clip it if a genuine reaction or funny "
    "moment carries it. Read the kill feed (top-right): it shows the weapon icon and how many "
    "kills happened in the streak.\n\n"
    "What makes a great clip here (Renyan-style, comedy/personality FIRST): genuine funny or "
    "relatable moments; meltdowns and rage at toxic or uncooperative teammates and 'the state "
    "of the game'; calling out or outplaying obvious cheaters/hackers; self-handicap or "
    "challenge bits (weird strats, unusual weapons, 1vN); AND genuinely impressive plays — "
    "aces, clutches (winning when outnumbered), multi-kills, insane or lucky shots — but "
    "framed for ENTERTAINMENT, not as a dry flex. A real reaction on camera (hype, rage, "
    "shock, laughter) strongly boosts a clip. What is NOT clipworthy: routine "
    "walking/rotating/buying, plain aim with no payoff or reaction, menus, sponsor/ad reads, "
    "dead time. Keep the sensibility dry, absurdist and self-deprecating — never a hype "
    "esports announcer. Be selective and skip the boring/routine windows — but do NOT reject "
    "a genuine kill streak, clutch, or real funny/rage/hype reaction. Score honestly: give "
    "strong moments a high score and weak ones a low one.\n\n"
    "You may also be given the streamer's DIALOGUE (a timestamped transcript) for the "
    "window. This channel is comedy/personality-first and much of the entertainment is "
    "VERBAL — funny banter, a heated rage/rant, a good back-and-forth with chat, or a "
    "strong short story. Weigh what is SAID as heavily as what is SHOWN: a window is "
    "clipworthy for the talk alone even when the gameplay frames look routine. Do NOT "
    "dismiss a window as 'just walking/rotating' if the dialogue is what carries it — judge "
    "the whole moment, frames and words together.\n\n"
    "READING EMOTION vs OUTCOME (avoid false positives): use the SCOREBOARD / round result "
    "and the streamer's tone TOGETHER. CS2 players are often sarcastic, deadpan or bitter. A "
    "line like 'that was impressive as hell', 'nice one', or 'great job team' said after a "
    "LOST round or a teammate's mistake is SARCASM or disappointment — it is NOT genuine hype "
    "and must NOT be scored as a 'big_reaction'. A real big_reaction needs genuine, POSITIVE "
    "excitement (or genuinely heated rage) that MATCHES what actually happened: hype only if "
    "the round/play was won, rage/sarcasm if it was lost. If the round was lost or the play "
    "failed, do not read a calm, sad or sarcastic remark as excitement. Match the emotion to "
    "the outcome before you pick the kind and score.\n\n"
    "HOW BIG IS THE REACTION (this drives the score): the SIZE of the reaction matters as much "
    "as its kind. A genuinely loud, high-energy outburst — his voice jumps up in pitch and "
    "volume, he yells, he loses it laughing — is a STRONG clip; score it high. You may be told "
    "the audio got noticeably louder here (a vocal-energy spike); treat that as evidence of a "
    "bigger reaction and weight it UP. Conversely, mild, low-energy, GENERIC teammate-"
    "complaining ('my team is so bad', 'these guys are trash') with no real intensity, no "
    "escalation and no humour is WEAK — even with swearing — and usually NOT worth a clip. "
    "Only clip salt when it's a genuine, energetic meltdown or it's actually funny.\n\n"
    "Also choose the cut using the frame AND transcript timestamps. The clip must be SELF-"
    "CONTAINED — it has to make sense to a viewer with NO prior context. Start at the "
    "beginning of the exchange that SETS UP the moment (the first line/beat a viewer needs to "
    "understand it) — never drop in mid-sentence or mid-thought, and never start on something "
    "that refers to an earlier event the clip doesn't show. End cleanly right after the payoff, "
    "punchline or reaction lands. Use the transcript line timestamps to snap the start/end to "
    "natural sentence boundaries. The clip must run 15-45 seconds; do not pad with dead time, "
    "but do NOT cut so tight that the setup or context is lost.\n\n"
    "Return JSON:\n"
    "- clipworthy: true only if genuinely worth posting (apply the rules above).\n"
    "- score: 0..1 confidence it performs as a Short.\n"
    "- kind: best-fitting label.\n"
    "- title: a strong, scroll-stopping Renyan-style title. (a) Write it in the SAME LANGUAGE "
    "the streamer speaks in the transcript — Russian dialogue -> Russian title, English -> "
    "English. (b) Prefer a meme / relatable / reaction framing ('POV: ...', 'WHEN YOUR TEAM "
    "...', 'X BUT Y', 'NAH CHAT WE ...') over a dry highlight label like 'INSANE 1v5 ACE'. "
    "(c) Make it SPECIFIC to what actually happens or is said in THIS clip — not generic. "
    "(d) Build curiosity; a trailing '...' cliffhanger is on-brand. (e) ALL CAPS is fine, at "
    "most one emoji, NO hashtags or quotes (hashtags are added at publish time). Good English "
    "examples: 'POV: YOUR 2K ELO TEAMMATE BLAMES EVERYONE BUT HIMSELF...', 'NAH CHAT WE GOT A "
    "GENIUS ON OUR HANDS...', 'THANK YOU SHERLOCK...'. Use a real map/site name only if you "
    "are sure; never invent intrigue (a 'secret room' etc.) that isn't there.\n"
    "- hook: a punchy 2-4 word on-screen opener in the SAME LANGUAGE as the title (UPPERCASE "
    "ok), or empty.\n"
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
    sfx: str = ""           # chosen sound-effect name (or "" for none)
    sfx_time: float = 0.0   # absolute seconds where the SFX should hit
    music: str = ""         # chosen background mood: '', 'calm', or 'hype'


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
                 min_len: float = 15.0, max_len: float = 45.0,
                 transcript: str = "", audio_level: float = 0.0) -> VisionVerdict | None:
    sampled = _sample_frames(vod_path, start, end, frames)
    if not sampled:
        return None
    imgs = [b for b, _ in sampled]
    stamps = [t for _, t in sampled]
    labels = ", ".join(f"frame {i+1}={t}s" for i, t in enumerate(stamps))
    dialogue = (transcript or "").strip()
    talk = (
        f"\n\nWhat the streamer SAYS during this window (timestamped transcript lines, "
        f"Russian and sometimes English):\n{dialogue}"
        if dialogue else
        "\n\n(No transcript available for this window — judge from the frames alone.)"
    )
    audio_note = (
        f"\n\nAUDIO ENERGY: a vocal reaction about {audio_level:.1f}x louder than his baseline "
        f"overlaps this window — he raised his voice / got loud here. A louder, higher-energy "
        f"outburst means a BIGGER reaction: weight genuine hype or rage UP accordingly. (A "
        f"high number does not rescue mild, generic complaining — judge the content too.)"
        if audio_level and audio_level >= 1.5 else ""
    )
    sfx_names = _sfx_names()
    sfx_note = (
        f"\n\nOPTIONAL SOUND EFFECT: you may add ONE meme sound to punctuate the clip, but "
        f"ONLY if it genuinely fits (e.g. 'vine-boom' on a punchline, a fail sound on a whiff, "
        f"'metal-pipe-clang' on a death). Most clips need NONE — default to 'none'. If you pick "
        f"one, set sfx to its EXACT name and sfx_time to the absolute second (same scale as "
        f"clip_start) where it should hit. Available sounds: {', '.join(sfx_names)}."
        if sfx_names else ""
    )
    music_on = bool(CONFIG.get("music", {}).get("enabled", True))
    music_note = (
        "\n\nBACKGROUND MUSIC: pick a music mood for this clip. 'calm' = boring / low-action / "
        "downtime clips AND rage clips (calm Oblivion music plays under his anger). 'hype' = "
        "clips with many kills or genuinely good plays. 'none' = no music. The track plays "
        "quietly and automatically ducks out while he's loud (raging/hyped) and returns when "
        "he calms, so choose by the clip's overall vibe."
        if music_on else ""
    )
    user = (
        f"These {len(imgs)} frames span {start:.0f}s to {end:.0f}s of the stream, in order "
        f"({labels}). Judge whether this is a clipworthy CS2 Short and pick the tight 15-45s "
        f"cut using those timestamps.{talk}{audio_note}{sfx_note}{music_note}"
    )
    extra_props: dict = {}
    if sfx_names:
        extra_props["sfx"] = {"type": "string", "enum": sfx_names + ["none"]}
        extra_props["sfx_time"] = {"type": "number"}
    if music_on:
        extra_props["music"] = {"type": "string", "enum": ["calm", "hype", "none"]}
    schema = _SCHEMA
    if extra_props:
        schema = {**_SCHEMA, "properties": {**_SCHEMA["properties"], **extra_props}}
    try:
        r = llm.chat_vision(_SYSTEM, user, imgs, schema)
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

    sfx = str(r.get("sfx", "") or "").strip()
    if sfx.lower() == "none" or sfx not in sfx_names:   # guard against junk / 'none'
        sfx = ""
    sfx_time = float(r.get("sfx_time", 0.0) or 0.0)
    music = str(r.get("music", "") or "").strip().lower()
    if music not in ("calm", "hype"):
        music = ""

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
        sfx=sfx,
        sfx_time=round(sfx_time, 2),
        music=music,
    )
