"""Tiny SQLite-backed store for jobs and clips (stdlib only)."""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Optional

from .config import Paths
from .models import Job, Clip

_lock = threading.Lock()

# Cooperative cancellation: a job_id in here means "stop ASAP". The pipeline checks this
# at stage boundaries (and inside the vision loop). Lives here so run.py and moments.py can
# both read it without an import cycle.
_CANCEL: set[str] = set()


def request_cancel(job_id: str) -> None:
    _CANCEL.add(job_id)


def clear_cancel(job_id: str) -> None:
    _CANCEL.discard(job_id)


def is_cancelled(job_id: str) -> bool:
    return job_id in _CANCEL


def delete_job(job_id: str) -> None:
    """Remove a job and all its clip rows from the DB (files are removed by the caller)."""
    with _lock, _conn() as c:
        c.execute("DELETE FROM clips WHERE job_id=?", (job_id,))
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(Paths.db, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS clips (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                data TEXT NOT NULL
            )"""
        )


def save_job(job: Job) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO jobs (id, data) VALUES (?, ?)",
            (job.id, job.model_dump_json()),
        )


def get_job(job_id: str) -> Optional[Job]:
    with _lock, _conn() as c:
        row = c.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
    return Job.model_validate_json(row["data"]) if row else None


def list_jobs() -> list[Job]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT data FROM jobs").fetchall()
    jobs = [Job.model_validate_json(r["data"]) for r in rows]
    return sorted(jobs, key=lambda j: j.created_at, reverse=True)


def save_clip(clip: Clip) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO clips (id, job_id, data) VALUES (?, ?, ?)",
            (clip.id, clip.job_id, clip.model_dump_json()),
        )


def get_clip(clip_id: str) -> Optional[Clip]:
    with _lock, _conn() as c:
        row = c.execute("SELECT data FROM clips WHERE id=?", (clip_id,)).fetchone()
    return Clip.model_validate_json(row["data"]) if row else None


def list_clips(job_id: Optional[str] = None) -> list[Clip]:
    with _lock, _conn() as c:
        if job_id:
            rows = c.execute("SELECT data FROM clips WHERE job_id=?", (job_id,)).fetchall()
        else:
            rows = c.execute("SELECT data FROM clips").fetchall()
    clips = [Clip.model_validate_json(r["data"]) for r in rows]
    return sorted(clips, key=lambda cl: cl.score, reverse=True)


init_db()
