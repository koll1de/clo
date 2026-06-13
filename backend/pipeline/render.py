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


def render(plan: EditPlan, clip_id: str, transcript_path: str | None = None) -> Path:
    out_path = Paths.clips / f"{clip_id}.mp4"
    ass_path = Paths.work / f"{clip_id}.ass"

    # Build the subtitle/hook overlay (relative filename so the ffmpeg cwd handles paths)
    vf_parts = [_reframe_filter(plan)]
    if (plan.captions.enabled or (plan.intro_hook.enabled and plan.intro_hook.text)) and transcript_path:
        captions_mod.build_ass(plan, transcript_path, ass_path)
        _stage_font(plan.captions.font)
        vf_parts.append(f"ass={ass_path.name}:fontsdir=.")
    vf = ",".join(vf_parts)

    dur = max(0.1, plan.end - plan.start)
    cmd = [
        ffmpeg_bin(), "-y",
        "-ss", f"{plan.start:.3f}", "-t", f"{dur:.3f}",
        "-i", plan.source,
        "-vf", vf,
        "-r", str(plan.fps),
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
