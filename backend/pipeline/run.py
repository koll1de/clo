"""Pipeline orchestrator — runs a job through every stage, updating status as it goes.

ingest -> transcribe -> find moments (LLM) -> render each candidate clip -> ready.
Audio/chat/kill-feed signals merge into the moments stage as they come online.
"""
from __future__ import annotations

import traceback

from .. import store
from ..config import CONFIG
from ..editplan import default_plan
from ..models import JobStatus, ClipStatus
from . import ingest as ingest_stage
from . import transcribe as transcribe_stage
from . import moments as moments_stage
from . import render as render_stage
from . import audio as audio_stage
from . import chat as chat_stage


def _auto_publish(clips: list) -> None:
    """Approve every clip and publish to enabled platforms (hands-off mode)."""
    from ..publish import publish_clip, any_success
    pcfg = CONFIG["publish"]
    platforms_on = pcfg.get("youtube", {}).get("enabled") or pcfg.get("tiktok", {}).get("enabled")
    for c in clips:
        c.status = ClipStatus.approved
        if platforms_on:
            try:
                res = publish_clip(c)
                c.publish_result = res
                if any_success(res):
                    c.status = ClipStatus.published
            except Exception as e:
                c.publish_result = {"error": {"ok": False, "error": str(e)}}
        store.save_clip(c)


def run_job(job_id: str) -> None:
    job = store.get_job(job_id)
    if job is None:
        return
    try:
        # 1) ingest
        job.status = JobStatus.ingesting
        store.save_job(job)
        job = ingest_stage.ingest(job)
        store.save_job(job)

        # 2) transcribe (GPU)
        job.status = JobStatus.transcribing
        store.save_job(job)
        job = transcribe_stage.transcribe(job)
        store.save_job(job)

        # 3) find moments (LLM). Free whisper from VRAM first so it doesn't fight qwen.
        transcribe_stage.unload_model()
        job.status = JobStatus.finding_moments
        store.save_job(job)
        clips = moments_stage.find_transcript_moments(job_id, job.transcript_path)
        # audio signal: corroborate moments + surface loud reactions the LLM missed
        if CONFIG.get("signals", {}).get("audio", {}).get("enabled", True):
            try:
                reactions = audio_stage.find_reactions(job.vod_path, job_id)
                clips = moments_stage.apply_audio_signal(
                    job_id, clips, reactions, job.transcript_path)
            except Exception as e:  # never let a signal kill the run
                print(f"[audio] signal failed: {e}")
        # chat signal: message-velocity + emote bursts (Twitch VODs with chat only)
        if job.chat_path and CONFIG.get("signals", {}).get("chat", {}).get("enabled", True):
            try:
                bursts = chat_stage.find_bursts(chat_stage.load_chat(job.chat_path))
                clips = moments_stage.apply_chat_signal(
                    job_id, clips, bursts, job.transcript_path)
            except Exception as e:
                print(f"[chat] signal failed: {e}")
        for c in clips:
            store.save_clip(c)

        # 4) render each candidate into a reviewable vertical clip
        job.status = JobStatus.rendering
        store.save_job(job)
        for c in clips:
            try:
                plan = default_plan(job.vod_path, c, CONFIG["edit"])
                out = render_stage.render(plan, c.id, transcript_path=job.transcript_path)
                c.file_path = str(out)
                c.edit_plan = plan.model_dump()
                store.save_clip(c)
            except Exception as e:  # a single clip failing shouldn't kill the batch
                print(f"[render] clip {c.id} failed: {e}")

        # 5) hands-off mode: auto-approve and publish, skipping the review queue
        if CONFIG.get("review", {}).get("hands_off"):
            _auto_publish(clips)

        # 6) done — clips are in the review queue
        job.status = JobStatus.ready
        store.save_job(job)
    except Exception as e:
        job = store.get_job(job_id) or job
        job.status = JobStatus.error
        job.error = f"{e}\n{traceback.format_exc()[-1500:]}"
        store.save_job(job)
