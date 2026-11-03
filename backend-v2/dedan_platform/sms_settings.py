"""Settings of the SMS-first features (SMS-only patients, pushed notices and
the pull commands by short code; docs/sms.md).

Each setting is read from ``platform_settings`` first (key ``sms.<NAME>``,
so the super admin can manage them later without a deploy), then from the
environment, then the default below. Secrets (``ENV_ONLY``) come from the
environment only. Read on every use: switching inbound
SMS on or off, or changing the short code, needs no restart.

The short code is "live" only when ``SMS_INBOUND_ENABLED`` is true AND
``SMS_SHORT_CODE`` is set: until then no text ever tells a patient to text
a command (it would be misleading), and the inbound webhook answers 404.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, FrozenSet, Optional, Tuple

logger = logging.getLogger(__name__)

#: name -> default (strings, as in the environment).
DEFAULTS: Dict[str, str] = {
    # The pull commands (Option B): off until the short code exists.
    "SMS_INBOUND_ENABLED": "false",
    "SMS_SHORT_CODE": "",
    # The secret in the inbound callback URL (Africa's Talking), and the HMAC
    # key of the generic adapter's signature header. Unset: inbound refused.
    "SMS_INBOUND_SECRET": "",
    # Replies to inbound commands go out from the short code through this provider.
    "SMS_REPLY_PROVIDER": "africastalking",
    "AFRICASTALKING_USERNAME": "",
    "AFRICASTALKING_API_KEY": "",
    "AFRICASTALKING_API_URL": "https://api.africastalking.com/version1/messaging",
    # PINs.
    "SMS_PIN_MAX_ATTEMPTS": "5",
    "SMS_PIN_LOCK_MINUTES": "60",
    # Inbound rate limits (per sender phone, per hour; all senders, per hour).
    "SMS_INBOUND_MAX_PER_PHONE_PER_HOUR": "20",
    "SMS_INBOUND_MAX_PER_HOUR": "5000",
    # Replies: at most this many segments (GSM-7 153 chars, UCS-2/Amharic 67 chars each).
    "SMS_REPLY_MAX_SEGMENTS": "3",
    # Results per RESULT reply.
    "SMS_RESULTS_PER_REPLY": "3",
    # Enrolment of SMS-only patients by a hospital.
    "SMS_ENROL_CODE_TTL_MINUTES": "10",
    "SMS_ENROL_MAX_ATTEMPTS": "5",
    "SMS_ENROL_RESEND_SECONDS": "60",
    "SMS_ENROL_MAX_PER_PHONE_PER_HOUR": "5",
    "SMS_ENROL_MAX_PER_HOSPITAL_PER_HOUR": "200",
    # Never sent by SMS, even on request: LOINC codes, words in a test or
    # report (case-insensitive; a keyword must start a word, so "mental" does
    # not match "supplemental"), and ICD-10 code prefixes of a diagnosis.
    # HIV, pregnancy/hCG, sexually transmitted infections, mental health.
    "SMS_SENSITIVE_LOINC": ",".join((
        # HIV
        "7917-8", "7918-6", "5221-7", "68961-2", "56888-1", "75622-1", "48345-6", "48346-4", "31201-7",
        "43009-0", "43010-8", "49580-4", "49905-3", "20447-9", "25836-8", "41513-3", "41514-1", "70241-5",
        "10351-5", "29539-4", "29541-0", "62469-2", "57182-8", "40733-8", "44533-8", "9821-0",
        # Pregnancy / hCG
        "2106-3", "2107-1", "2110-5", "2112-1", "2113-9", "2114-7", "2118-8", "2119-6", "19080-1",
        "21198-7", "25372-4", "45194-8", "53959-5", "80384-1", "83086-9",
        # Syphilis, gonorrhoea, chlamydia, herpes, trichomonas, hepatitis B surface antigen
        "20507-0", "22461-8", "22462-6", "24110-9", "5292-8", "11084-1", "47236-8", "71793-4",
        "26009-1", "24111-7", "43304-5", "21613-5", "4993-2", "6349-5", "6357-8", "45084-1",
        "21415-5", "5276-1", "16130-7", "69933-0", "5195-3", "7905-3",
    )),
    "SMS_SENSITIVE_KEYWORDS": ",".join((
        "hiv", "aids", "cd4", "viral load", "elisa", "western blot", "antiretroviral",
        "pregnan", "hcg", "beta-hcg", "b-hcg", "gonadotropin",
        "syphilis", "vdrl", "rpr", "tpha", "treponem", "gonorrh", "chlamydia", "herpes", "hsv",
        "trichomon", "sexually transmitted", "hepatitis b", "hbsag",
        "psychiatr", "mental", "depress", "anxiety", "schizo", "bipolar", "psychos", "suicid",
        "substance", "alcohol use", "drug use",
        "ኤች አይ ቪ", "ኤድስ", "እርግዝና", "ቂጥኝ", "ጨብጥ", "የአእምሮ",
    )),
    "SMS_SENSITIVE_ICD10": ",".join(("B20", "B21", "B22", "B23", "B24", "Z21", "R75", "F", "O", "Z32", "Z33",
                                     "Z34", "Z35", "Z36", "A50", "A51", "A52", "A53", "A54", "A55", "A56",
                                     "A57", "A58", "A59", "A60", "A63", "A64", "B16", "B18.0", "B18.1")),
}

_TRUE = {"1", "true", "yes", "on"}

#: Secrets, and where they are sent: from the environment only, never from the database.
ENV_ONLY = frozenset({"SMS_INBOUND_SECRET", "AFRICASTALKING_API_KEY", "AFRICASTALKING_API_URL"})


def _from_database(name: str) -> Optional[str]:
    try:
        from dedan_platform.db import session_scope
        from dedan_platform.models import PlatformSetting

        with session_scope() as session:
            row = session.get(PlatformSetting, f"sms.{name}")
            return row.value if row is not None else None
    except Exception as exc:  # the table may not exist yet (a fresh database): the environment decides
        logger.debug("sms_setting_db_unavailable name=%s error=%s", name, type(exc).__name__)
        return None


def get(name: str) -> str:
    if name not in DEFAULTS:
        raise KeyError(name)
    value = None if name in ENV_ONLY else _from_database(name)
    if value is None:
        value = os.getenv(name)
    if value is None:
        value = DEFAULTS[name]
    return value.strip()


def flag(name: str) -> bool:
    return get(name).lower() in _TRUE


def number(name: str) -> int:
    try:
        return int(get(name))
    except ValueError:
        logger.warning("sms_setting_not_a_number name=%s", name)
        return int(DEFAULTS[name])


def items(name: str) -> Tuple[str, ...]:
    return tuple(part.strip().lower() for part in get(name).split(",") if part.strip())


def inbound_enabled() -> bool:
    return flag("SMS_INBOUND_ENABLED")


def short_code() -> str:
    return get("SMS_SHORT_CODE")


def inbound_live() -> bool:
    """Whether patients can text commands now (the switch on and a short code)."""
    return inbound_enabled() and bool(short_code())


def sensitive_loinc() -> FrozenSet[str]:
    return frozenset(items("SMS_SENSITIVE_LOINC"))


def sensitive_keywords() -> Tuple[str, ...]:
    return items("SMS_SENSITIVE_KEYWORDS")


def sensitive_icd10() -> Tuple[str, ...]:
    return tuple(code.upper() for code in items("SMS_SENSITIVE_ICD10"))
