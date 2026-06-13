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

from .config import CONFIG, ROOT

WIN_FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"

# Friendly name -> (file on disk, font family name libass/ASS expects). All Cyrillic-capable.
FONTS: dict[str, dict] = {
    "Bahnschrift": {"file": "bahnschrift.ttf", "family": "Bahnschrift"},  # modern condensed, Cyrillic
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


def _has_cyrillic(text: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in text)


def cyrillic_safe_font(name: str, text: str) -> str:
    """Impact (and other Latin-only faces) can't render Russian. If the text has Cyrillic,
    fall back to a heavy Cyrillic-capable font so the title actually shows."""
    latin_only = {"Impact"}
    if name in latin_only and _has_cyrillic(text):
        return "Arial Black"
    return name


class Facecam(BaseModel):
    """Source location of the streamer's webcam (fractions of the frame) and how big
    its band is in the vertical clip. Used by the 'facecam_top' reframe (Renyan style:
    reaction cam on top, gameplay below)."""
    present: bool = False
    x: float = 0.0            # webcam box in the source, as fractions of W/H
    y: float = 0.0
    w: float = 0.21
    h: float = 0.26
    band: float = 0.34        # fraction of the 1920px-tall clip the cam occupies on top


class Reframe(BaseModel):
    mode: Literal["fill_crop", "fit_blur", "facecam_top"] = "fill_crop"
    zoom: float = 1.0          # 1.0 = just covers the frame; >1 zooms further in
    x_center: float = 0.5      # horizontal crop center (0=left, 1=right)
    y_center: float = 0.5      # vertical crop center for the gameplay region


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
    seconds: float = 1.3        # only used when persist=False
    persist: bool = True        # keep the title on screen for the WHOLE clip
    color: str = "#FFD400"      # yellow
    font: str = "Impact"        # heavy meme font (auto-swapped to a Cyrillic face for Russian)


class QuestionCard(BaseModel):
    """The red-tag + bold question overlay used when he talks to chat / gives tips."""
    enabled: bool = False
    username: str = ""
    text: str = ""
    highlights: list[str] = Field(default_factory=list)  # words rendered in gold
    t0: float = 0.0            # clip-relative seconds to show
    t1: float = 5.0


class Watermark(BaseModel):
    """Renyan-style channel watermark: a logo (Twitch glyph) + nickname, semi-transparent,
    centred over the gameplay so it survives re-uploads."""
    enabled: bool = False
    image: str = ""            # absolute path to a pre-composited watermark PNG (with alpha)
    opacity: float = 0.5       # 0..1
    scale: float = 0.30        # watermark width as a fraction of the clip width


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
    facecam: Facecam = Field(default_factory=Facecam)
    captions: Captions = Field(default_factory=Captions)
    intro_hook: IntroHook = Field(default_factory=IntroHook)
    question_card: QuestionCard = Field(default_factory=QuestionCard)
    watermark: Watermark = Field(default_factory=Watermark)
    effects: list[Effect] = Field(default_factory=list)


def default_plan(source: str, clip, edit_cfg: dict) -> EditPlan:
    """Build a starting plan for a clip from the app's edit config."""
    plan = EditPlan(source=source, start=clip.start, end=clip.end)
    plan.reframe.mode = edit_cfg.get("reframe_mode", "fill_crop")
    plan.reframe.zoom = float(edit_cfg.get("reframe_zoom", 1.0))
    plan.captions.enabled = bool(edit_cfg.get("subtitles", False))
    plan.captions.font = edit_cfg.get("subtitle_font", "Bahnschrift")
    plan.intro_hook.enabled = bool(edit_cfg.get("intro_hook", True))
    plan.intro_hook.text = (getattr(clip, "hook", "") or clip.title or "")
    plan.intro_hook.persist = bool(edit_cfg.get("hook_persist", True))
    plan.intro_hook.color = edit_cfg.get("hook_color", "#FFD400")
    # Impact can't render Russian; swap to a Cyrillic-capable face when the title is Russian.
    plan.intro_hook.font = cyrillic_safe_font(
        edit_cfg.get("hook_font", "Impact"), plan.intro_hook.text)

    # Facecam (Renyan-style cam-on-top layout). Defaults from config; per-job detection
    # can override via edit_cfg["facecam"].
    fcfg = edit_cfg.get("facecam") or {}
    plan.facecam = Facecam(**{**Facecam().model_dump(), **{k: v for k, v in fcfg.items()
                                                           if k in Facecam.model_fields}})
    # honour a per-clip detected rect if present
    det = getattr(clip, "facecam_rect", None)
    if det:
        for k in ("x", "y", "w", "h", "present"):
            if k in det:
                setattr(plan.facecam, k, det[k])

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

    # Channel watermark (logo + nickname), centred over the gameplay.
    wcfg = edit_cfg.get("watermark") or {}
    if wcfg.get("enabled") and wcfg.get("image"):
        img = str(wcfg.get("image", "")).strip()
        if img and not Path(img).is_absolute():
            img = str(Path(__file__).resolve().parent.parent / img)  # resolve vs repo root
        plan.watermark = Watermark(
            enabled=bool(img and Path(img).exists()),
            image=img,
            opacity=float(wcfg.get("opacity", 0.5)),
            scale=float(wcfg.get("scale", 0.30)),
        )

    # Sound effect the vision gate chose for this clip (renderer mixes it over the audio).
    sfx_name = (getattr(clip, "sfx", "") or "").strip()
    if edit_cfg.get("sound_effects", True) and sfx_name:
        scfg = CONFIG.get("sfx", {})
        sfx_path = ROOT / scfg.get("dir", "assets/sfx") / f"{sfx_name}.mp3"
        if sfx_path.exists():
            # sfx_time is absolute source seconds; make it clip-relative and keep it in-bounds
            t0 = max(0.0, float(getattr(clip, "sfx_time", 0.0)) - clip.start)
            t0 = min(t0, max(0.0, (clip.end - clip.start) - 0.2))
            plan.effects.append(Effect(
                type="sfx", t0=round(t0, 2),
                params={"file": str(sfx_path), "volume": float(scfg.get("volume", 0.8))},
            ))
    return plan
