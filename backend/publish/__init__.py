"""Publishing — push approved clips out to platforms.

YouTube Shorts is a real auto-upload. TikTok pushes to your drafts (full public
auto-posting needs TikTok to audit the app — see SETUP_PUBLISHING.md). Nothing is
published unless you enable a platform in config.yaml and complete its one-time auth.
"""
from __future__ import annotations

from ..config import CONFIG
from ..models import Clip, ClipStatus
from . import youtube, tiktok


def publish_clip(clip: Clip) -> dict:
    """Publish a clip to every enabled platform. Returns per-platform results."""
    pcfg = CONFIG["publish"]
    results: dict[str, dict] = {}

    if pcfg.get("youtube", {}).get("enabled"):
        try:
            results["youtube"] = {"ok": True, **youtube.upload(clip)}
        except Exception as e:
            results["youtube"] = {"ok": False, "error": str(e)}

    if pcfg.get("tiktok", {}).get("enabled"):
        try:
            results["tiktok"] = {"ok": True, **tiktok.upload(clip)}
        except Exception as e:
            results["tiktok"] = {"ok": False, "error": str(e)}

    if not results:
        results["none"] = {"ok": False, "error": "No publishing platform is enabled in config.yaml"}

    return results


def any_success(results: dict) -> bool:
    return any(r.get("ok") for r in results.values())
