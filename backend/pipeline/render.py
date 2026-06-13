"""Stage 4 — render an EditPlan into a finished vertical clip with ffmpeg.

v1 implements: precise cut, vertical reframe (fill_crop / fit_blur), styled Russian
captions, and the intro hook (both via one libass pass). Zoom punch-ins, speed ramps,
sound effects, and the question-card overlay are layered on next.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..config import Paths
from ..ffmpeg import ffmpeg_bin
from ..editplan import EditPlan, font_file
from . import captions as captions_mod


def _stage_font(name: str) -> None:
    """Copy a system font into the work dir so libass finds it via fontsdir='.'
    (avoids escaping the Windows drive colon inside the ffmpeg filtergraph)."""
    src = font_file(name)
    dst = Paths.work / src.name
    if src.exists() and not dst.exists():
        shutil.copy2(src, dst)


def _reframe_filter(plan: EditPlan) -> str:
    W, H = plan.width, plan.height
    if plan.reframe.mode == "fit_blur":
        return (
            f"split=2[bg][fg];"
            f"[bg]scale=-2:{H},crop={W}:{H},boxblur=24:2[bgb];"
            f"[fg]scale={W}:-2[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    # fill_crop (default): cover by height (optionally zoomed), crop centered
    z = max(1.0, plan.reframe.zoom)
    scaled_h = round(H * z)
    xc = plan.reframe.x_center
    return (
        f"scale=-2:{scaled_h},"
        f"crop={W}:{H}:(in_w-{W})*{xc}:(in_h-{H})/2,setsar=1"
    )


def _zoom_filter(plan: EditPlan) -> str | None:
    """Animated zoom punch-ins. Builds one z(t) expression from every `zoom` effect
    (each a smooth pulse that eases in/out over its window), then crops the WxH frame
    by 1/z centered and scales back up — a single pass that stacks multiple punch-ins.
    Returns None when there are no zoom effects."""
    W, H = plan.width, plan.height
    zooms = [e for e in plan.effects if e.type == "zoom"]
    if not zooms:
        return None
    terms = []
    for e in zooms:
        t0, t1 = e.t0, max(e.t0 + 0.3, e.t1)
        amp = float(e.params.get("amount", 0.18))   # 0.18 ≈ a punchy but not jarring push-in
        r = min(0.25, (t1 - t0) / 2)                 # ease seconds
        # amp * rampUp(t) * rampDown(t). Commas are fine: the value is single-quoted below.
        terms.append(
            f"{amp}*min(1,max(0,(t-{t0:.3f})/{r:.3f}))"
            f"*min(1,max(0,({t1:.3f}-t)/{r:.3f}))"
        )
    z = "1+" + "+".join(terms)
    # ffmpeg can't animate crop's output SIZE, so scale the whole frame by z(t) per
    # frame (eval=frame) and crop the constant WxH centre back out = zoom toward centre.
    return (
        f"scale=w='{W}*({z})':h='{H}*({z})':eval=frame,"
        f"crop={W}:{H}"
    )


def render(plan: EditPlan, clip_id: str, transcript_path: str | None = None) -> Path:
    out_path = Paths.clips / f"{clip_id}.mp4"
    ass_path = Paths.work / f"{clip_id}.ass"

    # Video filter chain: reframe -> zoom punch-ins -> caption/card overlay.
    vf_parts = [_reframe_filter(plan)]
    zoom = _zoom_filter(plan)
    if zoom:
        vf_parts.append(zoom)
    # Build the ASS (captions, intro hook, and/or question card) if anything needs it.
    needs_ass = (
        plan.captions.enabled
        or (plan.intro_hook.enabled and plan.intro_hook.text)
        or (plan.question_card.enabled and plan.question_card.text.strip())
    )
    if needs_ass and transcript_path:
        captions_mod.build_ass(plan, transcript_path, ass_path)
        _stage_font(plan.captions.font)
        vf_parts.append(f"ass={ass_path.name}:fontsdir=.")
    vf = ",".join(vf_parts)

    dur = max(0.1, plan.end - plan.start)

    # Sound-effect overlays: mix each onto the original audio at its t0 (only real files).
    sfx = [e for e in plan.effects
           if e.type == "sfx" and e.params.get("file") and Path(e.params["file"]).exists()]

    # ffmpeg runs with cwd=work (so the ass=<basename> path resolves), so the source
    # must be absolute — a relative VOD path would otherwise be looked for under work/.
    source = str(Path(plan.source).resolve())
    cmd = [ffmpeg_bin(), "-y", "-ss", f"{plan.start:.3f}", "-t", f"{dur:.3f}", "-i", source]
    for e in sfx:
        cmd += ["-i", str(e.params["file"])]

    if sfx:
        # ffmpeg forbids -vf alongside -filter_complex, so the video chain lives in the
        # graph too. Each sfx input is delayed to its t0 (ms) and amixed with clip audio.
        fc = [f"[0:v]{vf}[vout]"]
        labels = ["[0:a]"]
        for i, e in enumerate(sfx, start=1):
            delay = int(max(0.0, e.t0) * 1000)
            vol = float(e.params.get("volume", 1.0))
            fc.append(f"[{i}:a]adelay={delay}|{delay},volume={vol}[s{i}]")
            labels.append(f"[s{i}]")
        fc.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:dropout_transition=0[aout]")
        cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]", "-r", str(plan.fps)]
    else:
        cmd += ["-vf", vf, "-r", str(plan.fps)]

    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    # Run with cwd=work so the ass=<basename> resolves without Windows path escaping.
    proc = subprocess.run(
        cmd, cwd=str(Paths.work), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"render failed:\n{proc.stderr[-2000:]}")
    return out_path
