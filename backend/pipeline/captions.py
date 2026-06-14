"""Build an ASS subtitle file for a clip from the transcript window.

Plain styled captions (not karaoke), one line per spoken segment, timed relative to
the clip start. Styling comes from the EditPlan's Captions. Uses libass, which wraps
long lines and renders Cyrillic correctly.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..editplan import EditPlan, font_family

# Intro-hook (persistent title) sizing. We position each wrapped title line ourselves so we
# can control the leading: libass has no line-spacing tag and otherwise uses the font's full
# line height, which reads too airy for a big uppercase title. HOOK_LINE_SPACING is the gap
# between baselines as a fraction of the font size — lower = tighter lines.
HOOK_SIZE = 104
HOOK_LINE_SPACING = 0.92


def _ass_color(hex_color: str) -> str:
    """#RRGGBB -> ASS &HBBGGRR (no alpha)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _load_segments(transcript_path: str | None) -> list[dict]:
    if not transcript_path:
        return []
    with open(transcript_path, "r", encoding="utf-8") as f:
        return json.load(f).get("segments", [])


def _wrap(text: str, width: int) -> str:
    """Word-wrap into ASS \\N-separated lines of at most `width` characters.
    Manual wrapping makes the boxed question card lay out deterministically."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        lines.append(cur)
    return "\\N".join(lines)


def _highlight(text: str, highlights: list[str], white: str, gold: str) -> str:
    """Uppercase the text and colour any `highlights` words gold (rest white)."""
    hi = {h.strip().lower() for h in highlights if h.strip()}
    out: list[str] = []
    for word in text.split():
        # compare on letters/digits only so trailing punctuation still matches
        bare = "".join(ch for ch in word if ch.isalnum()).lower()
        if bare and bare in hi:
            out.append(f"{{\\1c{gold}}}{word.upper()}{{\\1c{white}}}")
        else:
            out.append(word.upper())
    return " ".join(out)


def _question_card_events(plan: EditPlan) -> list[str]:
    """Render the red username tag + dark question container (with gold keyword
    highlights) as positioned, auto-sized libass boxes. Clip-relative timing."""
    qc = plan.question_card
    if not (qc.enabled and qc.text.strip()):
        return []

    white = "&H00FFFFFF"
    gold = _ass_color("#F5B400")
    s, e = _ts(max(0.0, qc.t0)), _ts(max(qc.t0 + 0.5, qc.t1))

    events: list[str] = []
    # Red username tag (top-left), shown only if we know who said it.
    if qc.username.strip():
        tag = qc.username.strip().upper().replace("{", "(").replace("}", ")")
        events.append(f"Dialogue: 5,{s},{e},QTag,,0,0,0,,{{\\an7\\pos(70,250)}}{tag}")

    # Dark question container, wrapped and highlighted. A lighter box one layer
    # below (slightly larger border) reads as the thin outline from the reference.
    body = _wrap(qc.text.strip().replace("{", "(").replace("}", ")"), 20)
    marked = _highlight(body, qc.highlights, white, gold)
    y = 340 if qc.username.strip() else 270
    # Edge layer (light, larger border) sits under the dark box for the thin outline.
    events.append(f"Dialogue: 4,{s},{e},QBoxEdge,,0,0,0,,{{\\an7\\pos(70,{y})}}{body.upper()}")
    events.append(f"Dialogue: 5,{s},{e},QBox,,0,0,0,,{{\\an7\\pos(70,{y})\\1c{white}}}{marked}")
    return events


def build_ass(plan: EditPlan, transcript_path: str | None, out_path: Path) -> Path:
    cap = plan.captions
    segments = _load_segments(transcript_path) if cap.enabled else []

    family = font_family(cap.font)
    primary = _ass_color(cap.primary)
    outline = _ass_color(cap.outline_color)

    hook = plan.intro_hook
    hook_family = font_family(hook.font)
    hook_color = _ass_color(hook.color)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {plan.width}
PlayResY: {plan.height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{family},{cap.size},{primary},{outline},&H00000000,-1,0,0,0,100,100,0,0,1,{cap.outline},0,2,80,80,{cap.margin_v},204
Style: Hook,{hook_family},{HOOK_SIZE},{hook_color},&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,7,0,8,90,90,300,204
Style: QTag,{family},48,&H00FFFFFF,&H002828D6,&H00000000,-1,0,0,0,100,100,0,0,3,14,0,7,0,0,0,204
Style: QBox,{family},58,&H00FFFFFF,&H00231F1E,&H64000000,-1,0,0,0,100,100,0,0,3,18,6,7,0,0,0,204
Style: QBoxEdge,{family},58,&H00D8D0CF,&H00D8D0CF,&H00000000,-1,0,0,0,100,100,0,0,3,23,0,7,0,0,0,204

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []
    if hook.enabled and hook.text.strip():
        htext = hook.text.strip().upper().replace("{", "(").replace("}", ")")
        wrapped = _wrap(htext, 16).split("\\N")
        clip_dur = plan.end - plan.start
        hook_end = clip_dur if hook.persist else min(hook.seconds, clip_dur)
        hook_x = plan.width // 2
        lh = max(1, round(HOOK_SIZE * HOOK_LINE_SPACING))   # our own baseline-to-baseline leading
        if plan.reframe.mode == "facecam_top" and plan.facecam.present:
            # centre the title block ON the seam between the cam (top) and the gameplay (below)
            seam = int(plan.height * min(0.7, max(0.15, plan.facecam.band)))
            an = 5
            y0 = seam - (len(wrapped) - 1) * lh // 2
        elif plan.reframe.mode == "gameplay_blur":
            # No-cam layout: title in the top blurred band, nudged DOWN from the very top edge.
            # Uses the same band geometry as the renderer so it tracks the gameplay_mid zoom.
            frac = min(0.72, max(0.34, plan.reframe.gameplay_mid))
            mid_h = (round(plan.height * frac) // 2) * 2
            top_h = ((plan.height - mid_h) // 2 // 2) * 2
            an, y0 = 8, int(top_h * 0.30)
        else:
            an, y0 = 8, 140
        # One Dialogue per wrapped line so we control the leading (libass has no line-spacing tag).
        for i, ln in enumerate(wrapped):
            lines.append(
                f"Dialogue: 1,{_ts(0)},{_ts(hook_end)},Hook,,0,0,0,,"
                f"{{\\an{an}\\pos({hook_x},{y0 + i * lh})}}{ln}"
            )
    for seg in segments:
        s = seg["start"] - plan.start
        e = seg["end"] - plan.start
        if e <= 0 or s >= (plan.end - plan.start):
            continue
        s = max(0.0, s)
        e = min(plan.end - plan.start, e)
        text = (seg.get("text") or "").strip().replace("\n", " ")
        if not text:
            continue
        if cap.uppercase:
            text = text.upper()
        text = text.replace("{", "(").replace("}", ")")  # ASS override guard
        lines.append(f"Dialogue: 0,{_ts(s)},{_ts(e)},Main,,0,0,0,,{text}")

    lines.extend(_question_card_events(plan))

    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path
