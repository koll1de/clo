"""Stage 2 — transcribe the VOD audio (Russian) on the GPU with faster-whisper.

Produces a transcript JSON with segments and word-level timestamps, which later
stages use both for caption rendering and for finding spoken/funny moments.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import CONFIG, Paths
from ..ffmpeg import extract_audio
from ..models import Job

_model = None  # lazily loaded, kept warm between jobs


def _get_model():
    global _model
    if _model is None:
        from .. import cuda
        cuda.enable()  # register CUDA DLL dirs before loading the model
        from faster_whisper import WhisperModel
        cfg = CONFIG["transcribe"]
        _model = WhisperModel(
            cfg["model"], device=cfg["device"], compute_type=cfg["compute_type"]
        )
    return _model


def unload_model() -> None:
    """Free the whisper model from VRAM (called before the LLM stage so they don't
    both sit in the 24 GB at once)."""
    global _model
    if _model is not None:
        del _model
        _model = None
        import gc
        gc.collect()


def transcribe(job: Job) -> Job:
    assert job.vod_path, "ingest must run before transcribe"
    work_audio = Paths.work / f"{job.id}.wav"
    extract_audio(job.vod_path, work_audio)

    cfg = CONFIG["transcribe"]
    model = _get_model()
    # language: a fixed code (e.g. "ru") forces that language; "auto"/""/None lets whisper
    # detect it from the audio. Detection is what makes an English VOD produce an English
    # transcript (and therefore English titles) while a Russian VOD stays Russian.
    lang_cfg = (cfg.get("language") or "").strip().lower()
    language = None if lang_cfg in ("", "auto", "detect") else lang_cfg
    # Batched inference is much faster on long VODs (multi-hour streams). It needs
    # spare VRAM for the larger batch; whisper still unloads before the LLM stage.
    if cfg.get("batched"):
        from faster_whisper import BatchedInferencePipeline
        pipeline = BatchedInferencePipeline(model=model)
        segments, info = pipeline.transcribe(
            str(work_audio),
            language=language,
            word_timestamps=True,
            vad_filter=True,
            batch_size=int(cfg.get("batch_size", 16)),
        )
    else:
        segments, info = model.transcribe(
            str(work_audio),
            language=language,
            word_timestamps=True,
            vad_filter=True,
        )
    print(f"[transcribe] language={info.language} (config: {lang_cfg or 'auto'})")

    out = {
        "language": info.language,
        "duration": info.duration,
        "segments": [],
    }
    for seg in segments:
        out["segments"].append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "words": [
                {"start": w.start, "end": w.end, "word": w.word}
                for w in (seg.words or [])
            ],
        })

    transcript_path = Paths.work / f"{job.id}.transcript.json"
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    job.transcript_path = str(transcript_path)
    return job
