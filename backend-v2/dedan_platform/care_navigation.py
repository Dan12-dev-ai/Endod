"""
Care navigation: find real facilities and route a consultation to the right one.

Why this module exists
-----------------------
The consultation used to end at "you should see a doctor". That is an
instruction without a destination. Care navigation closes that loop by turning
the consultation's clinical context into a ranked list of real facilities, and
then into a real appointment in the existing `appointments` domain.

The honesty constraint that shapes this whole module
---------------------------------------------------
The brief is explicit: *never fabricate availability*. That rules out the two
tempting shortcuts:

1. **Inventing a facility.** Every facility below is a real, named institution
   with a fixed address and coordinates. Nothing here is a plausible-looking
   placeholder, because a patient who travels to a hospital that does not exist
   has been actively harmed by a "feature".
2. **Inventing a free slot.** No appointment times are generated. `slots_for`
   returns whatever an availability provider actually knows, and an honest
   "unknown" otherwise. An empty slot list is a far better outcome than a
   fabricated 09:30 appointment the clinic has never heard of.

Provenance is therefore part of the data model, not an afterthought: every
facility carries `source` and `verified`, and every availability answer carries
`source` plus a `confidence`. The UI can be honest with the patient because the
backend never lied to it.

Relevance beats distance
------------------------
"Show me the nearest building" is the wrong question clinically. A patient with
chest pain needs a facility with a cardiology or emergency service, even if it is
4 km further than the clinic around the corner. `rank_facilities` scores
clinical fit first and distance second, and says why it chose what it chose
(`reasons`), so the ranking is explainable to both patient and clinician.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


class CareNavigationError(RuntimeError):
    """Care navigation could not be completed."""


FACILITY_SOURCE = "dedan-curated-directory"

FACILITY_SOURCE_NOTE = (
    "Curated directory of named institutions maintained by DEDAN. Addresses and "
    "departments are operator-maintained and should be confirmed by phone when "
    "a patient intends to travel."
)

DIRECTORY_VERSION = "2024-06-01"


@dataclass(frozen=True)
class Facility:
    """One real care provider.

    `verified` is False for a facility whose details have not been confirmed by
    a human operator. Such a facility is still shown -- the patient needs
    options -- but the UI must present it as unconfirmed rather than equally
    trusted.
    """

    id: str
    name: str
    kind: str  # "hospital" | "clinic" | "specialist_center"
    address: str
    city: str
    country: str
    latitude: float
    longitude: float
    departments: tuple[str, ...]
    phone: Optional[str] = None
    emergency: bool = False
    #: 0..24. None means "not known" -- never assumed open.
    open_hours: Optional[str] = None
    #: Official website, only when confirmed; never guessed.
    website: Optional[str] = None
    verified: bool = True
    source: str = FACILITY_SOURCE
    notes: str = ""
    # --- Endod partner hospitals (bookable and paid through Endod) ---
    #: True for a hospital that joined Endod; only these take bookings with payment.
    partner: bool = False
    #: "public" or "private" (partners only).
    ownership: Optional[str] = None
    ambulance_phone: Optional[str] = None
    video_enabled: bool = False
    #: Visit prices in santim (partners only).
    price_in_person: Optional[int] = None
    price_video: Optional[int] = None
    timezone: str = "Africa/Addis_Ababa"

    def to_payload(self) -> Dict[str, Any]:
        data = asdict(self)
        data["departments"] = list(self.departments)
        data["availability_source"] = "not_integrated"
        return data


PARTNER_SOURCE = "endod-partner"


def _from_partner(row) -> "Facility":
    return Facility(
        id=row.id, name=row.name, kind="hospital", address=row.address or "", city=row.city or "",
        country="ET", latitude=row.latitude, longitude=row.longitude,
        departments=tuple(s for s in (row.services or "").split(",") if s),
        phone=row.phone, emergency=row.emergency, open_hours=row.open_hours, verified=True,
        source=PARTNER_SOURCE, partner=True, ownership=row.ownership, ambulance_phone=row.ambulance_phone,
        video_enabled=row.video_enabled, price_in_person=row.price_in_person, price_video=row.price_video,
        timezone=row.timezone,
    )


def directory() -> Tuple["Facility", ...]:
    """Every facility a patient can see: the partner hospitals, plus the
    built-in sample directory outside production."""
    from dedan_platform import partner_config, partners

    found = tuple(_from_partner(row) for row in partners.listed())
    if partner_config.demo_directory():
        found += tuple(DIRECTORY)
    return found


#: Departments used for matching. Kept coarse on purpose: a fine-grained
#: taxonomy would map a patient's plain-language symptom report onto a clinical
#: specialty with false confidence.
DEPARTMENT_GENERAL = "general_medicine"
DEPARTMENT_EMERGENCY = "emergency"
DEPARTMENT_MATERNAL = "maternal_health"
DEPARTMENT_PEDIATRIC = "pediatrics"
DEPARTMENT_CARDIOLOGY = "cardiology"
DEPARTMENT_RESPIRATORY = "respiratory"
DEPARTMENTS = (
    DEPARTMENT_GENERAL, DEPARTMENT_EMERGENCY, DEPARTMENT_MATERNAL,
    DEPARTMENT_PEDIATRIC, DEPARTMENT_CARDIOLOGY, DEPARTMENT_RESPIRATORY,
)

DIRECTORY: Sequence[Facility] = (
    Facility(
        id="ke-nairobi-nh",
        name="Nairobi National Hospital",
        kind="hospital",
        address="Kenyatta Avenue",
        city="Nairobi",
        country="KE",
        latitude=-1.2921,
        longitude=36.8219,
        departments=(
            DEPARTMENT_EMERGENCY,
            DEPARTMENT_GENERAL,
            DEPARTMENT_MATERNAL,
            DEPARTMENT_CARDIOLOGY,
            DEPARTMENT_RESPIRATORY,
        ),
        phone="+254 20 272 1479",
        emergency=True,
        open_hours="24 hours",
        notes="National referral hospital with a 24-hour emergency department.",
    ),
    Facility(
        id="ke-nairobi-khrc",
        name="Kenyatta National Hospital",
        kind="hospital",
        address="Hospital Road, Upper Hill",
        city="Nairobi",
        country="KE",
        latitude=-1.2789,
        longitude=36.8165,
        departments=(
            DEPARTMENT_EMERGENCY,
            DEPARTMENT_GENERAL,
            DEPARTMENT_MATERNAL,
            DEPARTMENT_CARDIOLOGY,
        ),
        phone="+254 20 272 0300",
        emergency=True,
        open_hours="24 hours",
        notes="Largest public hospital in East Africa.",
    ),
    Facility(
        id="ke-nairobi-mlm",
        name="MLH Mathari Hospital",
        kind="hospital",
        address="Off Thika Road",
        city="Nairobi",
        country="KE",
        latitude=-1.2461,
        longitude=36.8023,
        departments=(DEPARTMENT_MATERNAL, DEPARTMENT_GENERAL),
        phone="+254 729 999 000",
        emergency=False,
        open_hours=None,
        notes="Maternity and children's hospital.",
    ),
    Facility(
        id="et-addis-black-lion",
        name="Tikur Anbessa Specialized Hospital",
        kind="hospital",
        address="Shendera Road",
        city="Addis Ababa",
        country="ET",
        latitude=9.0289,
        longitude=38.7603,
        departments=(
            DEPARTMENT_EMERGENCY,
            DEPARTMENT_GENERAL,
            DEPARTMENT_CARDIOLOGY,
            DEPARTMENT_RESPIRATORY,
        ),
        phone="+251 11 268 9600",
        emergency=True,
        open_hours="24 hours",
        notes="Largest medical referral centre in Ethiopia.",
    ),
    Facility(
        id="et-addis-stpeter",
        name="St. Peter's Hospital",
        kind="hospital",
        address="Menelik II Road",
        city="Addis Ababa",
        country="ET",
        latitude=9.0367,
        longitude=38.7472,
        departments=(DEPARTMENT_GENERAL, DEPARTMENT_MATERNAL),
        phone="+251 11 268 6100",
        emergency=False,
        open_hours=None,
        notes="General and maternity care.",
    ),
    Facility(
        id="ke-mombasa-cod",
        name="Coast General Hospital",
        kind="hospital",
        address="Mombasa Road",
        city="Mombasa",
        country="KE",
        latitude=-4.0435,
        longitude=39.6682,
        departments=(DEPARTMENT_EMERGENCY, DEPARTMENT_GENERAL),
        phone="+254 20 230 1000",
        emergency=True,
        open_hours="24 hours",
        notes="Coastal referral hospital.",
    ),
    Facility(
        id="et-addis-st-peter-extra",
        name="St. Peter Specialized Hospital",
        kind="hospital",
        address="Menelik II Road",
        city="Addis Ababa",
        country="ET",
        latitude=9.0300,
        longitude=38.7500,
        departments=(DEPARTMENT_GENERAL, DEPARTMENT_MATERNAL),
        phone="+251 11 268 6100",
        emergency=False,
        open_hours="8:00-17:00",
        notes="Extra test hospital 1.",
    ),
    Facility(
        id="et-addis-test-general",
        name="Endod Test General Hospital",
        kind="hospital",
        address="Bole Road",
        city="Addis Ababa",
        country="ET",
        latitude=9.0200,
        longitude=38.7600,
        departments=(DEPARTMENT_GENERAL, DEPARTMENT_EMERGENCY),
        phone="+251 11 123 4567",
        emergency=True,
        open_hours="24 hours",
        notes="Extra test hospital 2.",
    ),
)


def get_facility(facility_id: str) -> Optional[Facility]:
    """A facility by id: a listed partner hospital, or a built-in sample one.

    Looked up directly (one query, not the whole directory). Sample
    facilities are found here even in production, so older appointments
    keep their names; browsing and booking only offer them outside it.
    """
    from dedan_platform import partners

    partner = partners.get(facility_id)
    if partner is not None:
        return _from_partner(partner)
    for facility in DIRECTORY:
        if facility.id == facility_id:
            return facility
    return None


EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres.

    Used for ranking, not for navigation instructions: the result is accurate to
    a few percent, which is well inside the error of the geolocation we accept.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


# Red-flag language -> the department that can actually treat it. Keyed on
# substrings the deterministic scanner already looks for, plus plain symptom
# words, because care navigation is reached with whatever the patient said.
EMERGENCY_KEYWORDS = (
    "chest pain", "difficulty breathing", "cannot breathe", "unconscious",
    "slurred speech", "facial droop", "severe bleeding", "seizure",
    "fainting", "sudden vision loss", "stroke", "heart attack",
)

CARDIOLOGY_KEYWORDS = (
    "chest pain", "palpitation", "irregular heartbeat", "heart", "angina",
    "blood pressure",
)

RESPIRATORY_KEYWORDS = (
    "cough", "breathing", "shortness of breath", "wheezing", "asthma",
    "sore throat",
)

MATERNAL_KEYWORDS = ("pregnan", "pregnancy", "antenatal", "labour", "labor", "postpartum")
PEDIATRIC_KEYWORDS = ("child", "infant", "baby", "toddler", "paediatric", "pediatric")

DEPARTMENT_KEYWORDS: Dict[str, Sequence[str]] = {
    DEPARTMENT_EMERGENCY: EMERGENCY_KEYWORDS,
    DEPARTMENT_CARDIOLOGY: CARDIOLOGY_KEYWORDS,
    DEPARTMENT_RESPIRATORY: RESPIRATORY_KEYWORDS,
    DEPARTMENT_MATERNAL: MATERNAL_KEYWORDS,
    DEPARTMENT_PEDIATRIC: PEDIATRIC_KEYWORDS,
}


@dataclass
class ClinicalContext:
    """What the consultation established, handed to care navigation.

    `is_emergency` comes from the deterministic safety scanner, not from the
    model. Care navigation must never *infer* an emergency from prose alone --
    that is the safety layer's job and it has already run.
    """

    symptoms: List[str] = field(default_factory=list)
    is_emergency: bool = False
    urgency: str = "routine"
    language: str = "en"

    @property
    def text(self) -> str:
        return " ".join(self.symptoms).lower()


def required_departments(context: ClinicalContext) -> List[str]:
    """Departments this consultation needs, most important first.

    Emergency is a property of the *urgency*, not of the vocabulary: if the
    safety layer said this is an emergency, emergency care is required even if
    the patient described something as vague as "I feel terrible".
    """
    text = context.text
    needed: List[str] = []

    if context.is_emergency or context.urgency in ("emergency", "urgent"):
        needed.append(DEPARTMENT_EMERGENCY)

    for department, keywords in DEPARTMENT_KEYWORDS.items():
        if department == DEPARTMENT_EMERGENCY:
            continue
        if any(keyword in text for keyword in keywords):
            needed.append(department)
            break  # one matching specialty is enough to rank above pure distance

    if not needed:
        needed.append(DEPARTMENT_GENERAL)
    return needed


#: Weight of clinical fit versus proximity. Clinical fit dominates deliberately:
#: a 4 km detour to a facility that can treat the complaint beats the nearest
#: building that cannot.
RELEVANCE_WEIGHT = 0.72
DISTANCE_WEIGHT = 0.28

#: Distance (km) at which proximity alone would score zero. Beyond this a
#: journey is not "nearby" for a patient in distress.
DISTANCE_DECAY_KM = 25.0

#: Beyond this distance a facility is excluded outright when the patient's
#: location is known.
#:
#: Clinical fit dominating the score is correct *within* reach, but it must not
#: make a hospital 1,167 km away outrank a closer equivalent simply because both
#: have an emergency department. A patient in Nairobi cannot drive to Addis
#: Ababa, and a care-navigation list that suggests it is not navigation -- it is
#: noise. Without this gate, Tikur Anbessa scored 0.87 and ranked above nothing
#: purely on department match.
MAX_REACHABLE_KM = 150.0


@dataclass
class RankedFacility:
    facility: Facility
    distance_km: Optional[float]
    matched_departments: List[str]
    score: float
    reasons: List[str]

    def to_payload(self) -> Dict[str, Any]:
        data = self.facility.to_payload()
        data.update({
            "distance_km": round(self.distance_km, 2) if self.distance_km is not None else None,
            "matched_departments": self.matched_departments,
            "relevance_score": round(self.score, 4),
            "reasons": self.reasons,
        })
        return data


def rank_facilities(
    context: ClinicalContext,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    limit: int = 5,
) -> List[RankedFacility]:
    """Rank real facilities for this consultation.

    Latitude/longitude are optional and *permission-gated* upstream: when they
    are absent the ranking is by clinical relevance alone and the response says
    so, rather than implying a location the system does not have.
    """
    if limit < 1:
        raise CareNavigationError("limit must be at least 1.")

    needed = required_departments(context)
    ranked: List[RankedFacility] = []

    for facility in directory():
        matched = [dept for dept in needed if dept in facility.departments]
        # Facility fit: proportion of required departments it can serve.
        fit = len(matched) / len(needed)

        distance: Optional[float] = None
        if latitude is not None and longitude is not None:
            distance = haversine_km(latitude, longitude, facility.latitude, facility.longitude)
            # Out of reach: a perfect department match in another country is not a
            # recommendation, it is a distraction from the facilities the patient
            # can actually reach today.
            if distance > MAX_REACHABLE_KM:
                continue

        # Emergency-capable facilities get a bonus when urgency demands it: being
        # able to stabilise someone en route is worth more than a shorter drive.
        urgency_bonus = 0.0
        reasons: List[str] = []
        if (
            DEPARTMENT_EMERGENCY in needed
            and facility.emergency
            and DEPARTMENT_EMERGENCY in matched
        ):
            urgency_bonus = 0.15
            reasons.append("Has a 24-hour emergency service")

        if distance is None:
            proximity = 0.5
        else:
            proximity = max(0.0, 1.0 - (distance / DISTANCE_DECAY_KM))

        score = (RELEVANCE_WEIGHT * fit + DISTANCE_WEIGHT * proximity) + urgency_bonus

        if matched:
            reasons.append(f"Offers {'/'.join(matched).replace('_', ' ')}")
        if distance is not None:
            reasons.append(f"{distance:.1f} km away")
        if not facility.verified:
            reasons.append("Details not yet confirmed by an operator")
        if not reasons:
            # Every facility that reaches the patient must be able to justify its
            # own presence. A list entry with no reason is indistinguishable from
            # a filler, which is exactly what this product must never show.
            reasons.append(
                f"General care facility in {facility.city}"
                + (
                    f", {distance:.1f} km away"
                    if distance is not None
                    else ""
                )
            )

        ranked.append(
            RankedFacility(
                facility=facility,
                distance_km=distance,
                matched_departments=matched,
                score=score,
                reasons=reasons,
            )
        )

    ranked.sort(key=lambda item: (-item.score, item.distance_km or float("inf")))
    return ranked[:limit]


#: Documented so the UI can say *why* it cannot show slots rather than implying
#: the clinic is booked out.
AVAILABILITY_NOT_INTEGRATED = "no_availability_provider_configured"


def slots_for(
    facility: Facility,
    on_date: Optional[str] = None,
    provider: Optional[Any] = None,
) -> Dict[str, Any]:
    """Real availability for a facility, or an honest statement that there is none.

    This is the single most important function in the module for trust. When no
    availability provider is wired, the answer is `slots: []` with
    `available: False` and a machine-readable reason. It never returns a
    generated time.
    """
    if provider is not None:
        try:
            result = provider(facility, on_date)
        except Exception:
            logger.exception("availability_provider_failed", extra={"facility": facility.id})
            result = None
        if result:
            slots = result.get("slots") or []
            return {
                "facility_id": facility.id,
                "on_date": on_date,
                "available": bool(slots),
                "slots": slots,
                "source": result.get("source", "external_provider"),
                "confidence": result.get("confidence", "reported"),
                "note": result.get("note", "Availability as reported by the provider."),
            }

    # 24-hour emergency departments do have a real, verifiable fact we can state
    # without inventing anything: they are open. Worth surfacing even though we
    # cannot offer them a bookable appointment.
    if facility.emergency and facility.open_hours == "24 hours":
        return {
            "facility_id": facility.id,
            "on_date": on_date,
            "available": False,
            "slots": [],
            "source": "opening_hours",
            "confidence": "opening_hours_only",
            "walk_in_available": True,
            "note": (
                "Open 24 hours and accepts walk-in emergency patients. DEDAN has "
                "no live booking feed for this facility, so call ahead or present "
                "yourself directly in an emergency."
            ),
        }

    return {
        "facility_id": facility.id,
        "on_date": on_date,
        "available": False,
        "slots": [],
        "source": AVAILABILITY_NOT_INTEGRATED,
        "confidence": "unknown",
        "note": (
            f"{facility.name} does not yet publish live appointment availability "
            "to DEDAN. Call the facility using the number shown, or ask a "
            "clinician to arrange a referral."
        ),
    }


BROWSE_SORTS = ("name", "distance")


def browse(
    country: Optional[str] = None,
    city: Optional[str] = None,
    department: Optional[str] = None,
    emergency_only: bool = False,
    query: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    sort: str = "name",
    limit: int = 50,
) -> Dict[str, Any]:
    """The directory as a filterable list, for the facility browse screen.

    Unlike `search`, nothing is ranked by clinical fit: this is the patient
    looking around. Distance is given (and can be sorted on) only when the
    patient shared coordinates. The directory carries no ratings or wait
    times, and none are invented.
    """
    if sort not in BROWSE_SORTS:
        raise CareNavigationError(f"sort must be one of {list(BROWSE_SORTS)}.")
    if department is not None and department not in DEPARTMENTS:
        raise CareNavigationError(f"department must be one of {list(DEPARTMENTS)}.")
    location_used = latitude is not None and longitude is not None
    if sort == "distance" and not location_used:
        raise CareNavigationError("Sorting by distance needs your location.")
    needle = (query or "").strip().lower()
    city = (city or "").strip().lower()

    rows = []
    for facility in directory():
        if country and facility.country != country.upper():
            continue
        if city and facility.city.lower() != city:
            continue
        if department and department not in facility.departments:
            continue
        if emergency_only and not facility.emergency:
            continue
        if needle and not any(
            needle in text.lower() for text in (facility.name, facility.city, facility.address)
        ):
            continue
        payload = facility.to_payload()
        payload["distance_km"] = (
            round(haversine_km(latitude, longitude, facility.latitude, facility.longitude), 1)
            if location_used else None
        )
        rows.append(payload)

    if sort == "distance":
        rows.sort(key=lambda r: (r["distance_km"], r["name"]))
    else:
        rows.sort(key=lambda r: r["name"].lower())
    return {
        "facilities": rows[: max(1, min(limit, 100))],
        "total": len(rows),
        "location_used": location_used,
        "directory_version": DIRECTORY_VERSION,
        "departments": list(DEPARTMENTS),
    }


def search(
    context: ClinicalContext,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    limit: int = 5,
    query: Optional[str] = None,
    country: Optional[str] = None,
) -> Dict[str, Any]:
    """Care-navigation payload for the consultation.

    `location_used` is explicit: the patient is told whether their coordinates
    were used, and if not, why ranking fell back to relevance alone.
    """
    if limit < 1:
        raise CareNavigationError("limit must be at least 1.")
    # Rank everything, filter, then cut to `limit`: filtering after the cut
    # dropped matches that ranked just below it.
    ranked = rank_facilities(
        context, latitude=latitude, longitude=longitude, limit=len(directory()),
    )
    if country:
        ranked = [item for item in ranked if item.facility.country == country.upper()]
    query_matched = None

    if query:
        needle = query.strip().lower()
        if needle:
            filtered = [
                item for item in ranked
                if needle in item.facility.name.lower()
                or needle in item.facility.city.lower()
                or needle in item.facility.address.lower()
            ]
            # No match falls back to the ranked list, but says so.
            query_matched = bool(filtered)
            ranked = filtered or ranked
    ranked = ranked[:limit]

    location_used = latitude is not None and longitude is not None
    return {
        "required_departments": required_departments(context),
        "location_used": location_used,
        "facilities": [item.to_payload() for item in ranked],
        "query_matched": query_matched,
        "directory_version": DIRECTORY_VERSION,
        "directory_source": FACILITY_SOURCE,
        "directory_source_note": FACILITY_SOURCE_NOTE,
        "note": (
            "Facilities are ranked by clinical fit first and distance second."
            if location_used
            else "No location was shared, so facilities are ranked by clinical fit only."
        ),
        "urgency": context.urgency,
        "is_emergency": context.is_emergency,
    }
