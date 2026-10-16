"""
Registry of Gemini models this deployment is configured to use.

Reported by ``GET /api/providers`` so a misconfigured model id is visible from
the API. The ids mirror ``.env.example`` (``AI_TEXT_MODEL``, ``AI_VISION_MODEL``,
``GEMINI_MODEL``, ``REALTIME_MODEL``); the ``*-latest`` aliases track Google's
current model of that class, so they are the safest defaults.
"""

from __future__ import annotations

from typing import Dict

#: model id -> what it is used for.
GEMINI_MODELS: Dict[str, str] = {
    "gemini-flash-lite-latest": "text triage (fast, low cost)",
    "gemini-flash-latest": "text and image analysis",
    "gemini-pro-latest": "complex multimodal analysis",
    "gemini-3.5-flash": "text and image analysis",
    "gemini-3.8-live": "native-duplex live voice",
}
