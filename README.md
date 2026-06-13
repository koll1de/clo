# Clipmaker.ai

Turns CS2 stream VODs into engaging vertical clips (YouTube Shorts + TikTok), automatically.
Runs **entirely locally** on your PC and GPU — no paid APIs.

## What it does

1. **Ingest** — drop a local VOD file, or paste a Twitch VOD URL (downloads video + chat).
2. **Transcribe** — Russian speech → text with word-level timestamps (faster-whisper on the GPU).
3. **Find moments** — combines four signals to find clip-worthy moments:
   - transcript read by a local LLM (funny interactions, jokes, talking to chat / tips),
   - your mic (laughter + excitement),
   - Twitch chat bursts / emote spikes,
   - kill-feed (aces, multi-kills, deagle head-shot strings, bot kills).
4. **Edit & render** — vertical 9:16 reframe, zoom-punch-ins, speed ramps, sound effects,
   kill-feed highlights, intro hook, the question-card overlay, optional captions (toggle + font picker).
5. **Review** — preview every candidate clip, approve/reject, or type a change request and the AI re-edits.
6. **Publish** — approved clips auto-upload to YouTube Shorts and drop into TikTok drafts.

## Status

Built in vertical slices. See the in-app progress / `config.yaml` for current settings.

## Setup (one time)

```
setup.bat
```

Installs ffmpeg + Ollama (if missing), creates the Python environment, and downloads models.

## Run

```
launch.bat
```

Opens the app in your browser at http://localhost:8000

## Layout

```
backend/            FastAPI app + pipeline
  pipeline/         ingest, transcribe, moments, edit, publish stages
  main.py           web server + API
  store.py          local SQLite job/clip storage
  models.py         data schemas
frontend/           browser UI (review gallery)
assets/             fonts, sound effects
data/               VODs, rendered clips, working files, app.db   (git-ignored)
config.yaml         all settings
```
