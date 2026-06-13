"""Run a downloaded test VOD through the full pipeline so its clips show up in the
web UI. Useful for non-Russian test footage (e.g. a Renyan VOD) — pass the language.

    python run_demo.py data/vods/renyan_demo.mp4 en

Your own Russian streams just go through launch.bat normally (config language = ru).
"""
import sys
import time
import uuid

from backend.config import CONFIG
from backend import store
from backend.models import Job, JobStatus
from backend.pipeline.run import run_job


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "data/vods/renyan_demo.mp4"
    lang = sys.argv[2] if len(sys.argv) > 2 else "en"
    CONFIG["transcribe"]["language"] = lang  # in-process override for this run only

    job = Job(id="demo" + uuid.uuid4().hex[:6], source_type="local", source=path,
              status=JobStatus.queued, created_at=time.time())
    store.save_job(job)
    print(f"running job {job.id} on {path} (lang={lang}) ...")
    run_job(job.id)

    j = store.get_job(job.id)
    print(f"status: {j.status}" + (f" | error: {j.error}" if j.error else ""))
    clips = store.list_clips(job.id)
    print(f"{len(clips)} clips:")
    for c in clips:
        print(f"  [{c.start:.0f}-{c.end:.0f}s] {c.kind} score={c.score} rendered={bool(c.file_path)}")
        print(f"      {c.title}")


if __name__ == "__main__":
    main()
