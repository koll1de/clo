"""Loads config.yaml and exposes app paths."""
from __future__ import annotations

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"

# Load a .env file (if present) before anything reads os.environ — this is how the
# Anthropic API key reaches llm.py: put ANTHROPIC_API_KEY=... in a .env at the repo
# root (git-ignored). Existing real env vars win over .env (override=False).
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed; rely on real env vars / secrets file instead


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = load_config()


def _data_dir() -> Path:
    d = ROOT / CONFIG.get("paths", {}).get("data_dir", "data")
    return d


class Paths:
    data = _data_dir()
    vods = data / "vods"       # downloaded / referenced source videos
    work = data / "work"       # intermediate files (audio, transcripts, frames)
    clips = data / "clips"     # rendered output clips
    db = data / "app.db"

    @classmethod
    def ensure(cls) -> None:
        for p in (cls.data, cls.vods, cls.work, cls.clips):
            p.mkdir(parents=True, exist_ok=True)


Paths.ensure()
