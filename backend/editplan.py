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
ASSET_FONTS = ROOT / "assets" / "fonts"   # bundled fonts (Nata Sans) that ship with the app

# The bundled, OFL-licensed, Cyrillic-capable family shipped in assets/fonts (instanced
# from the Nata Sans variable font). Every render falls back to this when a requested
# font is missing, so the app is self-contained and never silently renders tofu/the
# wrong face for Russian text on a machine that lacks a given system font.
FALLBACK_FONT = "Nata Sans"

# Friendly name -> (file, family libass expects, asset=True if it lives in assets/fonts).
# Each Nata Sans weight is its OWN family name so the ASS Fontname field selects the exact
# face under libass (which keys on family name, not the OS/2 weight class) on Windows.
FONTS: dict[str, dict] = {
    # --- bundled: ship with the app, render identically on any machine ---
    "Nata Sans":           {"file": "NataSans-Regular.ttf",   "family": "Nata Sans",           "asset": True},
    "Nata Sans Medium":    {"file": "NataSans-Medium.ttf",    "family": "Nata Sans Medium",    "asset": True},
    "Nata Sans SemiBold":  {"file": "NataSans-SemiBold.ttf",  "family": "Nata Sans SemiBold",  "asset": True},
    "Nata Sans Bold":      {"file": "NataSans-Bold.ttf",      "family": "Nata Sans Bold",      "asset": True},
    "Nata Sans ExtraBold": {"file": "NataSans-ExtraBold.ttf", "family": "Nata Sans ExtraBold", "asset": True},
    # --- optional system fonts: selectable for variety, NOT bundled (Windows only) ---
    "Bahnschrift": {"file": "bahnschrift.ttf", "family": "Bahnschrift"},  # modern condensed, Cyrillic
    "Segoe Black": {"file": "seguibl.ttf", "family": "Segoe UI Black"},
    "Arial Black": {"file": "ariblk.ttf", "family": "Arial Black"},
    "Impact":      {"file": "impact.ttf", "family": "Impact"},
    "Arial Bold":  {"file": "arialbd.ttf", "family": "Arial"},
    "Tahoma":      {"file": "tahoma.ttf", "family": "Tahoma"},
}


def _font_path(entry: dict) -> Path:
    base = ASSET_FONTS if entry.get("asset") else WIN_FONTS
    return base / entry["file"]


def _resolve(name: str) -> dict:
    """The font entry to actually use: the requested one if its file exists on this
    machine, otherwise the bundled Cyrillic fallback. font_file() and font_family() both
    go through here so the staged file and the ASS Fontname stay in lockstep — a missing
    system font can never leave libass with a family name it has no file for."""
    entry = FONTS.get(name)
    if entry is not None and _font_path(entry).exists():
        return entry
    if entry is None:
        print(f"[font] {name!r} not in registry; using bundled {FALLBACK_FONT!r}")
    else:
        print(f"[font] {name!r} file missing ({_font_path(entry)}); using bundled {FALLBACK_FONT!r}")
    return FONTS[FALLBACK_FONT]


def font_file(name: str) -> Path:
    return _font_path(_resolve(name))


def font_family(name: str) -> str:
    return _resolve(name)["family"]


def _has_cyrillic(text: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in text)


def cyrillic_safe_font(name: str, text: str) -> str:
    """Impact (and other Latin-only faces) can't render Russian. If the text has Cyrillic,
    fall back to a heavy bundled Cyrillic-capable face so the title actually shows."""
    latin_only = {"Impact"}
    if name in latin_only and _has_cyrillic(text):
        return "Nata Sans ExtraBold"   # bundled, heavy, full Cyrillic
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
    mode: Literal["fill_crop", "fit_blur", "facecam_top", "gameplay_blur"] = "fill_crop"
    zoom: float = 1.0          # 1.0 = just covers the frame; >1 zooms further in
    x_center: float = 0.5      # horizontal crop center (0=left, 1=right)
    y_center: float = 0.5      # vertical crop center for the gameplay region
    gameplay_mid: float = 0.5  # gameplay_blur: share of the clip height the SHARP gameplay band
                               # takes (bigger = more zoomed-in gameplay, smaller blur bands)


class Captions(BaseModel):
    enabled: bool = True
    font: str = "Nata Sans Medium"   # bundled, Cyrillic-capable (no system font needed)
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
    font: str = "Nata Sans SemiBold"   # bundled, Cyrillic-capable (no swap needed)


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


