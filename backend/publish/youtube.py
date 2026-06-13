"""YouTube Shorts upload via the YouTube Data API v3.

One-time setup (see SETUP_PUBLISHING.md): create a Google Cloud project, enable the
YouTube Data API, make an OAuth "Desktop app" client, and drop client_secret.json into
the secrets/ folder. First upload opens a browser to authorize; the token is saved so
later uploads are silent.
"""
from __future__ import annotations

from pathlib import Path

from ..config import CONFIG, ROOT
from ..models import Clip

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _secrets_dir() -> Path:
    d = ROOT / CONFIG["publish"].get("secrets_dir", "secrets")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _client_secret_path() -> Path:
    return _secrets_dir() / "client_secret.json"


def _token_path() -> Path:
    return _secrets_dir() / "youtube_token.json"


def _credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = _token_path()
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    cs = _client_secret_path()
    if not cs.exists():
        raise FileNotFoundError(
            f"Missing {cs}. Follow SETUP_PUBLISHING.md to create a Google OAuth client."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(cs), SCOPES)
    creds = flow.run_local_server(port=0)  # opens a browser once to authorize
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def upload(clip: Clip) -> dict:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    if not clip.file_path or not Path(clip.file_path).exists():
        raise FileNotFoundError("clip has no rendered file to upload")

    ycfg = CONFIG["publish"]["youtube"]
    title = (clip.title or "CS2 clip").strip()[:90] + ycfg.get("title_suffix", " #Shorts")
    body = {
        "snippet": {
            "title": title,
            "description": ycfg.get("description", ""),
            "tags": ycfg.get("tags", []),
            "categoryId": str(ycfg.get("category_id", "20")),
        },
        "status": {
            "privacyStatus": ycfg.get("privacy", "private"),
            "selfDeclaredMadeForKids": False,
        },
    }

    service = build("youtube", "v3", credentials=_credentials())
    media = MediaFileUpload(clip.file_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()
    vid = response["id"]
    return {"video_id": vid, "url": f"https://youtube.com/shorts/{vid}"}
