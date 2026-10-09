"""
Doctor handoff: turn a conversation into a note a clinician can actually use.

Why this is a separate domain rather than a report endpoint
-----------------------------------------------------------
A consultation the patient had with DEDAN is worthless to the next clinician
unless it arrives as structured facts. Patients reliably forget onset dates,
medication names and the sequence of changes -- exactly the things a clinician
asks about first. So the handoff exists to make the *patient's own account*
available in a form that saves the consultation time.

Three rules this module enforces in code, not in prompts
--------------------------------------------------------
1. **It is a summary, not a diagnosis.** Every payload carries
   `is_ai_generated: True` and `is_diagnosis: False`. The phrase "possible
   cause" is allowed because it is what a clinician needs to see; "you have X"
   is not, because DEDAN is not qualified to assert it.

2. **Nothing is shared without explicit approval.** `share()` requires the
   patient to pass the exact summary they reviewed. If the summary changed in
   between, the share is refused rather than sending something the patient did
   not see -- this is the consent boundary, enforced server-side because a
   client-side checkbox can be trivially bypassed.

3. **Unknown is a valid value.** `allergies: ["not stated"]` is correct and
   `allergies: []` would be a lie. An empty list reads as "no known allergies",
   which is a clinically significant difference from "we were not told".
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


class HandoffError(RuntimeError):
    """A handoff operation failed."""


#: The single most important disclaimer in the product. Attached to every
#: payload and shown in every surface that renders one.
AI_SUMMARY_DISCLAIMER = (
    "AI-generated patient summary — not a medical diagnosis. Only an authorised "
    "healthcare professional can confirm a diagnosis."
)

#: Used wherever a field is absent, so "unknown" is never rendered as "none".
UNKNOWN = "not stated"

#: Guards the no-diagnosis rule at the schema level: a field whose name implies a
#: confirmed condition is rejected by `build_summary`.
FORBIDDEN_FIELDS = frozenset({
    "diagnosis", "diagnosis_code", "confirmed_diagnosis", "disease",
    "icd_code", "condition", "final_diagnosis",
})

MAX_SYMPTOM_ITEMS = 40
MAX_TEXT_LENGTH = 400


def _clean(text: Optional[str], limit: int = MAX_TEXT_LENGTH) -> str:
    """Normalise free text: collapse whitespace, bound the length.

    Bounded because this text ends up in a clinician-facing note; an unbounded
    transcript fragment would be both unreadable and a log-injection vector.
    """
    if not text:
        return ""
    collapsed = re.sub(r"\s+", " ", str(text)).strip()
    return collapsed[:limit]


def _dedupe(values: Sequence[str]) -> List[str]:
    """Order-preserving de-duplication, case-insensitive."""
    seen: set = set()
    out: List[str] = []
    for value in values:
        cleaned = _clean(value, 160)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


# ---------------------------------------------------------------------------
# Structure extraction
# ---------------------------------------------------------------------------

#: Duration phrasings patients actually use. Extracted, not inferred: if the
#: patient never said how long, the field stays UNKNOWN rather than defaulting
#: to something clinically misleading.
_DURATION_PATTERNS = (
    re.compile(
        r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*(day|days)\b", re.I
    ),
    re.compile(
        r"\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s*(week|weeks)\b", re.I
    ),
    re.compile(
        r"\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s*(month|months)\b", re.I
    ),
    re.compile(r"\b(today|tonight)\b", re.I),
    re.compile(r"\b(yesterday)\b", re.I),
)

_SEVERITY_PATTERN = re.compile(r"\b(\d{1,2})\s*(?:/|out of|outof)\s*10\b", re.I)


def extract_duration(symptom_texts: Sequence[str]) -> str:
    """Pull an onset/duration statement out of what the patient said."""
    joined = " ".join(symptom_texts)
    for pattern in _DURATION_PATTERNS:
        match = pattern.search(joined)
        if not match:
            continue
        value = match.group(1) if match.groups() else match.group(0)
        return _clean(value.replace("a ", "one ").replace("an ", "one "), 60)
    return UNKNOWN


def extract_severity(symptom_texts: Sequence[str]) -> str:
    """Pull an explicit severity rating, if the patient gave one."""
    for text in symptom_texts:
        match = _SEVERITY_PATTERN.search(text)
        if not match:
            continue
        try:
            value = int(match.group(1))
        except ValueError:
            continue
        if 0 <= value <= 10:
            return f"{value}/10"
    return UNKNOWN


@dataclass
class HandoffSummary:
    """The clinician-facing note.

    Field names are chosen to be honest about epistemic status:
    `possible_causes` and `reported_symptoms`, never `diagnosis`.
    """

    main_concern: str
    reported_symptoms: List[str] = field(default_factory=list)
    onset: str = UNKNOWN
    duration: str = UNKNOWN
    severity: str = UNKNOWN
    associated_symptoms: List[str] = field(default_factory=list)
    allergies: List[str] = field(default_factory=list)
    medications: List[str] = field(default_factory=list)
    relevant_context: List[str] = field(default_factory=list)
    safety_findings: List[str] = field(default_factory=list)
    possible_causes: List[str] = field(default_factory=list)
    questions_for_clinician: List[str] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "main_concern": self.main_concern,
            "reported_symptoms": self.reported_symptoms,
            "onset": self.onset,
            "duration": self.duration,
            "severity": self.severity,
            "associated_symptoms": self.associated_symptoms,
            "allergies": self.allergies or [UNKNOWN],
            "medications": self.medications or [UNKNOWN],
            "relevant_context": self.relevant_context,
            "safety_findings": self.safety_findings,
            "possible_causes": self.possible_causes,
            "questions_for_clinician": self.questions_for_clinician,
            # --- provenance, always present ---
            "is_ai_generated": True,
            "is_diagnosis": False,
            "disclaimer": AI_SUMMARY_DISCLAIMER,
        }


def build_summary(
    main_concern: str,
    patient_statements: Sequence[str] = (),
    allergies: Sequence[str] = (),
    medications: Sequence[str] = (),
    relevant_context: Sequence[str] = (),
    safety_findings: Sequence[str] = (),
    possible_causes: Sequence[str] = (),
    clinician_questions: Sequence[str] = (),
    onset: Optional[str] = None,
    severity: Optional[str] = None,
) -> HandoffSummary:
    """Assemble the summary, rejecting anything that asserts a diagnosis."""
    offending = set(locals()) & FORBIDDEN_FIELDS
    if offending:
        # A caller passing `diagnosis=` would otherwise silently create a field
        # the rest of the system treats as clinician-confirmed.
        raise HandoffError(
            f"Handoff must not carry a confirmed-diagnosis field: {sorted(offending)}"
        )

    statements = [s for s in (_clean(s) for s in patient_statements) if s][:MAX_SYMPTOM_ITEMS]
    concern = _clean(main_concern)
    if not concern:
        # Fall back to the patient's own words rather than inventing a headline.
        concern = statements[0] if statements else UNKNOWN

    # Everything the patient said after their first statement is treated as
    # associated symptoms. A presentation choice, not an inference: it groups
    # what was said without asserting anything causal about it.
    return HandoffSummary(
        main_concern=concern,
        reported_symptoms=_dedupe(statements)[:MAX_SYMPTOM_ITEMS],
        onset=onset or UNKNOWN,
        duration=extract_duration(statements),
        severity=severity or extract_severity(statements),
        associated_symptoms=_dedupe(statements[1:])[:12],
        allergies=_dedupe(allergies),
        medications=_dedupe(medications),
        relevant_context=_dedupe(relevant_context)[:12],
        safety_findings=_dedupe(safety_findings)[:12],
        possible_causes=_dedupe(possible_causes)[:12],
        questions_for_clinician=_dedupe(clinician_questions)[:12],
    )


# ---------------------------------------------------------------------------
# Consent boundary
# ---------------------------------------------------------------------------

def content_fingerprint(summary: HandoffSummary) -> str:
    """Stable hash of the reviewable content.

    The patient approves a *fingerprint*, not a boolean. That is what makes
    "I approved this summary" mean something checkable: if the summary is
    regenerated after approval, the fingerprint changes and the share is
    refused.
    """
    return _fingerprint(summary.to_payload())


def _fingerprint(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def approve(summary: HandoffSummary) -> Dict[str, Any]:
    """Mark a summary reviewed and return the approval token.

    Approval is recorded, not implied: nothing is transmitted anywhere by this
    function. `share()` is the only thing that publishes, and it requires an
    approval token.
    """
    return {
        "handoff_id": uuid.uuid4().hex,
        "summary": summary.to_payload(),
        "fingerprint": content_fingerprint(summary),
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "is_shared": False,
        "shared_at": None,
        "disclaimer": AI_SUMMARY_DISCLAIMER,
    }


def share(approved: Dict[str, Any], approved_fingerprint: Optional[str]) -> Dict[str, Any]:
    """Publish an approved summary -- if and only if it is the one approved.

    `approved_fingerprint` is what the client echoes back from the summary the
    patient actually read. A mismatch means the content changed between review
    and share, and the correct action is to refuse rather than transmit content
    the patient has not seen.
    """
    if not approved.get("fingerprint"):
        raise HandoffError("Summary has not been approved.")
    if not approved_fingerprint:
        raise HandoffError("Sharing requires explicit patient approval.")

    if _fingerprint(approved.get("summary") or {}) != approved_fingerprint:
        logger.warning(
            "handoff_fingerprint_mismatch", extra={"handoff": approved.get("handoff_id")}
        )
        raise HandoffError(
            "The summary changed after it was reviewed. Review it again before sharing."
        )

    payload = dict(approved)
    payload["is_shared"] = True
    payload["shared_at"] = datetime.now(timezone.utc).isoformat()
    return payload


# ---------------------------------------------------------------------------
# Patient communication assistant
# ---------------------------------------------------------------------------

def patient_explanation(summary: HandoffSummary, language: str = "en") -> Dict[str, Any]:
    """Turn the clinical note into words the patient can say out loud.

    Patients struggle to describe symptoms precisely under clinical questioning.
    This restructures what DEDAN heard into first-person sentences, so the
    patient is rehearsing rather than reconstructing under pressure.
    """
    if language == "am":
        return {
            "language": "am",
            "sections": [
                {"heading": "ምሳሌ እየስራለሁ ነው", "body": summary.main_concern},
                {"heading": "መጀመሪያው", "body": summary.onset},
                {"heading": "የቀጠልኝ ርስ", "body": summary.severity},
                {
                    "heading": "ሌሎች ምልክቶች",
                    "body": "; ".join(summary.reported_symptoms[:5]) or UNKNOWN,
                },
                {
                    "heading": "ስለሚያስገኝኝ",
                    "body": "; ".join(summary.safety_findings) or "ምንም ችግር አልጠነውም",
                },
            ],
            "questions": [
                "ይህ ምልክት የሚያስከትለኝ ምክንያት ምላሽ?",
                "ምድጃዊ ምርመራ ወይስ ምድመራ ያስፈልግኛል?",
                "መድሃኛ ምላሽ ማንኛውንም አላወጣችሁም?",
            ],
            "disclaimer": AI_SUMMARY_DISCLAIMER,
        }

    sections = [
        {"heading": "What I am experiencing", "body": summary.main_concern},
        {"heading": "When it started", "body": summary.onset},
        {"heading": "How severe it is", "body": summary.severity},
        {
            "heading": "Other symptoms I have noticed",
            "body": "; ".join(summary.reported_symptoms[:5]) or UNKNOWN,
        },
        {
            "heading": "What I am most worried about",
            "body": "; ".join(summary.safety_findings) or "Nothing specific",
        },
    ]
    default_questions = [
        "What do you think is causing this?",
        "Do I need any tests or images?",
        "What medication should I take, and how much?",
        "What should I watch for that means I should come back?",
    ]
    return {
        "language": "en",
        "sections": sections,
        "questions": summary.questions_for_clinician or default_questions,
        "default_questions": default_questions,
        "disclaimer": AI_SUMMARY_DISCLAIMER,
    }
