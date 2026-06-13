# Clipmaker.ai — Handover & Context

Last updated: 2026-06-13. This is the single source of truth for picking up the project
in a new terminal / Claude Code session. Read this first.

---

## 1. What this is

A program the user runs **locally** that turns his **CS2 Twitch stream VODs** into engaging
**vertical clips** (YouTube Shorts + TikTok), in the editing style of creators like Renyan
(no facecam). Personal tool, not a SaaS.

**The user:** Russian-speaking Twitch CS2 streamer (Premier), few viewers yet — the whole
point is to grow via Shorts/TikTok. Has coding experience but "vibe-codes" and wants Claude
to do essentially all implementation. $0 budget → everything must be free and run locally.

**Machine:** Windows 11, RTX 3090 (24 GB), i7-13700K, 32 GB DDR5. Python 3.13.3.

---

## 2. The pipeline (end to end)

`backend/pipeline/run.py :: run_job(job_id)` runs the stages:

1. **ingest** (`pipeline/ingest.py`) — local file passthrough, or download a Twitch/YouTube
   URL via yt-dlp.
2. **transcribe** (`pipeline/transcribe.py`) — faster-whisper `large-v3` on the GPU, Russian,
   word timestamps → `data/work/<job>.transcript.json`.
3. **unload whisper** from VRAM (`transcribe.unload_model()`) so it doesn't fight the LLM.
4. **find moments** (`pipeline/moments.py`) — qwen3:30b (Ollama) reads the transcript in
   time-windowed chunks, returns structured JSON moments (funny_interaction, irl_interruption,
   tips_to_chat, big_reaction, story_banter). Scored by `config.yaml priority` weights, deduped.
5. **render** (`pipeline/render.py`) — for each candidate, build an `EditPlan` and ffmpeg-render
   a vertical 1080×1920 clip: reframe + Russian captions + intro hook → `data/clips/<id>.mp4`.
6. **hands-off mode** (optional) — auto-approve + publish, skipping review.
7. **ready** — clips sit in the review queue.

**Review + re-edit** (web UI): approve/reject each clip, or type a plain-language change
("меньше зума", "шрифт Impact", "обрежь первые 2 сек"). `pipeline/revise.py` turns that into an
`EditPlan` patch via the LLM and re-renders — no re-analysis.

**Publish** (`backend/publish/`): YouTube Shorts = real auto-upload; TikTok = push to drafts.

---

## 3. Architecture / file map

```
config.yaml                 ALL settings (models, priority weights, edit, publish)
launch.bat                  starts Ollama (if needed) + uvicorn, opens browser
setup.bat                   one-time: venv + pip install + ollama pull
run_demo.py                 process a test VOD with a language override (see §7)
backend/
  main.py                   FastAPI app + all API endpoints
  config.py                 loads config.yaml; Paths (data/vods, work, clips, app.db)
  models.py                 Job, Clip pydantic models + status enums
  store.py                  SQLite store (jobs, clips)
  ffmpeg.py                 resolves ffmpeg/ffprobe (NOT on PATH — see §6) + helpers
  cuda.py                   registers CUDA DLL dirs before whisper loads (see §6)
  llm.py                    Ollama client (structured JSON via `format` schema)
  editplan.py               EditPlan (parametric edit) + FONTS registry
  pipeline/
    run.py                  orchestrator
    ingest.py  transcribe.py  moments.py  render.py  captions.py  revise.py
  publish/
    __init__.py  youtube.py  tiktok.py
frontend/index.html         single-page review UI (vanilla JS, polls every 3s)
data/                       git-ignored: vods/, work/, clips/, app.db
secrets/                    git-ignored: client_secret.json, *_token.json
```

---

## 4. Status — what's DONE and TESTED

- ✅ Env: ffmpeg 8.1.1 + Ollama 0.30.6 installed; `.venv` with all deps.
- ✅ Models downloaded: faster-whisper `large-v3`, `qwen3:30b`.
- ✅ GPU transcription validated on the 3090 (float16).
- ✅ Moment brain tested: correctly found a "mom walks in" (irl_interruption) clip in a
  synthetic Russian transcript and wrote a Russian title itself.
- ✅ Render tested: produces real 1080×1920 mp4 with Russian (Cyrillic) captions + intro hook.
- ✅ Review UI + approve/reject + plain-text re-edit tested (font change + trim applied & re-rendered).
- ✅ Publishing coded + degrades gracefully when nothing configured (YouTube needs user's
  Google OAuth per SETUP_PUBLISHING.md; TikTok needs a dev app).
- ✅ Full real-footage run: a 6-min Renyan VOD section (YouTube) ran clean end-to-end.
  Found **0 clips** — correct, because that segment is competitive callouts, not banter, and the
  only moment signal so far is the transcript brain. This proves plumbing works AND that the
  kill-feed detector is the key missing piece for pure gameplay highlights.
- ✅ On GitHub: `github.com/koll1de/clo`, branch `main`.

---

## 5. Status — what's NOT built (Phase 2, the roadmap)

Priority order:

1. **Kill-feed detection** — the big one for CS. Detect aces / clutches / multi-kill deagle
   strings / bot kills from the top-right kill-feed (OCR or template-match weapon icons).
   The `ace`/`clutch`/`multikill_deagle` kinds + priority weights already exist; the detector
   doesn't. **Best tuned on the user's own full-res footage** (matches his HUD/resolution).
2. **Audio signals** — laughter + excitement/loudness spikes to corroborate/add moments.
3. **Chat signals** — message-velocity + emote spikes. Requires downloading the Twitch VOD
   **chat** in ingest (not done yet; `Job.chat_path` exists but is unused).
