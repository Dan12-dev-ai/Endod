"""
Languages a patient can choose for the app and for consultations.

ISO 639-1 codes; English first because it is the storage default
(`Preferences.language`).
"""

from __future__ import annotations

from typing import Tuple

SUPPORTED_LANGUAGES: Tuple[str, ...] = ("en", "am", "om", "ti", "so", "sw")
