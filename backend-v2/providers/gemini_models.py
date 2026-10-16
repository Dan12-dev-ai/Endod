"""
Registry of Gemini models this deployment is configured to use.

Reported by ``GET /api/providers`` so a misconfigured model id is visible from
the API. The ids mirror ``.env.example`` (``AI_TEXT_MODEL``, ``AI_VISION_MODEL``,
``GEMINI_MODEL``, ``REALTIME_MODEL``); the ``*-latest`` aliases track Google's
current model of that class, so they are the safest defaults.
"""

from __future__ import annotations

import os
from typing import Dict

#: model id -> what it is used for.
GEMINI_MODELS: Dict[str, str] = {
    "gemini-flash-lite-latest": "text triage (fast, low cost)",
    "gemini-flash-latest": "text and image analysis",
    "gemini-pro-latest": "complex multimodal analysis",
    "gemini-3.5-flash": "text and image analysis",
    "gemini-3.8-live": "native-duplex live voice",
}


def configured_gemini_models() -> Dict[str, str]:
    """``GEMINI_MODELS`` plus every model id this deployment is configured to use.

    A configured id that is not in the registry is still reported, so
    ``/api/providers`` never omits the model a deployment actually calls.
    """
    from app.core.config import get_settings

    models = dict(GEMINI_MODELS)
    configured = {
        "GEMINI_MODEL": get_settings().GEMINI_MODEL,
        "AI_TEXT_MODEL": os.getenv("AI_TEXT_MODEL"),
        "AI_VISION_MODEL": os.getenv("AI_VISION_MODEL"),
        "AI_MULTIMODAL_MODEL": os.getenv("AI_MULTIMODAL_MODEL"),
        "REALTIME_MODEL": os.getenv("REALTIME_MODEL"),
    }
    for setting, model_id in configured.items():
        if model_id and model_id not in models:
            models[model_id] = f"configured via {setting} (not in the registry)"
    return models