4. **Edit effects** — zoom punch-ins, speed ramps, sound effects, and the **visual
   question-card overlay** (red username tag + bold uppercase question with gold highlights;
   reference image described in memory `clip-editing-style`). `EditPlan.effects` and
   `EditPlan.question_card` hold the data; the ffmpeg rendering of them isn't written.
5. **Batched transcription** — faster-whisper `BatchedInferencePipeline` for multi-hour VODs.
6. **Font bundling** — currently uses Cyrillic-capable Windows system fonts (Segoe UI Black
   default). Could bundle nicer fonts (must have Cyrillic glyphs — Anton/Impact-style Latin-only
   fonts won't render Russian).
7. **TikTok auth helper** + real public-post path (needs TikTok app audit).

---

## 6. Critical gotchas (HARD-WON — don't re-discover these)

- **ffmpeg is NOT on PATH.** Installed via winget to
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*/.../bin`. `backend/ffmpeg.py`
  auto-resolves it (PATH → winget glob → `CLIPMAKER_FFMPEG` env override). Always call
  `ffmpeg_bin()`/`ffprobe_bin()`, never bare `"ffmpeg"`.
- **CUDA DLLs.** faster-whisper/ctranslate2 can't find `cublas64_12.dll`/`cudnn` because the
  pip `nvidia-*-cu12` wheels put them in site-packages. Call `backend.cuda.enable()` **before**
  importing/using faster_whisper (transcribe.py already does this). Symptom if missing:
  `Library cublas64_12.dll is not found`.
- **ffmpeg ass-subtitle font path.** The `subtitles/ass` filter uses `:` as an option separator,
  so a Windows path like `C:/Windows/Fonts` breaks the parser. Solution in render.py: copy the
  chosen font file into `data/work` and run ffmpeg with `cwd=work` + `fontsdir=.` (no colon).
- **Windows console can't print Cyrillic** (cp1252 → UnicodeEncodeError). For any script that
  prints Russian, prefix with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. (The app itself is fine —
  it stores UTF-8 JSON and serves the web UI.)
- **YouTube bot-gate.** yt-dlp needs `--extractor-args "youtube:player_client=tv_embedded"` to
  download without login (browser-cookie extraction is blocked by Chromium app-bound encryption).
  Caveat: tv_embedded only serves up to **360p**. ingest.py adds this automatically for YouTube
  URLs. Twitch VODs don't have this problem. Keep yt-dlp fresh (`pip install -U yt-dlp`).
- **VRAM.** whisper large-v3 (~3 GB) + qwen3:30b (~19 GB) ≈ near 24 GB. Pipeline unloads whisper
  before the LLM stage. Don't load both at once. Render uses CPU (libx264), no GPU contention.
- **Ollama server** must be running (`localhost:11434`). launch.bat starts it; it also auto-starts
  at login. `llm.is_up()` / `llm.has_model()` check it.

---

## 7. How to run / test

**Run the app:** double-click `launch.bat` → http://localhost:8000. Create a job (local file
path or Twitch URL), watch status, review clips when ready.

**Run a non-Russian test VOD** (e.g. Renyan) so it shows in the UI:
```
.venv\Scripts\python.exe run_demo.py data/vods/renyan_demo.mp4 en
```
(`en` overrides the transcribe language for that run only; real Russian streams use config `ru`.)

**Download a YouTube test section** (the channel is `more renyan`):
```
.venv\Scripts\yt-dlp.exe --extractor-args "youtube:player_client=tv_embedded" \
  --ffmpeg-location <ffmpeg bin dir> --download-sections "*600-960" \
  -f "best[height<=1080]/best" -o "data/vods/renyan_demo.%(ext)s" <youtube_url>
```

**Smoke-test a single stage** (examples are in the git history of this session): import
`backend.*` from the venv python; `PYTHONIOENCODING=utf-8` if printing Russian.

**Reset all data:** delete `data/` (vods, clips, work, app.db). Recreated on next run.

---

## 8. Key decisions & rationale

- **Python, not Rust** — every heavy part (whisper, ffmpeg, Ollama, OpenCV) is already native;
  our code is just glue (<1% of runtime). Python = same speed where it matters, 5× faster to build.
- **qwen3:30b** (MoE, 256K ctx) for the brain — beats Gemma 3 on multilingual/Russian, fast (only
  ~3B active), fits the 3090. Swappable in one line (`config.yaml llm.model`).
- **Edits as a parametric `EditPlan`** (data, not baked pixels) — this is what makes the user's
  "tell the AI what to change" re-edit feature work without re-analysis.
- **Moment priority** (config): funny_interaction > irl_interruption (scream→parents, "viral
  gold" per the user) > big_reaction > ace > clutch > multikill_deagle. A single flick is NOT
  worth clipping; a 3–4 headshot deagle string IS.
- **Publishing:** YouTube Shorts = true auto-upload; TikTok = drafts (full auto needs app audit);
  no Instagram (wrong audience for CS). Uploads default to **private** for safety.

---

## 9. Immediate next steps (suggested)

1. **User streams** → keeps the Twitch VOD (enable *Store past broadcasts*) → gives the VOD URL.
   That is the correct footage to build/tune **kill-feed detection** and the **reframe** against.
2. Build **kill-feed detection** (Phase 2 #1) — prototype on a frame grab, then tune on his HUD.
3. Add **chat download** to ingest + the **chat-spike** signal.
4. Build the **edit effects** (zoom punch-ins, SFX, question-card overlay) and tune on real clips.
5. When ready to publish: follow `SETUP_PUBLISHING.md` (YouTube Google Cloud OAuth, 5 min).

See also the auto-memory at `~/.claude/projects/.../memory/` (project, editing-style, machine,
user-profile) for durable context.
