"""
Enhanced Safety Validator — DEDAN Health 2.0

Validates AI responses for medical safety.
Never silently downgrades urgency. Always escalates when uncertain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, TYPE_CHECKING

import clinical_triage

if TYPE_CHECKING:
    from providers.models import AnalysisResponse, PatientProfile as ProviderPatientProfile


@dataclass
class SafetyCheckResult:
    is_safe: bool
    urgency_override: Optional[str] = None
    additional_flags: List[str] = field(default_factory=list)
    requires_professional_review: bool = False
    emergency_message: Optional[str] = None


class SafetyValidator:
    """
    Validates AI responses for medical safety.
    Never silently downgrades urgency. Always escalates when uncertain.
    """

    # Red-flag symptom rules live in `clinical_triage`, shared with the
    # offline provider, so the two can never disagree about an emergency.

    HIGH_RISK_PATIENT_FLAGS = [
        "pregnant", "pregnancy",
        "infant", "newborn", "baby", "child", "pediatric",
        "elderly", "geriatric", "over 75", "over 80",
        "immunocompromised", "immunosuppressed", "hiv", "aids", "chemotherapy",
        "cancer", "malignancy",
        "diabetes", "diabetic",
        "heart disease", "heart failure", "hypertension",
        "stroke", "tia",
        "kidney disease", "renal failure",
        "liver disease", "cirrhosis",
        "on blood thinners", "anticoagulant", "warfarin",
    ]

    #: Conditions that make any infection more dangerous: never "routine".
    IMMUNOCOMPROMISED_FLAGS = frozenset({
        "immunocompromised", "immunosuppressed", "hiv", "aids", "chemotherapy",
        "cancer", "malignancy",
    })

    #: Below this the model's answer is never treated as reassurance.
    VERY_LOW_CONFIDENCE = 0.4

    UNCERTAINTY_INDICATORS = [
        "cannot determine", "unclear", "insufficient", "need better image",
        "blurry", "dark", "poor quality", "not visible", "cannot see",
        "uncertain", "ambiguous", "insufficient information", "limited view",
    ]

    def __init__(self, confidence_threshold: float = 0.7):
        self.confidence_threshold = confidence_threshold

    async def validate_async(
        self,
        response: "AnalysisResponse",
        context: Optional["ProviderPatientProfile"] = None,
        original_text: str = "",
    ) -> SafetyCheckResult:
        """
        Validate response for safety. Returns safety check result with any overrides.
        """
        result = SafetyCheckResult(is_safe=True)
        current = response.urgency
        target = current

        def escalate(urgency: str, flag: str) -> None:
            nonlocal target
            result.additional_flags.append(flag)
            result.requires_professional_review = True
            target = clinical_triage.max_urgency(target, urgency)

        # 1. Red-flag rules on the patient's own words. The model's output is
        #    not scanned: advice such as "seek care if chest pain develops"
        #    must not turn into an emergency.
        triage = clinical_triage.assess(
            original_text,
            age_years=context.age if context else None,
            pregnant=bool(context and context.pregnancy_status),
        )
        result.additional_flags.extend(f"triage:{reason}" for reason in triage.reasons)
        if triage.reasons:
            escalate(triage.urgency, f"triage_urgency:{triage.urgency}")

        # 2. High-risk patients are never told "routine": at least see a
        #    clinician soon.
        if context:
            if context.age is not None and context.age < 5:
                escalate("see_doctor_soon", "high_risk_patient:young_child")
            if context.age is not None and context.age >= 75:
                escalate("see_doctor_soon", "high_risk_patient:older_adult")
            if context.pregnancy_status:
                escalate("see_doctor_soon", "high_risk_patient:pregnant")
            conditions = " ".join(
                str(item) for item in (context.chronic_conditions or []) + (context.medications or [])
            ).lower()
            for flag in self.HIGH_RISK_PATIENT_FLAGS:
                if flag in conditions:
                    immunocompromised = flag in self.IMMUNOCOMPROMISED_FLAGS
                    floor = "see_doctor_soon" if immunocompromised or target == "self_care" else "routine"
                    escalate(floor, f"high_risk_patient:{flag}")
                    break

        # 3. The model is unsure of its own answer.
        if response.uncertainty:
            uncertainty_lower = response.uncertainty.lower()
            for indicator in self.UNCERTAINTY_INDICATORS:
                if indicator in uncertainty_lower:
                    floor = "see_doctor_soon" if target == "self_care" else "routine"
                    escalate(floor, f"ai_uncertainty:{indicator}")
                    break

        # 4. Low confidence. Very low confidence is never reassurance.
        if response.confidence_score < self.confidence_threshold:
            result.additional_flags.append(f"low_confidence:{response.confidence_score:.2f}")
            result.requires_professional_review = True
            if response.confidence_score < self.VERY_LOW_CONFIDENCE or target == "self_care":
                target = clinical_triage.max_urgency(target, "see_doctor_soon")

        # 5. Escalate only. Never lower what the model said.
        target = clinical_triage.max_urgency(current, target)
        if clinical_triage.urgency_rank(target) > clinical_triage.urgency_rank(current):
            result.urgency_override = target
        if target == "emergency":
            result.requires_professional_review = True
            result.emergency_message = "⚠️ " + clinical_triage.emergency_instructions(
                context.location if context else None
            )

        # 6. Ensure safety notice is present
        if not response.safety_notice:
            result.additional_flags.append("missing_safety_notice")

        # 7. Validate medical disclaimer language
        if not self._has_proper_disclaimer(response.safety_notice):
            result.additional_flags.append("inadequate_disclaimer")

        # 8. Check for inappropriate prescriptions
        if self._contains_prescription_details(response):
            result.additional_flags.append("inappropriate_prescription_details")
            result.requires_professional_review = True

        return result

    async def apply_safety_result_async(
        self,
        response: "AnalysisResponse",
        safety_result: SafetyCheckResult,
    ) -> "AnalysisResponse":
        """Apply safety check results to the response."""
        if safety_result.urgency_override:
            response.urgency = safety_result.urgency_override

        response.requires_professional_review = (
            response.requires_professional_review or safety_result.requires_professional_review
        )

        response.safety_flags.extend(safety_result.additional_flags)

        if safety_result.emergency_message:
            if response.safety_notice:
                response.safety_notice = safety_result.emergency_message + "\n\n" + response.safety_notice
            else:
                response.safety_notice = safety_result.emergency_message

        return response

    def _get_emergency_number(self, context: Optional[ProviderPatientProfile]) -> str:
        """Get emergency number based on location."""
        return clinical_triage.emergency_number(context.location if context else None)

    def _has_proper_disclaimer(self, notice: str) -> bool:
        """Check if safety notice contains required disclaimer elements."""
        if not notice:
            return False
        notice_lower = notice.lower()
        required_elements = [
            "not a diagnosis" in notice_lower or "not a medical diagnosis" in notice_lower,
            "professional" in notice_lower or "healthcare" in notice_lower,
            "emergency" in notice_lower or "urgent" in notice_lower,
        ]
        return all(required_elements)

    def _contains_prescription_details(self, response: AnalysisResponse) -> bool:
        """Check if response inappropriately contains specific dosages or brand names."""
        text_to_check = " ".join([
            response.recommended_next_step,
            response.uncertainty,
            str(response.medical_information),
            str(response.treatment_information),
        ]).lower()

        dosage_patterns = [
            r"\d+\s*mg", r"\d+\s*ml", r"\d+\s*tablet", r"\d+\s*capsule",
            r"take \d+", r"dose of \d+", r"\d+ times daily", r"\d+ times a day",
            r"every \d+ hours", r"\d+ hourly",
        ]

        for pattern in dosage_patterns:
            if re.search(pattern, text_to_check):
                return True

        brand_names = [
            "tylenol", "advil", "motrin", "aleve", "aspirin", "panadol",
            "amoxicillin", "azithromycin", "ciprofloxacin", "metronidazole",
            "coartem", "malarone", "loroquine", "primaquine",
            "paracetamol", "ibuprofen", "diclofenac", "naproxen",
        ]

        for brand in brand_names:
            if f"take {brand}" in text_to_check or f"prescribe {brand}" in text_to_check:
                return True

        return False


# Global validator instance
safety_validator = SafetyValidator()