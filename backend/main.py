"""Clipmaker.ai web app — local FastAPI server + browser UI."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import store
from .config import CONFIG, Paths
from .models import Job, JobStatus, ClipStatus
from .pipeline.run import run_job

app = FastAPI(title="Clipmaker.ai")

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


@app.middleware("http")
async def _no_cache_frontend(request, call_next):
    """The UI is JSX transpiled in-browser; StaticFiles sends no Cache-Control, so browsers
    keep serving a STALE theme.jsx/dirB.jsx after a code change (e.g. clicks wired to the new
    handler do nothing). Force the frontend to always load fresh."""
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith(".jsx") or p.endswith(".html") or p.endswith(".css"):
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


class CreateJob(BaseModel):
    source_type: str   # "local" | "twitch"
    source: str


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "config": {"language": CONFIG["transcribe"]["language"]}}


@app.post("/api/jobs")
def create_job(body: CreateJob, bg: BackgroundTasks) -> Job:
    if body.source_type not in ("local", "twitch"):
        raise HTTPException(400, "source_type must be 'local' or 'twitch'")
    job = Job(
        id=uuid.uuid4().hex[:12],
        source_type=body.source_type,
        source=body.source.strip().strip('"'),
        status=JobStatus.queued,
        created_at=time.time(),
    )
    store.save_job(job)
    bg.add_task(run_job, job.id)
    return job


@app.get("/api/jobs")
def get_jobs() -> list[Job]:
    return store.list_jobs()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> Job:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.get("/api/jobs/{job_id}/clips")
def get_job_clips(job_id: str) -> list:
    return store.list_clips(job_id)


def _safe_unlink(p) -> None:
    if not p:
        return
    try:
        Path(p).unlink(missing_ok=True)
    except Exception:
        pass


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Stop a running/queued job. Kills any live subprocess (download/ffmpeg) at once, and
    marks the job cancelled immediately — so a STALE job whose process died (e.g. a crash or
    server restart left it stuck 'ingesting') is freed too, not just a live one."""
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    store.request_cancel(job_id)   # kill a live subprocess + flag the run loops to bail
    terminal = (JobStatus.ready, JobStatus.error, JobStatus.cancelled)
    if job.status not in terminal:
        # A live run also lands on 'cancelled' at its next checkpoint; setting it here gives
        # instant UI feedback and frees a stuck job that has no process left to stop.
        job.status = JobStatus.cancelled
        job.error = None
        store.save_job(job)
    else:
        store.clear_cancel(job_id)  # nothing actually running to stop
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    """Delete a job fully — its clips, work files, and the VOD — even when finished. Also
    cancels it first if it's mid-run. The VOD is removed only if no other job still uses it,
    and only when it lives inside the app's data dir (never an outside file the user picked)."""
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    store.request_cancel(job_id)  # stop any in-flight processing before we remove its files

    for c in store.list_clips(job_id):
        _safe_unlink(c.file_path)
        _safe_unlink(Paths.work / f"{c.id}.ass")
    _safe_unlink(job.transcript_path)
    _safe_unlink(job.chat_path)
    _safe_unlink(Paths.work / f"{job.id}.wav")
    _safe_unlink(Paths.work / f"{job.id}.chat.json")

    # the VOD: only delete it if it's inside data/ AND no other job references it
    others = [o for o in store.list_jobs() if o.id != job_id]
    for vod in {job.vod_path, job.source}:
        if not vod:
            continue
        try:
            vp = Path(vod).resolve()
        except Exception:
            continue
        if Paths.data.resolve() not in vp.parents or not vp.exists():
            continue
        shared = any(o.vod_path == vod or o.source == vod for o in others)
        if not shared:
            _safe_unlink(vp)

    store.delete_job(job_id)
    store.clear_cancel(job_id)
    return {"ok": True}


@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: str):
    clip = store.get_clip(clip_id)
    if not clip:
        raise HTTPException(404, "clip not found")
    return clip


def _platforms_enabled() -> bool:
    p = CONFIG["publish"]
    return bool(p.get("youtube", {}).get("enabled") or p.get("tiktok", {}).get("enabled"))


def _do_publish(clip_id: str) -> None:
    from .publish import publish_clip, any_success
    clip = store.get_clip(clip_id)
    if not clip:
        return
    try:
        results = publish_clip(clip)
    except Exception as e:
        results = {"error": {"ok": False, "error": str(e)}}
    clip = store.get_clip(clip_id) or clip
    clip.publish_result = results
    clip.publishing = False
    if any_success(results):
        clip.status = ClipStatus.published
    store.save_clip(clip)


@app.post("/api/clips/{clip_id}/approve")
def approve_clip(clip_id: str, bg: BackgroundTasks):
    clip = store.get_clip(clip_id)
    if not clip:
        raise HTTPException(404, "clip not found")
    clip.status = ClipStatus.approved
    # Approve -> the AI publishes (if enabled). Privacy defaults to 'private' for safety.
    if CONFIG["publish"].get("auto_on_approve") and _platforms_enabled():
        clip.publishing = True
        store.save_clip(clip)
        bg.add_task(_do_publish, clip_id)
    else:
        store.save_clip(clip)
    return clip


@app.post("/api/clips/{clip_id}/publish")
def publish_clip_endpoint(clip_id: str, bg: BackgroundTasks):
    clip = store.get_clip(clip_id)
    if not clip:
        raise HTTPException(404, "clip not found")
    if not _platforms_enabled():
        raise HTTPException(400, "No publishing platform enabled in config.yaml")
    clip.publishing = True
    store.save_clip(clip)
    bg.add_task(_do_publish, clip_id)
    return clip


@app.post("/api/clips/{clip_id}/reject")
def reject_clip(clip_id: str):
    clip = store.get_clip(clip_id)
    if not clip:
        raise HTTPException(404, "clip not found")
    clip.status = ClipStatus.rejected
    store.save_clip(clip)
    return clip


class ReviseBody(BaseModel):
    request: str


def _do_revise(clip_id: str, request_text: str) -> None:
    from .pipeline.revise import revise_clip
    clip = store.get_clip(clip_id)
    if not clip:
        return
    try:
        revise_clip(clip, request_text)
    except Exception as e:
        print(f"[revise] clip {clip_id} failed: {e}")
    finally:
        c = store.get_clip(clip_id)
        if c:
            c.busy = False
            store.save_clip(c)


@app.post("/api/clips/{clip_id}/revise")
def revise_clip_endpoint(clip_id: str, body: ReviseBody, bg: BackgroundTasks):
    clip = store.get_clip(clip_id)
    if not clip:
        raise HTTPException(404, "clip not found")
    if not body.request.strip():
        raise HTTPException(400, "empty request")
    clip.busy = True
    clip.last_request = body.request.strip()
    store.save_clip(clip)
    bg.add_task(_do_revise, clip_id, body.request.strip())
    return clip


# --- static frontend ---
app.mount("/clips", StaticFiles(directory=str(Paths.clips)), name="clips")


@app.get("/")
def index() -> FileResponse:
    # no-store so the browser always loads the latest UI (no more stale cached index.html)
    return FileResponse(str(FRONTEND / "index.html"),
                        headers={"Cache-Control": "no-store, must-revalidate"})


app.mount("/", StaticFiles(directory=str(FRONTEND)), name="frontend")
