"""Thin client for the LLM backend.

Two providers, chosen independently per call site in config.yaml:
  - ollama    : local models on the 3090 (qwen3 / qwen2.5vl). Free, fully offline.
  - anthropic : Claude via the API (e.g. Opus 4.8). Costs money, but far better
                judgment on "is this moment actually clipworthy".

Both return schema-valid JSON, so the rest of the pipeline never knows or cares
which one produced it. The transcript brain (chat_json) reads config `llm.provider`;
the vision gate (chat_vision) reads config `signals.vision.provider` — so you can,
for example, keep transcript work local and only spend on the vision gate.
"""
from __future__ import annotations

import copy
import json
import os

import requests

from .config import CONFIG, ROOT

_cfg = CONFIG["llm"]
_HOST = _cfg["host"].rstrip("/")


class LLMError(RuntimeError):
    pass


# Back-compat: existing call sites catch llm.OllamaError.
OllamaError = LLMError


# --------------------------------------------------------------------------- #
# Ollama (local) helpers
# --------------------------------------------------------------------------- #
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


def _ollama_chat(payload: dict, *, timeout: int) -> dict:
    try:
        r = requests.post(f"{_HOST}/api/chat", json=payload, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        raise LLMError(f"Ollama request failed: {e}") from e
    content = r.json().get("message", {}).get("content", "").strip()
    if not content:
        raise LLMError("Ollama returned an empty response")
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise LLMError(f"Ollama returned non-JSON: {content[:500]}") from e


# --------------------------------------------------------------------------- #
# Anthropic (cloud) helpers
# --------------------------------------------------------------------------- #
_anthropic_client = None


def _anthropic():
    """Lazily build (and cache) an Anthropic client. Key resolution order:
    ANTHROPIC_API_KEY env var, then secrets/anthropic_api_key.txt (git-ignored)."""
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    try:
        import anthropic
    except ImportError as e:
        raise LLMError(
            "provider 'anthropic' needs the anthropic package — run: pip install anthropic"
        ) from e

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        secrets_dir = CONFIG.get("publish", {}).get("secrets_dir", "secrets")
        key_file = ROOT / secrets_dir / "anthropic_api_key.txt"
        if key_file.exists():
            key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        raise LLMError(
            "No Anthropic API key found. Set the ANTHROPIC_API_KEY environment variable, "
            "or save the key in secrets/anthropic_api_key.txt."
        )
    _anthropic_client = anthropic.Anthropic(api_key=key)
    return _anthropic_client


def _strict_schema(schema: dict) -> dict:
    """Anthropic structured outputs require additionalProperties:false on every object.
    Return a deep copy with that added, so the shared Ollama schemas stay untouched."""
    s = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "additionalProperties" not in node:
                node["additionalProperties"] = False
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(s)
    return s


def _anthropic_json(system: str, content, schema: dict, *, model: str,
                    max_tokens: int = 16000) -> dict:
    """One constrained call to Claude. `content` is either a user string or a list of
    content blocks (for vision). Returns schema-valid parsed JSON."""
    client = _anthropic()
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": _strict_schema(schema)}},
        )
    except Exception as e:                       # SDK / network / API errors
        raise LLMError(f"Anthropic request failed: {e}") from e

    if getattr(resp, "stop_reason", None) == "refusal":
        raise LLMError("Anthropic declined the request (safety refusal)")
    text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
    if not text:
        raise LLMError("Anthropic returned an empty response")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"Anthropic returned non-JSON: {text[:500]}") from e


# --------------------------------------------------------------------------- #
# Public API — provider-agnostic
# --------------------------------------------------------------------------- #
def chat_vision(system: str, user: str, images_b64: list[str], schema: dict,
                *, model: str | None = None, temperature: float = 0.2,
                num_ctx: int = 16384) -> dict:
    """Send images + a prompt to a vision model and return JSON constrained to `schema`.
    Images are base64-encoded JPEG (no data: prefix). Provider is `signals.vision.provider`."""
    vcfg = CONFIG.get("signals", {}).get("vision", {})
    if vcfg.get("provider", "ollama") == "anthropic":
        content = [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}
            for b in images_b64
        ]
        content.append({"type": "text", "text": user})
        return _anthropic_json(
            system, content, schema,
            model=vcfg.get("anthropic_model", "claude-opus-4-8"),
            max_tokens=4000,
        )

    payload = {
        "model": model or vcfg.get("model", "qwen2.5vl:7b"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user, "images": images_b64},
        ],
        "format": schema,
        "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": temperature},
    }
    return _ollama_chat(payload, timeout=600)


def chat_json(system: str, user: str, schema: dict, *, temperature: float = 0.4) -> dict:
    """Send a chat request constrained to `schema` and return parsed JSON.
    Provider is `llm.provider`."""
    if _cfg.get("provider", "ollama") == "anthropic":
        acfg = _cfg.get("anthropic", {})
        return _anthropic_json(
            system, user, schema,
            model=acfg.get("model", "claude-opus-4-8"),
        )

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
    return _ollama_chat(payload, timeout=1200)
