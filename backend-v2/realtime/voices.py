"""
Supported consultation languages and the voice registry.

Languages are a platform fact: a patient's language preference is validated
against ``SUPPORTED_LANGUAGES`` whether or not live voice is available, so the
list lives here rather than with any provider.

Voice ids are validated the same way, so an unknown id is rejected instead of
being silently replaced by a default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

#: ISO 639-1 codes. English first because it is the storage default
#: (`Preferences.language`).
SUPPORTED_LANGUAGES: Tuple[str, ...] = ("en", "am", "om", "ti", "so", "sw")


class VoiceUnavailableError(ValueError):
    """The requested voice id is not in the registry."""


@dataclass(frozen=True)
class Voice:
    id: str
    label: str


#: Voices offered for spoken replies. Kept provider-neutral; a provider maps
#: these ids to its own voice names when live voice is enabled.
VOICES: Dict[str, Voice] = {
    voice.id: voice
    for voice in (
        Voice(id="warm", label="Warm"),
        Voice(id="calm", label="Calm"),
        Voice(id="clear", label="Clear"),
    )
}


def get_voice(voice_id: str) -> Voice:
    """Return the registered voice for ``voice_id``. Raises ``VoiceUnavailableError``."""
    voice = VOICES.get(voice_id)
    if voice is None:
        raise VoiceUnavailableError(
            f"Unknown voice '{voice_id}'. Available: {sorted(VOICES)}"
        )
    return voice
