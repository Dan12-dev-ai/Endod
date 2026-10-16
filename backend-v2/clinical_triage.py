"""
Deterministic red-flag triage for patient-described symptoms.

This is the safety floor under every assessment, whichever AI provider (or
none) produced it: the final urgency is the *higher* of the model's answer and
these rules, so a model can add caution but never remove it.

What it checks
--------------
* Emergency red flags in English and Amharic: breathing, cardiac, stroke,
  consciousness, seizures, severe bleeding, self-harm and suicidal thoughts,
  poisoning/overdose, anaphylaxis, meningitis signs, severe trauma.
* Age-specific rules: young infants with fever; WHO IMCI general danger signs
  in children (unable to drink, vomiting everything, convulsions, lethargy);
  prolonged fever or poor feeding in children; older adults.
* Pregnancy danger signs (bleeding, severe headache, blurred vision, severe
  abdominal pain, convulsions, reduced fetal movement).
* Measured temperatures ("39C", "39.5 °C", "103F", "40 degrees").
* Negation ("no chest pain", "I don't have a fever"), so a denied symptom does
  not trigger a false emergency.

Limits
------
Keyword rules miss presentations they were not written for. The Amharic terms
and every rule here need review by an Ethiopian clinician and native speakers
before real patient use; see ``docs/medication-safety.md`` and the README's
medical-safety section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Pattern, Sequence, Tuple

# ---------------------------------------------------------------------------
# Urgency ordering
# ---------------------------------------------------------------------------

#: Lowest to highest. Matches the provider contract's urgency strings.
URGENCY_ORDER: Tuple[str, ...] = ("self_care", "routine", "see_doctor_soon", "urgent", "emergency")
_RANK = {name: i for i, name in enumerate(URGENCY_ORDER)}


def urgency_rank(urgency: Optional[str]) -> int:
    """Rank of an urgency string. Unknown values rank as ``see_doctor_soon``.

    Treating an unknown value as "see a doctor soon" (rather than routine) means
    a provider that returns an unexpected label is never read as reassurance.
    """
    if not urgency:
        return _RANK["routine"]
    value = urgency.strip().lower()
    if value in _RANK:
        return _RANK[value]
    if "emerg" in value or "critical" in value or "immediate" in value:
        return _RANK["emergency"]
    if "urgent" in value:
        return _RANK["urgent"]
    if value in {"soon", "see_doctor"}:
        return _RANK["see_doctor_soon"]
    return _RANK["see_doctor_soon"]


def max_urgency(*urgencies: Optional[str]) -> str:
    """The highest of ``urgencies``, normalised to a known urgency string."""
    best = max((urgency_rank(u) for u in urgencies), default=_RANK["routine"])
    return URGENCY_ORDER[best]


# ---------------------------------------------------------------------------
# Emergency numbers
# ---------------------------------------------------------------------------

#: (country names and ISO codes, number to show). Matched on whole words so a
#: city such as "Mekelle" cannot match the code "ke".
_EMERGENCY_NUMBERS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("ethiopia", "et"), "907 (ambulance) or 991 (police)"),
    (("kenya", "ke"), "999 or 112"),
    (("tanzania", "tz"), "112"),
    (("uganda", "ug"), "999 or 112"),
    (("rwanda", "rw"), "912 (ambulance) or 112"),
    (("somalia", "so"), "888 or 999"),
    (("nigeria", "ng"), "112"),
    (("ghana", "gh"), "112"),
    (("south africa", "za"), "10177 or 112"),
    (("united states", "usa", "us"), "911"),
    (("canada", "ca"), "911"),
    (("united kingdom", "uk", "gb"), "999 or 112"),
    (("australia", "au"), "000"),
)

_DEFAULT_EMERGENCY_NUMBER = "your local emergency number (in Ethiopia: 907 for an ambulance)"


def emergency_number(location: Optional[str]) -> str:
    """Emergency number for a free-text location or country code."""
    if not location:
        return _DEFAULT_EMERGENCY_NUMBER
    text = location.lower()
    for names, number in _EMERGENCY_NUMBERS:
        for name in names:
            if re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", text):
                return number
    return _DEFAULT_EMERGENCY_NUMBER


# ---------------------------------------------------------------------------
# Text normalisation and negation
# ---------------------------------------------------------------------------

_NEGATION_CUES = re.compile(
    r"\b(no|not|without|denies|denied|never|nor|"
    r"(?:do|does|did)\s?n['o]?t\s+have|have\s?n['o]?t\s+(?:had|got)|"
    r"free\s+of|negative\s+for)\b"
)
#: How many words may sit between a negation cue and the symptom it negates.
_NEGATION_WINDOW = 5
#: Words that start a new subject or clause. A negation cue never reaches past
#: one: in "no idea why I can't breathe" the breathing is not denied.
_NEGATION_BLOCKERS = frozenset({
    "i", "i'm", "im", "he", "she", "they", "we", "you", "it", "my", "his", "her", "our",
    "their", "why", "idea", "because", "if", "when", "what", "how", "that", "which", "who",
    "so", "is", "am", "are", "was", "were", "be", "been", "can", "can't", "cannot", "now",
    "sure", "know", "think", "until", "since", "suddenly", "today", "yesterday",
})
_CLAUSE_SPLIT = re.compile(r"[.;!?\n]|,\s*but\b|\bbut\b|\bhowever\b|\balthough\b")


def _normalise(text: str) -> str:
    text = text.lower()
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    text = re.sub(r"\bcan\s?not\b", "cannot", text)
    text = re.sub(r"\bcant\b", "can't", text)
    text = re.sub(r"\bwont\b", "won't", text)
    text = re.sub(r"\bdont\b", "don't", text)
    return re.sub(r"[ \t]+", " ", text)


#: "or"/"nor" are absent on purpose: "no chest pain or difficulty breathing"
#: denies both.
_CONJUNCTION = re.compile(r",|\b(?:and|with|plus|also|then)\b")


def _is_negated(clause: str, start: int) -> bool:
    """True when a negation cue sits just before ``start`` in the same phrase.

    Negation never reaches across "and", a comma, or a new subject: in "no chest
    pain and can't breathe" or "no idea why I can't breathe" the breathing is
    not denied. Erring this way can only make the result more cautious.
    """
    before = clause[:start]
    cues = list(_NEGATION_CUES.finditer(before))
    if not cues:
        return False
    gap = before[cues[-1].end():]
    if _CONJUNCTION.search(gap):
        return False
    words = gap.split()
    if any(word in _NEGATION_BLOCKERS for word in words):
        return False
    return len(words) <= _NEGATION_WINDOW


def _find(patterns: Sequence[Pattern[str]], clauses: Sequence[str]) -> Optional[str]:
    """First non-negated match of any pattern, as the matched text."""
    for clause in clauses:
        for pattern in patterns:
            for match in pattern.finditer(clause):
                if not _is_negated(clause, match.start()):
                    return match.group(0).strip()
    return None


def _compile(patterns: Iterable[str]) -> List[Pattern[str]]:
    return [re.compile(p) for p in patterns]


# ---------------------------------------------------------------------------
# Rule tables
# ---------------------------------------------------------------------------

_BREATHE = r"(?:breathe|breathing|breath)"

#: Each rule: (reason code, patterns). English patterns run on lower-cased
#: text; Amharic (Ge'ez script) patterns are matched as written.
_EMERGENCY_RULES: Tuple[Tuple[str, List[Pattern[str]]], ...] = (
    ("self_harm_or_suicidal_thoughts", _compile([
        r"suicid\w*",
        r"kill (?:my ?self|himself|herself)",
        r"end (?:my|his|her) (?:own )?life",
        r"take (?:my|his|her) (?:own )?life",
        r"(?:want|wants|wanted|going) to die\b",
        r"(?:don't|do not|doesn't|no longer) want to (?:live|be alive|wake up)",
        r"better off dead",
        r"(?:hurt|harm|cut)(?:ting)? (?:my ?self|himself|herself)",
        r"self[- ]?harm\w*",
        r"no reason to live",
        r"ራሴን (?:ማጥፋት|ላጠፋ|አጠፋ)", r"ራስን ማጥፋት", r"መሞት (?:እፈልጋለሁ|ፈልጌ)",
    ])),
    ("poisoning_or_overdose", _compile([
        r"overdos\w*",
        r"(?<!food )poison\w*",
        r"took (?:\d{2,}|too many|a lot of|all (?:of )?(?:my|the|his|her)) (?:\w+ )?(?:pills|tablets|capsules)",
        r"took \d{2,} (?:paracetamol|panadol|acetaminophen|ibuprofen|aspirin|sleeping)",
        r"\b\d{2,} (?!mg\b|mcg\b|ml\b|g\b)(?:\w+ )?(?:pills|tablets|capsules)\b",
        r"swallowed (?:bleach|poison|chemicals?|kerosene|petrol|a battery|pesticide)",
        r"drank (?:bleach|poison|kerosene|petrol|pesticide)",
        r"መርዝ",
    ])),
    ("breathing_emergency", _compile([
        rf"(?:can't|cannot|unable to|could not|couldn't|struggling to|hard to) {_BREATHE}",
        rf"not {_BREATHE}",
        rf"stopped {_BREATHE}",
        rf"(?:difficulty|trouble|problems?) {_BREATHE}",
        r"short(?:ness)? of breath",
        r"gasping",
        r"chok(?:ing|ed)",
        r"blue lips|lips (?:are |turning |turned )?blue|turning blue",
        r"መተንፈስ (?:አልችልም|አልቻለም|አልቻለችም|አቃተኝ|አቃተው|አቃታት)",
        r"የመተንፈስ ችግር", r"ትንፋሽ (?:ማጠር|አጠረኝ|አጠረው|አጠራት)",
    ])),
    ("cardiac_chest_pain", _compile([
        r"chest (?:pain|pressure|tightness|heaviness)",
        r"(?:crushing|tight|heavy|squeezing) (?:pain in (?:my|the|his|her) )?chest",
        r"pain (?:spreading|radiating|going|moving) (?:down |up )?(?:to|into) (?:my |his |her |the )?(?:left )?(?:arm|jaw)",
        r"heart attack",
        r"(?:የደረት|ደረቴን|ደረቱን|ደረቷን) (?:ሕመም|ህመም|ያመኛል|ያመዋል|ያማታል)",
    ])),
    ("stroke_signs", _compile([
        r"\bstroke\b",
        r"(?:face|mouth|smile) (?:is |has |looks )?(?:droop|drooping|dropped|twisted|lopsided)",
        r"(?:facial|face) droop\w*",
        r"droop\w* (?:on )?(?:one|left|right) side",
        r"slurred speech|slurring (?:his|her|my)? ?(?:words|speech)",
        r"(?:sudden(?:ly)?|can't|cannot|unable to) (?:speak|talk)",
        r"(?:arm|leg|hand) (?:is |went |feels |suddenly )?(?:weak|numb|paralys\w*|limp)",
        r"(?:weakness|numbness) (?:in|on|of) (?:one|the left|the right|his left|his right|her left|her right) (?:side|arm|leg)",
        r"sudden (?:weakness|numbness|confusion|blindness|loss of vision)",
        r"ስትሮክ", r"ፊ(?:ቴ|ቱ|ቷ) ተጣመመ", r"የፊት መጣመም", r"ሽባ",
    ])),
    ("unconscious_or_unresponsive", _compile([
        r"unconscious",
        r"unresponsive",
        r"not respond\w*",
        r"(?:loss of|lost) consciousness",
        r"passed out",
        r"collapsed",
        r"(?:won't|will not|can't|cannot|unable to|hard to|difficult to) wake",
        r"not waking",
        r"ራ(?:ሱን|ሷን|ሴን) (?:ሳተ|ሳተች|ሳትኩ|ስቷል|ስታለች)",
    ])),
    ("seizure", _compile([
        r"seizure\w*",
        r"convuls\w*",
        r"having (?:a )?fits?\b",
        r"መንቀጥቀጥ", r"የሚጥል",
    ])),
    ("severe_bleeding", _compile([
        r"(?:severe|heavy|uncontrolled|a lot of) bleeding",
        r"bleeding (?:heavily|a lot|won't stop|that won't stop|will not stop|non-?stop)",
        r"(?:vomiting|throwing up|coughing up|coughing) blood",
        r"black (?:tarry )?(?:stool|poo)\w*",
        r"ደም (?:ማስታወክ|ያስታውከኛል|ያስታውከዋል)", r"ብዙ ደም",
    ])),
    ("anaphylaxis", _compile([
        r"anaphyla\w*",
        r"(?:throat|tongue|lips?) (?:is |are )?(?:closing|swelling|swollen)",
        r"swollen (?:throat|tongue)",
    ])),
    ("meningitis_signs", _compile([
        r"stiff neck.{0,40}(?:fever|headache|rash)",
        r"(?:fever|headache).{0,40}stiff neck",
        r"neck (?:is )?stiff.{0,40}fever",
    ])),
    ("severe_trauma", _compile([
        r"severe (?:head injury|burns?)",
        r"head injury.{0,40}(?:vomit|unconscious|confus|sleepy)",
        r"(?:hit|struck) by a (?:car|vehicle|truck|motorbike|bus)",
        r"electric(?:al)? shock|electrocut\w*",
        r"drown\w*",
        r"bone (?:is )?(?:sticking|poking) out",
    ])),
)

_URGENT_RULES: Tuple[Tuple[str, List[Pattern[str]]], ...] = (
    ("high_fever", _compile([r"high fever", r"very high temperature", r"ከፍተኛ ትኩሳት"])),
    ("severe_headache", _compile([r"(?:severe|worst|terrible|sudden) headache", r"ከባድ የራስ ምታት"])),
    ("severe_abdominal_pain", _compile([r"severe (?:abdominal|stomach|belly) pain"])),
    ("dehydration", _compile([
        r"(?:can't|cannot|unable to) keep (?:any )?(?:fluids|water|anything) down",
        r"(?:severely |very )?dehydrat\w*",
        r"(?:not|no|hasn't|hasn't been) (?:peeing|urinating|passing urine)",
    ])),
    ("persistent_vomiting", _compile([r"(?:persistent|constant|non-?stop) vomiting", r"vomit\w* everything"])),
    ("bloody_diarrhoea", _compile([r"blood(?:y)? (?:in (?:the |my )?)?(?:diarrh\w*|stool)"])),
    ("confusion", _compile([r"\bconfus\w*", r"disoriented"])),
    ("severe_pain", _compile([r"severe pain", r"unbearable pain"])),
    ("spreading_infection", _compile([r"spreading redness", r"red streak\w*"])),
)

_FEVER = _compile([
    r"fever\w*", r"febrile", r"(?:high|raised|very high) temperature", r"hot to (?:the )?touch", r"ትኩሳት",
])

_STIFF_NECK = _compile([r"stiff neck", r"neck (?:is )?stiff", r"can't (?:bend|move) (?:my|his|her) neck"])

_CHILD_HINT = _compile([
    r"\b(?:my |our |the )?(?:baby|infant|newborn|toddler|child|kid|son|daughter|boy|girl)\b",
    r"ሕፃን|ህፃን|ልጄ|ልጃችን",
])
_INFANT_HINT = _compile([r"\b(?:baby|infant|newborn)\b", r"ሕፃን|ህፃን"])
_PREGNANCY_HINT = _compile([r"pregnan\w*", r"weeks? pregnant", r"expecting a baby", r"እርጉዝ", r"ነፍሰ ጡር"])

# WHO IMCI general danger signs for a sick child.
_CHILD_DANGER_SIGNS = _compile([
    r"(?:not|not able to|unable to|can't|cannot|won't|refus\w* to) (?:drink|breastfeed|breast ?feed|feed|suck)",
    r"(?:vomit\w*|throws? up) everything",
    r"(?:very |unusually )?(?:sleepy|drowsy|lethargic|floppy|limp)",
    r"hard to wake|difficult to wake",
])
_POOR_FEEDING = _compile([r"(?:not|isn't|hasn't been|won't|refus\w* to) (?:eat\w*|feed\w*)", r"no appetite", r"lost (?:his|her|their) appetite"])

_PREGNANCY_DANGER_SIGNS = _compile([
    r"bleed\w*",
    r"severe (?:abdominal|stomach|belly) pain",
    r"(?:severe|bad|terrible) headache",
    r"blurr\w* vision|vision (?:is )?blurr\w*",
    r"(?:baby|fetus) (?:is )?(?:not moving|moving less|stopped moving)",
    r"(?:reduced|less|no) (?:fetal |baby )?movement",
    r"water (?:has )?broke\w*",
    r"swollen (?:face|hands)",
])

_TEMPERATURE = re.compile(
    r"(\d{2,3}(?:[.,]\d)?)\s*(°|º|degrees?|deg)?\s*(c|f|celsius|fahrenheit)?\b"
)
#: A number with no unit counts as a temperature only right after one of these.
_TEMPERATURE_CONTEXT = re.compile(r"(?:fever|temperature|temp|ትኩሳት)\D{0,25}$")
_AGE_IN_TEXT = re.compile(r"\b(\d{1,2})[- ](day|week|month|year)s?[- ]old\b")
_DAYS = re.compile(
    r"\b(\d{1,2}|two|three|four|five|six|seven|ten)\s+days?\b|\b(?:a|one|two|three)\s+weeks?\b"
)
_WORD_NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10}


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class TriageResult:
    urgency: str = "routine"
    #: Machine-readable reason codes, e.g. ``"emergency:breathing_emergency"``.
    reasons: List[str] = field(default_factory=list)
    #: The text that triggered the highest-urgency rule, for audit/logging.
    trigger: Optional[str] = None

    def raise_to(self, urgency: str, reason: str, trigger: Optional[str] = None) -> None:
        self.reasons.append(reason)
        if urgency_rank(urgency) > urgency_rank(self.urgency):
            self.urgency = urgency
            self.trigger = trigger

    @property
    def is_emergency(self) -> bool:
        return self.urgency == "emergency"


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


def _max_temperature_c(text: str) -> Optional[float]:
    """Highest plausible body temperature mentioned, in Celsius."""
    best: Optional[float] = None
    for match in _TEMPERATURE.finditer(text):
        value = float(match.group(1).replace(",", "."))
        unit = (match.group(3) or "").lower()
        if not unit and not match.group(2) and not _TEMPERATURE_CONTEXT.search(text[: match.start()]):
            # "my 40 year old husband", "500 mg": not a temperature.
            continue
        if unit.startswith("f") or (not unit and 95 <= value <= 110):
            celsius = (value - 32) * 5 / 9
        elif unit.startswith("c") or (not unit and 35 <= value <= 43):
            celsius = value
        else:
            continue
        if 35 <= celsius <= 45:
            best = celsius if best is None else max(best, celsius)
    return best


def _age_in_months_from_text(text: str) -> Optional[float]:
    match = _AGE_IN_TEXT.search(text)
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    return {"day": value / 30, "week": value / 4.3, "month": value, "year": value * 12}[unit]


def _fever_days(text: str) -> Optional[int]:
    best: Optional[int] = None
    for match in _DAYS.finditer(text):
        token = match.group(0)
        if "week" in token:
            days = 7 * ({"a": 1, "one": 1, "two": 2, "three": 3}.get(token.split()[0], 1))
        else:
            raw = match.group(1)
            days = int(raw) if raw.isdigit() else _WORD_NUMBERS.get(raw, 0)
        best = days if best is None else max(best, days)
    return best


def assess(
    text: str,
    age_years: Optional[float] = None,
    pregnant: Optional[bool] = None,
) -> TriageResult:
    """Triage free-text symptoms. ``age_years`` may be fractional (0.5 = 6 months)."""
    result = TriageResult()
    normalised = _normalise(text or "")
    if not normalised.strip():
        return result
    clauses = [c for c in _CLAUSE_SPLIT.split(normalised) if c.strip()]

    for reason, patterns in _EMERGENCY_RULES:
        hit = _find(patterns, clauses)
        if hit:
            result.raise_to("emergency", f"emergency:{reason}", hit)

    for reason, patterns in _URGENT_RULES:
        hit = _find(patterns, clauses)
        if hit:
            result.raise_to("urgent", f"urgent:{reason}", hit)

    # --- Fever and temperature --------------------------------------------
    fever = _find(_FEVER, clauses)
    temperature = _max_temperature_c(normalised)
    if temperature is not None and temperature >= 37.5:
        fever = fever or f"{temperature:.1f}C"
    if temperature is not None:
        if temperature >= 41:
            result.raise_to("emergency", "emergency:very_high_temperature", f"{temperature:.1f}C")
        elif temperature >= 39:
            result.raise_to("urgent", "urgent:high_temperature", f"{temperature:.1f}C")
    fever_days = _fever_days(normalised) if fever else None
    if fever:
        stiff_neck = _find(_STIFF_NECK, clauses)
        if stiff_neck:
            result.raise_to("emergency", "emergency:meningitis_signs", stiff_neck)

    # --- Age ---------------------------------------------------------------
    months = _age_in_months_from_text(normalised)
    if months is None and age_years is not None:
        months = float(age_years) * 12
    infant_hint = _find(_INFANT_HINT, clauses)
    child_hint = _find(_CHILD_HINT, clauses)
    is_child = (months is not None and months < 60) or (months is None and bool(child_hint))
    is_young_infant = months is not None and months < 3
    if months is None and infant_hint and "newborn" in infant_hint:
        is_young_infant = True

    if fever and is_young_infant:
        result.raise_to("emergency", "emergency:fever_in_young_infant", fever)
    elif fever and infant_hint and months is None:
        # A baby of unknown age with fever: could be under 3 months.
        result.raise_to("urgent", "urgent:fever_in_infant", fever)

    if is_child:
        danger = _find(_CHILD_DANGER_SIGNS, clauses)
        if danger:
            result.raise_to("emergency", "emergency:child_danger_sign", danger)
        if fever and fever_days is not None and fever_days >= 3:
            result.raise_to("urgent", "urgent:prolonged_fever_in_child", fever)
        poor_feeding = _find(_POOR_FEEDING, clauses)
        if poor_feeding:
            result.raise_to("urgent", "urgent:child_not_eating", poor_feeding)
        if fever:
            result.raise_to("see_doctor_soon", "soon:fever_in_child", fever)
    elif fever and fever_days is not None and fever_days >= 3:
        result.raise_to("see_doctor_soon", "soon:prolonged_fever", fever)

    if age_years is not None and age_years >= 75 and (fever or result.urgency != "routine"):
        result.raise_to("urgent", "urgent:older_adult_with_symptoms", fever)

    # --- Pregnancy ---------------------------------------------------------
    if pregnant or _find(_PREGNANCY_HINT, clauses):
        danger = _find(_PREGNANCY_DANGER_SIGNS, clauses)
        if danger:
            result.raise_to("emergency", "emergency:pregnancy_danger_sign", danger)
        if fever:
            result.raise_to("urgent", "urgent:fever_in_pregnancy", fever)

    return result


def emergency_instructions(location: Optional[str]) -> str:
    """Patient-facing instruction shown with every emergency result."""
    return (
        "This may be a medical emergency. Call "
        f"{emergency_number(location)} or go to the nearest emergency department now. "
        "Do not wait for symptoms to get worse."
    )


__all__: Sequence[str] = (
    "URGENCY_ORDER",
    "TriageResult",
    "assess",
    "emergency_instructions",
    "emergency_number",
    "max_urgency",
    "urgency_rank",
)