class Music(BaseModel):
    """Background music bed, laid under the clip and auto-ducked under his voice."""
    enabled: bool = False
    file: str = ""             # absolute path to the chosen track
    volume: float = 0.18       # background level (low)
    duck_ratio: float = 12.0   # how hard it ducks when his voice is loud


class Subscribe(BaseModel):
    """A subscribe-animation overlay (.mov with alpha + audio) dropped onto every clip,
    under the watermark, a couple seconds in."""
    enabled: bool = False
    file: str = ""             # absolute path to the animation (.mov with alpha)
    volume: float = 0.5        # its audio level (0..1)
    start: float = 2.5         # clip-relative seconds before it appears
    scale: float = 0.6         # cropped-content width as a fraction of the clip width
    gap: int = 24              # px gap below the watermark
    # Content crop (fractions of the source) — many subscribe .movs put a small button in a big
    # transparent canvas; crop to the button so it isn't scaled down to nothing. Full = 0,0,1,1.
    crop_x: float = 0.31
    crop_y: float = 0.49
    crop_w: float = 0.38
    crop_h: float = 0.43


class Effect(BaseModel):
    type: Literal["zoom", "speed"]
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
    music: Music = Field(default_factory=Music)
    subscribe: Subscribe = Field(default_factory=Subscribe)
    effects: list[Effect] = Field(default_factory=list)


def default_plan(source: str, clip, edit_cfg: dict) -> EditPlan:
    """Build a starting plan for a clip from the app's edit config."""
    plan = EditPlan(source=source, start=clip.start, end=clip.end)
    plan.reframe.mode = edit_cfg.get("reframe_mode", "fill_crop")
    plan.reframe.zoom = float(edit_cfg.get("reframe_zoom", 1.0))
    plan.reframe.gameplay_mid = float(edit_cfg.get("gameplay_mid", 0.5))
    plan.captions.enabled = bool(edit_cfg.get("subtitles", False))
    plan.captions.font = edit_cfg.get("subtitle_font", "Nata Sans Medium")
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

    # The AI (or the min-gameplay quota) can pick the no-webcam 'gameplay' layout: full
    # gameplay in the middle with a blurred backdrop above/below, no cam.
    if getattr(clip, "layout", "facecam") == "gameplay":
        plan.reframe.mode = "gameplay_blur"
        plan.facecam.present = False

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

    # Background music bed the vision gate chose (renderer ducks it under his voice).
    mood = (getattr(clip, "music", "") or "").strip().lower()
    mcfg = CONFIG.get("music", {})
    if mcfg.get("enabled", True) and mood in ("calm", "hype"):
        track = (mcfg.get("tracks", {}) or {}).get(mood, f"{mood}.mp3")
        mpath = ROOT / mcfg.get("dir", "assets/music") / track
        # Don't lay our bed over a part where music is ALREADY playing in the source (e.g.
        # he has a track on) — that would stack two songs. Detect it in the clip's audio.
        already = False
        if mcfg.get("skip_if_present", True):
            try:
                from .pipeline.audio import segment_has_music
                already = segment_has_music(getattr(clip, "job_id", ""), clip.start, clip.end)
            except Exception as e:
                print(f"[music] source-music check skipped: {e}")
        if mpath.exists() and not already:
            plan.music = Music(
                enabled=True, file=str(mpath),
                volume=float(mcfg.get("volume", 0.18)),
                duck_ratio=float(mcfg.get("duck_ratio", 12)),
            )
        elif already:
            print(f"[music] source already has music {clip.start:.0f}-{clip.end:.0f}s -> no bed")

    # Subscribe-animation overlay (under the watermark, a couple seconds in).
    scfg = CONFIG.get("subscribe", {})
    if scfg.get("enabled", False):
        spath = scfg.get("file", "")
        sp = Path(spath) if os.path.isabs(spath) else (ROOT / spath)
        if sp.exists():
            crop = scfg.get("content_crop", {}) or {}
            plan.subscribe = Subscribe(
                enabled=True, file=str(sp),
                volume=float(scfg.get("volume", 0.5)),
                start=float(scfg.get("start", 2.5)),
                scale=float(scfg.get("scale", 0.6)),
                gap=int(scfg.get("gap", 24)),
                crop_x=float(crop.get("x", 0.31)), crop_y=float(crop.get("y", 0.49)),
                crop_w=float(crop.get("w", 0.38)), crop_h=float(crop.get("h", 0.43)),
            )
    return plan
