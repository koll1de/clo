"""Thin client for the local Ollama LLM.

Uses Ollama's structured-output support: we pass a JSON schema as `format` and get
back schema-valid JSON, which removes brittle text parsing. qwen3's reasoning mode
is turned off for extraction so responses are fast and clean.
"""
from __future__ import annotations

import json
import requests

from .config import CONFIG

_cfg = CONFIG["llm"]
_HOST = _cfg["host"].rstrip("/")


class OllamaError(RuntimeError):
    pass


def is_up() -> bool:
    try:
        requests.get(f"{_HOST}/api/version", timeout=3).raise_for_status()
        return True
    except Exception:
        return False


def has_model(model: str | None = None) -> bool:
    model = model or _cfg["model"]
    try:
        r = requests.get(f"{_HOST}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
        # match with or without the :latest style tag
        return any(n == model or n.split(":")[0] == model.split(":")[0] for n in names)
    except Exception:
        return False


def chat_json(system: str, user: str, schema: dict, *, temperature: float = 0.4) -> dict:
    """Send a chat request constrained to `schema` and return parsed JSON."""
    payload = {
        "model": _cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "format": schema,
        "stream": False,
        "think": _cfg.get("think", False),
        "options": {
            "num_ctx": _cfg.get("num_ctx", 16384),
            "temperature": temperature,
        },
    }
    try:
        r = requests.post(f"{_HOST}/api/chat", json=payload, timeout=1200)
        r.raise_for_status()
    except requests.RequestException as e:
        raise OllamaError(f"Ollama request failed: {e}") from e

    content = r.json().get("message", {}).get("content", "").strip()
    if not content:
        raise OllamaError("Ollama returned an empty response")
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise OllamaError(f"Ollama returned non-JSON: {content[:500]}") from e
