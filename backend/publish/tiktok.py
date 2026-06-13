"""TikTok upload via the Content Posting API (draft / inbox flow).

Until a TikTok developer app passes audit, videos can only be sent to the user's
TikTok inbox as a draft (you tap Post in the app). This module does exactly that
given a valid user access token in secrets/tiktok_token.json. See SETUP_PUBLISHING.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from ..config import CONFIG, ROOT
from ..models import Clip

INBOX_INIT = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"


def _token_path() -> Path:
    return ROOT / CONFIG["publish"].get("secrets_dir", "secrets") / "tiktok_token.json"


def _access_token() -> str:
    p = _token_path()
    if not p.exists():
        raise FileNotFoundError(
            f"Missing {p}. Follow SETUP_PUBLISHING.md to connect your TikTok account."
        )
    data = json.loads(p.read_text(encoding="utf-8"))
    token = data.get("access_token")
    if not token:
        raise ValueError("tiktok_token.json has no access_token")
    return token


def upload(clip: Clip) -> dict:
    if not clip.file_path or not Path(clip.file_path).exists():
        raise FileNotFoundError("clip has no rendered file to upload")
    token = _access_token()
    size = os.path.getsize(clip.file_path)

    # 1) init an inbox (draft) upload — single chunk
    init = requests.post(
        INBOX_INIT,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": size,
                "total_chunk_count": 1,
            }
        },
        timeout=60,
    )
    init.raise_for_status()
    payload = init.json()
    upload_url = payload["data"]["upload_url"]

    # 2) PUT the file bytes to the provided upload URL
    with open(clip.file_path, "rb") as f:
        put = requests.put(
            upload_url,
            headers={
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes 0-{size - 1}/{size}",
            },
            data=f,
            timeout=600,
        )
    put.raise_for_status()
    return {"publish_id": payload["data"].get("publish_id"), "status": "sent_to_drafts"}
