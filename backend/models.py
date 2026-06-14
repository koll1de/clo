"""Data schemas shared across the app."""
from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    ingesting = "ingesting"
    transcribing = "transcribing"
    finding_moments = "finding_moments"
    rendering = "rendering"
    ready = "ready"          # clips are in the review queue
    error = "error"
    cancelled = "cancelled"  # the user killed the job mid-run


class ClipStatus(str, Enum):
    pending = "pending"      # waiting for review
    approved = "approved"
    rejected = "rejected"
    published = "published"


class Job(BaseModel):
    id: str
    source_type: str         # "local" | "twitch"
    source: str              # file path or VOD url
    status: JobStatus = JobStatus.queued
    error: Optional[str] = None
    vod_path: Optional[str] = None
    duration: Optional[float] = None   # VOD length in seconds (probed at ingest)
    chat_path: Optional[str] = None
    transcript_path: Optional[str] = None
    created_at: float = 0.0


class Clip(BaseModel):
    id: str
    job_id: str
    start: float             # seconds into the VOD
    end: float
    kind: str                # funny_interaction | irl_interruption | big_reaction | ace | clutch | multikill_deagle | tips_to_chat
    score: float
    title: str = ""
    hook: str = ""           # short on-screen opener (from the vision pass)
    reason: str = ""         # why the AI thinks this is clip-worthy
    quote: str = ""          # the key spoken line (becomes the question-card text)
    question_username: str = ""              # chat user he's answering, if named
    question_highlights: list[str] = Field(default_factory=list)  # words to gold-highlight
    audio_peak: Optional[float] = None       # source-seconds of the loudest beat in the clip
    audio_level: float = 0.0                 # vocal-reaction loudness (x baseline); 0 = none detected
    music: str = ""                          # AI-chosen background mood: '', 'calm', or 'hype'
    layout: str = "facecam"                  # AI-chosen frame: 'facecam' or 'gameplay' (no cam)
    signals: list[str] = Field(default_factory=list)  # corroborating signals: audio, chat, killfeed
    status: ClipStatus = ClipStatus.pending
    file_path: Optional[str] = None
    edit_plan: Optional[dict] = None
    busy: bool = False          # true while re-rendering after a revise request
    last_request: str = ""      # the user's most recent re-edit request
    publishing: bool = False    # true while an upload is in flight
    publish_result: Optional[dict] = None  # per-platform upload results
