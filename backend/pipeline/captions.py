"""Build an ASS subtitle file for a clip from the transcript window.

Plain styled captions (not karaoke), one line per spoken segment, timed relative to
the clip start. Styling comes from the EditPlan's Captions. Uses libass, which wraps
long lines and renders Cyrillic correctly.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..editplan import EditPlan, font_family


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


def _load_segments(transcript_path: str) -> list[dict]:
    with open(transcript_path, "r", encoding="utf-8") as f:
        return json.load(f).get("segments", [])


def build_ass(plan: EditPlan, transcript_path: str, out_path: Path) -> Path:
    cap = plan.captions
    segments = _load_segments(transcript_path)

    family = font_family(cap.font)
    primary = _ass_color(cap.primary)
    outline = _ass_color(cap.outline_color)

    hook = plan.intro_hook
    hook_family = font_family(plan.captions.font)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {plan.width}
PlayResY: {plan.height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{family},{cap.size},{primary},{outline},&H00000000,-1,0,0,0,100,100,0,0,1,{cap.outline},0,2,80,80,{cap.margin_v},204
Style: Hook,{hook_family},104,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,7,0,8,90,90,300,204

[Events]
Format: Layer, Start, End, Style, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []
    if hook.enabled and hook.text.strip():
        htext = hook.text.strip().upper().replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(hook.seconds)},Hook,,0,0,0,,{htext}")
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

    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path
