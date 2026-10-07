"""Lightweight AI-backend reachability probe — NOT the full AIProvider path.

Used only to stamp OodaDecision.ai_available at write time: a quick,
short-timeout check of whether something is listening at AI_BASE_URL, not a
real capability or auth check. Never raises — any failure (timeout,
connection refused, LLM_ENABLED unset/false, AI_BASE_URL unset) just means
"not available" for recording purposes, same graceful-degradation contract
as desk.fetch in the CISO demo: the core recording layer must never block
or error because an optional AI backend is offline.
"""

import os

import httpx

_PROBE_TIMEOUT_SECONDS = 1.5  # short on purpose — must never make a player's click feel slow


def ai_is_available() -> bool:
    if os.getenv("LLM_ENABLED", "false").lower() != "true":
        return False

    provider = os.getenv("AI_PROVIDER", "openai").lower()
    base_url = os.getenv("AI_BASE_URL")
    if provider == "openai" and not base_url:
        base_url = "https://api.openai.com/v1"
    if not base_url:
        return False

    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/models", timeout=_PROBE_TIMEOUT_SECONDS)
        return resp.status_code < 500
    except Exception:
        return False
