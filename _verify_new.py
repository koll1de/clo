"""End-to-end test of the NEW approach on the 1080p VOD:
audio candidates -> VISION gate -> facecam render (captions off). Deleted after use."""
import json, time, uuid
from backend import store
from backend.config import CONFIG, Paths
from backend.models import Job, JobStatus, ClipStatus
from backend.editplan import default_plan
from backend.pipeline import audio, moments, facecam, render as render_stage

VOD = str(Paths.vods / "renyan_new.mp4")
job_id = "vnew" + uuid.uuid4().hex[:6]

# empty transcript (we're testing the vision-gated path without transcription)
tp = Paths.work / f"{job_id}.transcript.json"
tp.write_text(json.dumps({"segments": []}), encoding="utf-8")

job = Job(id=job_id, source_type="local", source=VOD, status=JobStatus.finding_moments,
          vod_path=VOD, transcript_path=str(tp), created_at=time.time())
store.save_job(job)

t0 = time.time()
reactions = audio.find_reactions(VOD, job_id)
clips = moments.apply_audio_signal(job_id, [], reactions, str(tp))
print(f"[audio] {len(reactions)} reactions -> {len(clips)} candidates ({time.time()-t0:.0f}s)")

t0 = time.time()
clips = moments.vision_verify(job_id, VOD, clips)
print(f"[vision] {len(clips)} clips kept ({time.time()-t0:.0f}s)")

det = facecam.detect_facecam(VOD)
edit_cfg = dict(CONFIG["edit"])
if det:
    edit_cfg["facecam"] = {**(edit_cfg.get("facecam") or {}), **det}
print(f"[facecam] {det}")

rendered = 0
for c in clips:
    try:
        plan = default_plan(VOD, c, edit_cfg)
        out = render_stage.render(plan, c.id, transcript_path=str(tp))
        c.file_path = str(out); c.edit_plan = plan.model_dump()
        store.save_clip(c); rendered += 1
        print(f"  {c.id} | {c.kind:16} {c.score:.2f} | {c.title!r} [{c.start:.0f}-{c.end:.0f}]")
    except Exception as e:
        print(f"  RENDER FAILED {c.id}: {e}")

job.status = JobStatus.ready
store.save_job(job)
print(f"\nDONE: {rendered} clips. Job = {job_id}")
