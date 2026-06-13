"""The parametric edit plan.

Every clip is described by an EditPlan (pure data), and the renderer turns it into
a video. Because edits are data, the user's free-text change requests ("make the zoom
less aggressive", "use Impact font", "cut the first 2 seconds") become small edits to
this object and a re-render — no re-analysis needed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field

WIN_FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"

# Friendly name -> (file on disk, font family name libass/ASS expects). All Cyrillic-capable.
FONTS: dict[str, dict] = {
    "Segoe Black": {"file": "seguibl.ttf", "family": "Segoe UI Black"},
    "Arial Black": {"file": "ariblk.ttf", "family": "Arial Black"},
    "Impact":      {"file": "impact.ttf", "family": "Impact"},
    "Arial Bold":  {"file": "arialbd.ttf", "family": "Arial"},
    "Tahoma":      {"file": "tahoma.ttf", "family": "Tahoma"},
}


def font_file(name: str) -> Path:
    entry = FONTS.get(name, FONTS["Segoe Black"])
    return WIN_FONTS / entry["file"]


def font_family(name: str) -> str:
    return FONTS.get(name, FONTS["Segoe Black"])["family"]


class Reframe(BaseModel):
    mode: Literal["fill_crop", "fit_blur"] = "fill_crop"
    zoom: float = 1.0          # 1.0 = just covers the frame; >1 zooms further in
    x_center: float = 0.5      # horizontal crop center (0=left, 1=right)


class Captions(BaseModel):
    enabled: bool = True
    font: str = "Segoe Black"
    size: int = 74
    primary: str = "#FFFFFF"   # text color
    outline_color: str = "#000000"
    outline: int = 4
    margin_v: int = 230        # px above the bottom edge
    uppercase: bool = False


class IntroHook(BaseModel):
    enabled: bool = True
    text: str = ""
    seconds: float = 1.3


class QuestionCard(BaseModel):
    """The red-tag + bold question overlay used when he talks to chat / gives tips."""
    enabled: bool = False
    username: str = ""
    text: str = ""
    highlights: list[str] = Field(default_factory=list)  # words rendered in gold
    t0: float = 0.0            # clip-relative seconds to show
    t1: float = 5.0


class Effect(BaseModel):
    type: Literal["zoom", "speed", "sfx"]
    t0: float                  # clip-relative seconds
    t1: float = 0.0
    params: dict = Field(default_factory=dict)


class EditPlan(BaseModel):
    source: str                # path to the source VOD
    start: float               # source in-point (seconds)
    end: float                 # source out-point (seconds)
    width: int = 1080
    height: int = 1920
    fps: int = 30
    reframe: Reframe = Field(default_factory=Reframe)
    captions: Captions = Field(default_factory=Captions)
    intro_hook: IntroHook = Field(default_factory=IntroHook)
    question_card: QuestionCard = Field(default_factory=QuestionCard)
    effects: list[Effect] = Field(default_factory=list)


def default_plan(source: str, clip, edit_cfg: dict) -> EditPlan:
    """Build a starting plan for a clip from the app's edit config."""
    plan = EditPlan(source=source, start=clip.start, end=clip.end)
    plan.reframe.mode = edit_cfg.get("reframe_mode", "fill_crop")
    plan.reframe.zoom = float(edit_cfg.get("reframe_zoom", 1.0))
    plan.captions.enabled = bool(edit_cfg.get("subtitles", True))
    plan.captions.font = edit_cfg.get("subtitle_font", "Segoe Black")
    plan.intro_hook.enabled = bool(edit_cfg.get("intro_hook", True))
    plan.intro_hook.text = clip.title or ""

    # If audio found the loudest beat in this clip, punch in on it.
    peak = getattr(clip, "audio_peak", None)
    if edit_cfg.get("zoom_punch_ins", True) and peak is not None:
        rel = peak - clip.start
        if 0.2 < rel < (clip.end - clip.start) - 0.2:
            plan.effects.append(Effect(type="zoom", t0=round(rel - 0.4, 2),
                                       t1=round(rel + 1.1, 2), params={"amount": 0.2}))
    # When he's talking to chat / giving tips, show the question card from his line.
    if clip.kind == "tips_to_chat":
        text = (getattr(clip, "quote", "") or clip.title or "").strip()
        if text:
            plan.question_card.enabled = True
            plan.question_card.text = text
            plan.question_card.username = getattr(clip, "question_username", "") or ""
            plan.question_card.highlights = list(getattr(clip, "question_highlights", []) or [])
            # show it after the intro hook, for most of the clip
            plan.question_card.t0 = round(plan.intro_hook.seconds + 0.2, 2) if plan.intro_hook.enabled else 0.3
            plan.question_card.t1 = round(min(plan.question_card.t0 + 6.0, clip.end - clip.start), 2)
    return plan
