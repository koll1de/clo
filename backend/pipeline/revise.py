"""Free-text re-edit — turn a plain-language change request into an EditPlan change.

The user watches a clip and types e.g. "cut the first 2 seconds", "use Impact font",
"less zoom", "captions off". The LLM converts that into a bounded patch, we apply it to
the clip's stored EditPlan, and re-render. No re-analysis of the VOD needed.
"""
from __future__ import annotations

from .. import llm, store
from ..editplan import EditPlan, FONTS
from ..models import Clip
from . import render as render_stage

_FONT_NAMES = list(FONTS.keys())

_REVISION_SCHEMA = {
    "type": "object",
    "properties": {
        "captions_enabled": {"type": "boolean"},
        "caption_font": {"type": "string", "enum": _FONT_NAMES},
        "caption_size": {"type": "integer"},
        "caption_uppercase": {"type": "boolean"},
        "reframe_mode": {"type": "string", "enum": ["fill_crop", "fit_blur"]},
        "reframe_zoom": {"type": "number"},
        "reframe_x_center": {"type": "number"},
        "trim_start_delta": {"type": "number"},
        "trim_end_delta": {"type": "number"},
        "intro_hook_enabled": {"type": "boolean"},
        "intro_hook_text": {"type": "string"},
    },
}

_SYSTEM = (
    "You convert a user's plain-language video-edit request into a JSON patch for a "
    "vertical short. Only include the fields that should change; omit everything else.\n"
    f"Available caption fonts: {_FONT_NAMES}.\n"
    "Field meanings:\n"
    "- reframe_mode: 'fill_crop' = zoomed/immersive, 'fit_blur' = full width with blurred bg.\n"
    "- reframe_zoom: 1.0 = default; higher zooms in more, lower zooms out.\n"
    "- reframe_x_center: 0..1 horizontal crop center (0.5 = middle, <0.5 left, >0.5 right).\n"
    "- trim_start_delta: seconds to move the START. Positive trims the beginning "
    "(e.g. 'cut the first 2 seconds' -> 2). Negative starts earlier.\n"
    "- trim_end_delta: seconds to move the END. Positive makes it longer at the end, "
    "negative trims the end (e.g. 'cut the last 3 seconds' -> -3).\n"
    "- intro_hook_text: the big text shown at the very start.\n"
    "IMPORTANT: 'use the Impact font' / 'шрифт Impact' means caption_font='Impact' "
    "(NOT intro_hook_text). Only set intro_hook_text when the user gives actual hook wording.\n"
    "Examples:\n"
    "  'больше зума' -> {\"reframe_zoom\": 1.3}   'меньше зума' -> {\"reframe_zoom\": 1.0}\n"
    "  'обрежь первые 2 секунды' -> {\"trim_start_delta\": 2}\n"
    "  'subtitles off' -> {\"captions_enabled\": false}\n"
    "  'use Impact font and cut last 3s' -> {\"caption_font\": \"Impact\", \"trim_end_delta\": -3}\n"
    "Interpret requests in Russian or English."
)


def _apply(plan: EditPlan, patch: dict) -> EditPlan:
    if "captions_enabled" in patch:
        plan.captions.enabled = bool(patch["captions_enabled"])
    if patch.get("caption_font") in FONTS:
        plan.captions.font = patch["caption_font"]
    if "caption_size" in patch:
        plan.captions.size = max(20, min(200, int(patch["caption_size"])))
    if "caption_uppercase" in patch:
        plan.captions.uppercase = bool(patch["caption_uppercase"])
    if patch.get("reframe_mode") in ("fill_crop", "fit_blur"):
        plan.reframe.mode = patch["reframe_mode"]
    if "reframe_zoom" in patch:
        plan.reframe.zoom = max(1.0, min(3.0, float(patch["reframe_zoom"])))
    if "reframe_x_center" in patch:
        plan.reframe.x_center = max(0.0, min(1.0, float(patch["reframe_x_center"])))
    if "trim_start_delta" in patch:
        plan.start = max(0.0, plan.start + float(patch["trim_start_delta"]))
    if "trim_end_delta" in patch:
        plan.end = plan.end + float(patch["trim_end_delta"])
    if "intro_hook_enabled" in patch:
        plan.intro_hook.enabled = bool(patch["intro_hook_enabled"])
    if "intro_hook_text" in patch:
        plan.intro_hook.text = str(patch["intro_hook_text"])
    # keep the clip valid
    if plan.end - plan.start < 2.0:
        plan.end = plan.start + 2.0
    return plan


def revise_clip(clip: Clip, request_text: str) -> Clip:
    if not clip.edit_plan:
        raise ValueError("clip has no edit plan to revise")
    job = store.get_job(clip.job_id)
    transcript_path = job.transcript_path if job else None

    patch = llm.chat_json(_SYSTEM, f"Request: {request_text}", _REVISION_SCHEMA, temperature=0.1)
    plan = _apply(EditPlan.model_validate(clip.edit_plan), patch)

    out = render_stage.render(plan, clip.id, transcript_path=transcript_path)
    clip.file_path = str(out)
    clip.edit_plan = plan.model_dump()
    # reflect a changed time window on the clip record too
    clip.start, clip.end = plan.start, plan.end
    store.save_clip(clip)
    return clip
