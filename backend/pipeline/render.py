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
    if plan.reframe.mode == "facecam_top":
        return _facecam_top_filter(plan)
    if plan.reframe.mode == "gameplay_blur":
        return _gameplay_blur_filter(plan)
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


def _facecam_top_filter(plan: EditPlan) -> str:
    """Renyan-style vertical: the streamer's webcam fills a band on top, the gameplay
    fills the rest below — each scaled-to-cover then centre-cropped (no distortion)."""
    W, H = plan.width, plan.height
    fc = plan.facecam
    top_h = max(2, round(H * min(0.7, max(0.15, fc.band))) // 2 * 2)  # even
    bot_h = H - top_h
    # webcam source region (fractions -> 'in_w'/'in_h' expressions, robust to any source size)
    cx, cy, cw, ch = fc.x, fc.y, fc.w, fc.h
    cam = (
        f"crop=in_w*{cw}:in_h*{ch}:in_w*{cx}:in_h*{cy},"
        f"scale={W}:{top_h}:force_original_aspect_ratio=increase,crop={W}:{top_h},setsar=1"
    )
    # gameplay: centre of the frame (cam sits in a corner, so a centred crop avoids it),
    # nudgeable via x_center/y_center
    xc, yc = plan.reframe.x_center, plan.reframe.y_center
    game = (
        f"scale={W}:{bot_h}:force_original_aspect_ratio=increase,"
        f"crop={W}:{bot_h}:(in_w-{W})*{xc}:(in_h-{bot_h})*{yc},setsar=1"
    )
    return f"split=2[cam][game];[cam]{cam}[camf];[game]{game}[gamef];[camf][gamef]vstack=inputs=2"


def _gameplay_blur_filter(plan: EditPlan) -> str:
    """No-webcam layout: the full gameplay (sharp, uncropped) sits in a middle band, with
    blurred crops of the same gameplay filling the bands above and below. The top blurred
    band shows the BOTTOM of the gameplay; the bottom blurred band shows the TOP."""
    W, H = plan.width, plan.height
    mid_h = (round(W * 9 / 16) // 2) * 2          # full 16:9 gameplay scaled to width (~608)
    top_h = ((H - mid_h) // 2 // 2) * 2           # even
    bot_h = H - mid_h - top_h
    # middle: fit the whole frame to width (no crop); pad only if the source isn't 16:9
    mid = (f"scale={W}:{mid_h}:force_original_aspect_ratio=decrease,"
           f"pad={W}:{mid_h}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    # top band: cover Wxh, keep the BOTTOM slice, blur
    top = (f"scale={W}:{top_h}:force_original_aspect_ratio=increase,"
           f"crop={W}:{top_h}:(in_w-{W})/2:(in_h-{top_h}),boxblur=28:2,setsar=1")
    # bottom band: cover Wxh, keep the TOP slice, blur
    bot = (f"scale={W}:{bot_h}:force_original_aspect_ratio=increase,"
           f"crop={W}:{bot_h}:(in_w-{W})/2:0,boxblur=28:2,setsar=1")
    return (f"split=3[gt][gm][gb];[gt]{top}[topb];[gm]{mid}[midb];[gb]{bot}[botb];"
            f"[topb][midb][botb]vstack=inputs=3,setsar=1")


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
    if needs_ass:
        captions_mod.build_ass(plan, transcript_path, ass_path)
        _stage_font(plan.captions.font)
        if plan.intro_hook.enabled and plan.intro_hook.text.strip():
            _stage_font(plan.intro_hook.font)   # hook may use a different font (Impact / Cyrillic)
        vf_parts.append(f"ass={ass_path.name}:fontsdir=.")
    vf = ",".join(vf_parts)

    dur = max(0.1, plan.end - plan.start)
    W, H = plan.width, plan.height

    # Sound-effect overlays: mix each onto the original audio at its t0 (only real files).
    sfx = [e for e in plan.effects
           if e.type == "sfx" and e.params.get("file") and Path(e.params["file"]).exists()]
    wm = plan.watermark
    wm_on = bool(wm.enabled and wm.image and Path(wm.image).exists())
    mus = plan.music
    mus_on = bool(mus.enabled and mus.file and Path(mus.file).exists())

    # ffmpeg runs with cwd=work (so the ass=<basename> path resolves), so the source
    # must be absolute — a relative VOD path would otherwise be looked for under work/.
    source = str(Path(plan.source).resolve())
    cmd = [ffmpeg_bin(), "-y", "-ss", f"{plan.start:.3f}", "-t", f"{dur:.3f}", "-i", source]
    for e in sfx:
        cmd += ["-i", str(e.params["file"])]
    wm_idx = 1 + len(sfx)
    if wm_on:
        cmd += ["-i", str(Path(wm.image).resolve())]
    mus_idx = 1 + len(sfx) + (1 if wm_on else 0)
    if mus_on:
        cmd += ["-i", str(Path(mus.file).resolve())]

    if sfx or wm_on or mus_on:
        # ffmpeg forbids -vf alongside -filter_complex, so the video chain lives in the graph.
        fc = []
        # ---- video chain (+ optional watermark overlay) ----
        if wm_on:
            ww = max(2, int(W * max(0.05, min(0.9, wm.scale))))
            op = max(0.0, min(1.0, wm.opacity))
            # centre the watermark over the GAMEPLAY region (below the facecam band if present)
            if plan.reframe.mode == "facecam_top" and plan.facecam.present:
                top_h = round(H * min(0.7, max(0.15, plan.facecam.band)))
                oy = f"{top_h}+(H-{top_h}-h)/2"
            else:
                oy = "(H-h)/2"
            fc.append(f"[0:v]{vf}[vbase]")
            fc.append(f"[{wm_idx}:v]scale={ww}:-1,format=rgba,colorchannelmixer=aa={op}[wm]")
            fc.append(f"[vbase][wm]overlay=(W-w)/2:{oy}[vout]")
        else:
            fc.append(f"[0:v]{vf}[vout]")

        # ---- audio chain: voice (+ ducked music bed) (+ sfx) ----
        mix: list[str] = []
        if mus_on:
            # split the voice: one copy to keep, one as the sidechain KEY that ducks the music
            fc.append("[0:a]asplit=2[amain][akey]")
            mvol = max(0.0, min(1.0, mus.volume))
            ratio = max(1.0, min(20.0, mus.duck_ratio))
            # music trimmed to clip length + lowered to a background level, then ducked under
            # his voice (loud voice -> music drops; returns when he's quiet again)
            fc.append(f"[{mus_idx}:a]atrim=0:{dur:.3f},asetpts=N/SR/TB,volume={mvol}[mus0]")
            fc.append(f"[mus0][akey]sidechaincompress=threshold=0.03:ratio={ratio}:"
                      f"attack=20:release=500[musd]")
            mix += ["[amain]", "[musd]"]
        else:
            mix.append("[0:a]")
        for i, e in enumerate(sfx, start=1):
            delay = int(max(0.0, e.t0) * 1000)
            vol = float(e.params.get("volume", 1.0))
            fc.append(f"[{i}:a]adelay={delay}|{delay},volume={vol}[s{i}]")
            mix.append(f"[s{i}]")

        if len(mix) == 1:
            amap = "0:a"                        # just the original voice — map the input stream
        else:
            # normalize=0 keeps the voice full under the bed; a limiter guards against clipping
            fc.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:"
                      f"duration=first:dropout_transition=0[amx]")
            fc.append("[amx]alimiter=limit=0.95[aout]")
            amap = "[aout]"
        cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", amap, "-r", str(plan.fps)]
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
