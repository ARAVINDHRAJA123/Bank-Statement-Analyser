"""
Tiny LLM provider selector for the ai/ features.

Pick the provider from whichever API key is present, so the same code runs on
either a paid Claude key or a free Google AI Studio (Gemini) key:

    ANTHROPIC_API_KEY  -> Claude   (claude-opus-4-8)        — pay-per-use
    GEMINI_API_KEY     -> Gemini   (gemini-2.5-flash)       — free tier, no card
    (or GOOGLE_API_KEY)

Get a free Gemini key at https://aistudio.google.com/app/apikey
Model names are overridable via ANTHROPIC_MODEL / GEMINI_MODEL.
"""
from __future__ import annotations

import os

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def get_provider() -> str | None:
    """Return 'anthropic', 'gemini', or None based on which key is set.
    Anthropic wins if both are present."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if gemini_api_key():
        return "gemini"
    return None


NO_KEY_MESSAGE = (
    "No LLM key found. Set ANTHROPIC_API_KEY (Claude) or GEMINI_API_KEY "
    "(free Gemini — get one at https://aistudio.google.com/app/apikey)."
)
