"""
Response Transformer — DEDAN Health 2.0

Transforms AI provider response into structured clinical response
using the ClinicalResponse schema.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, TYPE_CHECKING

import clinical_triage
from clinical_schema import (
    ClinicalResponse, HealthSummary, SafetyClassification,
    PossibleExplanation, UncertaintyStatement, TreatmentEducation,
    MedicationInfo, VisualEducation, Source, UrgencyLevel,
    EvidenceLevel, Observation,
)

if TYPE_CHECKING:
    from providers.models import AnalysisResponse, PatientContext as ProviderPatientContext


def _as_dict(item: Any) -> Dict[str, Any]:
    """Provider items arrive as pydantic models; older code paths pass dicts.

    Every builder used to check `isinstance(item, dict)` and skip the rest, so
    the typed items real providers return were all discarded.
    """
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return {}


#: Provider evidence grades (A-D) -> the patient-facing scale.
_EVIDENCE_GRADES = {
    "a": EvidenceLevel.STRONG,
    "b": EvidenceLevel.MODERATE,
    "c": EvidenceLevel.LIMITED,
    "d": EvidenceLevel.THEORETICAL,
    # The schema's weakest level. (Code here referred to a non-existent
    # EvidenceLevel.EXPERT_OPINION, which silently broke the first-aid path.)
    "expert_opinion": EvidenceLevel.THEORETICAL,
    **{level.value: level for level in EvidenceLevel},
}


def _evidence_from_confidence(confidence: Any) -> EvidenceLevel:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return EvidenceLevel.THEORETICAL
    if value >= 0.75:
        return EvidenceLevel.MODERATE
    if value >= 0.4:
        return EvidenceLevel.LIMITED
    return EvidenceLevel.THEORETICAL


_DEFAULT_MORE_INFO = ["Physical examination", "Laboratory tests", "Detailed history"]

#: Doses, amounts and schedules. Treatment text is education: anything that
#: reads as a prescription is replaced, wherever the model put it.
_DOSE_PATTERNS = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:mg|mcg|µg|g|ml|iu|units?|tablets?|capsules?|pills?|drops?|puffs?|teaspoons?|tsp)\b"
    r"|\b(?:once|twice|thrice|\d+\s*(?:x|times))\s*(?:a|per)?\s*(?:day|daily|week)\b"
    r"|\bevery\s+\d+\s*(?:-\s*\d+\s*)?hours?\b"
    r"|\b\d+\s*(?:x|times)\s*daily\b",
    re.IGNORECASE,
)
_DOSE_REPLACEMENT = "[dose: ask a clinician or pharmacist]"


_REPEATED_REPLACEMENT = re.compile(r"(?:" + re.escape(_DOSE_REPLACEMENT) + r"[\s,;]*){2,}")


def _without_doses(text: str) -> str:
    redacted = _DOSE_PATTERNS.sub(_DOSE_REPLACEMENT, text or "")
    # "500 mg twice a day" -> one notice, not two.
    return _REPEATED_REPLACEMENT.sub(_DOSE_REPLACEMENT + " ", redacted).strip()


class ResponseTransformer:
    """Transforms AI provider response into structured clinical response."""

    # Standard disclaimer
    DISCLAIMER_FULL = (
        "IMPORTANT MEDICAL DISCLAIMER: DEDAN Health provides AI-generated health information "
        "for educational and informational purposes only. This service does not provide medical "
        "diagnoses, treatment recommendations, or professional medical advice. The analysis is "
        "based on the information you provided and may be incomplete or inaccurate. "
        "NEVER use this information as a substitute for professional medical evaluation, diagnosis, "
        "or treatment. ALWAYS consult a qualified healthcare professional (doctor, clinical officer, "
        "nurse, or pharmacist) for any health concerns, especially if symptoms are severe, worsening, "
        "or persistent. In case of medical emergency, call your local emergency number immediately. "
        "DEDAN Health and its providers are not liable for any decisions made based on this information."
    )

    DISCLAIMER_SHORT = (
        "This is AI-generated health information, not a medical diagnosis. "
        "Always consult a qualified healthcare professional for medical concerns."
    )

    def __init__(self, country_code: str = "KE"):
        self.country_code = country_code.upper()

    def transform(
        self,
        ai_response: "AnalysisResponse",
        clinical_context=None,
        request_id: str = "",
        session_id: str = "",
    ) -> ClinicalResponse:
        """Transform AI response into structured clinical response."""

        # Parse structured data from medical_information
        parsed_data = self._parse_medical_info(ai_response.medical_information)

        # Build health summary
        health_summary = self._build_health_summary(parsed_data, clinical_context, ai_response)

        # Build safety classification
        safety = self._build_safety(ai_response, clinical_context)

        # Build possible conditions
        possible_explanations = self._build_possible_explanations(parsed_data, ai_response)

        # Build uncertainty statement
        uncertainty = self._build_uncertainty(parsed_data, ai_response)

        # Build treatment education
        treatment_education = self._build_treatment_education(parsed_data, ai_response)

        # Build medication information
        medication_information = self._build_medication_information(parsed_data)

        # Build visual education (will be enhanced separately)
        visual_education = self._build_visual_education(parsed_data)

        # Build follow-up
        follow_up = self._build_follow_up(parsed_data, ai_response)

        # Build sources
        sources = self._build_sources(parsed_data, ai_response)

        # Build disclaimer
        disclaimer = self.DISCLAIMER_FULL

        return ClinicalResponse(
            response_id=request_id or str(uuid.uuid4()),
            session_id=session_id or str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            health_summary=health_summary,
            safety=safety,
            possible_explanations=possible_explanations,
            uncertainty=uncertainty,
            treatment_education=treatment_education,
            medication_information=medication_information,
            visual_education=visual_education,
            follow_up=follow_up,
            sources=sources,
            professional_review=ai_response.requires_professional_review,
            provider=ai_response.provider,
            model=ai_response.model,
            confidence_score=ai_response.confidence_score,
            disclaimer=disclaimer,
        )

    def _parse_medical_info(self, medical_info: List[Any]) -> Dict[str, Any]:
        """Parse structured data from medical_information list."""
        result = {
            "possible_conditions": [],
            "first_aid_steps": [],
            "what_to_tell_doctor": {},
            "recommended_medicine_class": None,
            "pharmacy_guidance": None,
            "symptom_analysis": {},
            "body_mechanism": [],
            "treatment_approach": {},
        }

        for item in medical_info:
            # Handle both dict and Pydantic model objects
            if hasattr(item, 'get'):
                topic = item.get("topic", "")
                content = item.get("content", "")
            else:
                # Pydantic model - use attribute access
                topic = getattr(item, "topic", "")
                content = getattr(item, "content", "")

            try:
                if topic == "possible_conditions":
                    result["possible_conditions"] = json.loads(content)
                elif topic == "first_aid":
                    result["first_aid_steps"] = json.loads(content)
                elif topic == "doctor_communication":
                    result["what_to_tell_doctor"] = json.loads(content)
                elif topic == "medicine_class":
                    result["recommended_medicine_class"] = json.loads(content)
                elif topic == "pharmacy_guidance":
                    result["pharmacy_guidance"] = json.loads(content)
                elif topic == "full_analysis":
                    # Fallback: parse everything from full analysis
                    full = json.loads(content)
                    result["possible_conditions"] = full.get("possible_conditions", [])
                    result["first_aid_steps"] = full.get("first_aid_steps", [])
                    result["what_to_tell_doctor"] = full.get("what_to_tell_doctor", {})
                    result["recommended_medicine_class"] = full.get("recommended_medicine_class")
                    result["pharmacy_guidance"] = full.get("pharmacy_guidance")
            except (json.JSONDecodeError, TypeError):
                continue

        return result

    def _build_health_summary(self, parsed: Dict[str, Any], clinical_context, ai_response: "AnalysisResponse") -> HealthSummary:
        """Build health summary from parsed data and context."""
        symptoms = []
        if clinical_context and clinical_context.symptoms:
            symptoms = [clinical_context.symptoms.symptoms] if clinical_context.symptoms.symptoms else []
        
        duration = "Not specified"
        severity = "Not specified"
        if clinical_context and clinical_context.symptoms:
            duration = clinical_context.symptoms.duration or "Not specified"
            severity = clinical_context.symptoms.severity or "Not specified"
        
        relevant_history = []
        if clinical_context and clinical_context.patient_profile:
            if clinical_context.patient_profile.chronic_conditions:
                relevant_history.extend([f"Chronic: {c}" for c in clinical_context.patient_profile.chronic_conditions])
            if clinical_context.patient_profile.medications:
                relevant_history.extend([f"Medication: {m}" for m in clinical_context.patient_profile.medications])
            if clinical_context.patient_profile.allergies:
                relevant_history.extend([f"Allergy: {a}" for a in clinical_context.patient_profile.allergies])

        return HealthSummary(
            duration=duration,
            severity=severity,
            symptoms=symptoms,
            relevant_history=relevant_history,
            images_provided=bool(ai_response.image_assessment),
            other_information={
                "ai_confidence": ai_response.confidence_score,
                "processing_time_ms": ai_response.processing_time_ms,
            },
        )

    def _build_safety(self, ai_response: "AnalysisResponse", clinical_context) -> SafetyClassification:
        """Build safety classification from AI response."""
        urgency_map = {
            "emergency": UrgencyLevel.EMERGENCY,
            "urgent": UrgencyLevel.URGENT,
            "see_doctor_soon": UrgencyLevel.SOON,
            "routine": UrgencyLevel.ROUTINE,
            "self_care": UrgencyLevel.ROUTINE,
        }
        
        # Unknown labels ("critical", "EMERGENCY - call now") are normalised by
        # rank rather than defaulted, so they can never read as reassurance.
        urgency = urgency_map[clinical_triage.max_urgency(ai_response.urgency)]
        
        return SafetyClassification(
            urgency=urgency,
            recommended_action=ai_response.recommended_next_step,
            red_flags=ai_response.safety_flags,
            requires_immediate_care=urgency == UrgencyLevel.EMERGENCY,
            emergency_message=ai_response.safety_notice if urgency == UrgencyLevel.EMERGENCY else None,
            professional_review_required=ai_response.requires_professional_review,
        )

    def _build_possible_explanations(
        self, parsed: Dict[str, Any], ai_response: Optional["AnalysisResponse"] = None
    ) -> List[PossibleExplanation]:
        """Build possible explanations: the provider's differential first, then
        any embedded JSON (`possible_conditions`), then image findings."""
        explanations: List[PossibleExplanation] = []
        seen = set()

        provider_items = list(getattr(ai_response, "possible_explanations", None) or [])
        image = getattr(ai_response, "image_assessment", None)
        if image is not None:
            provider_items.extend(getattr(image, "possible_explanations", None) or [])
        for item in provider_items:
            exp = _as_dict(item)
            label = (exp.get("condition") or "").strip()
            if not label or label.lower() in seen:
                continue
            seen.add(label.lower())
            observations = [str(o) for o in (exp.get("supporting_observations") or []) if o]
            why = exp.get("reasoning") or "Matches part of what you described."
            if observations:
                why = f"{why} (You mentioned: {'; '.join(observations[:3])}.)"
            explanations.append(PossibleExplanation(
                label=label,
                why_it_fits=why,
                what_does_not_fit="Needs a clinician's examination to confirm or rule out.",
                evidence_level=_evidence_from_confidence(exp.get("confidence")),
                requires_more_info=list(_DEFAULT_MORE_INFO),
            ))

        for c in parsed.get("possible_conditions", []):
            if not isinstance(c, dict):
                continue
            
            # Map confidence string to enum
            conf_str = c.get("confidence", "low").lower()
            confidence = EvidenceLevel.MODERATE
            if conf_str == "high":
                confidence = EvidenceLevel.STRONG
            elif conf_str == "medium":
                confidence = EvidenceLevel.MODERATE
            elif conf_str == "low":
                confidence = EvidenceLevel.LIMITED

            if (c.get("name") or "").lower() in seen:
                continue
            explanations.append(PossibleExplanation(
                label=c.get("name", "Unknown condition"),
                why_it_fits=c.get("reasoning", "Based on reported symptoms and analysis"),
                what_does_not_fit=c.get("contradicting_evidence", ["Insufficient information to confirm"])[0] if c.get("contradicting_evidence") else "Insufficient information to confirm",
                evidence_level=confidence,
                requires_more_info=c.get("requires_more_info", ["Physical examination", "Laboratory tests", "Detailed history"]),
            ))

        # If no conditions from AI, add generic entry
        if not explanations:
            explanations.append(PossibleExplanation(
                label="Undetermined - requires professional evaluation",
                why_it_fits="Insufficient information to suggest specific conditions",
                what_does_not_fit="No specific findings to support a diagnosis",
                evidence_level=EvidenceLevel.THEORETICAL,
                requires_more_info=["Physical examination", "Laboratory tests", "Detailed history"],
            ))

        return explanations

    def _build_uncertainty(self, parsed: Dict[str, Any], ai_response: "AnalysisResponse") -> UncertaintyStatement:
        """Build uncertainty statement."""
        uncertainty_msg = ai_response.uncertainty or "There is not enough information to determine the exact cause."
        
        missing_info = []
        for c in parsed.get("possible_conditions", []):
            if isinstance(c, dict) and c.get("requires_more_info"):
                missing_info.extend(c["requires_more_info"])
        
        # Deduplicate
        missing_info = list(dict.fromkeys(missing_info))
        if not missing_info:
            missing_info = ["Temperature", "Duration of specific symptoms", "Past medical history"]

        return UncertaintyStatement(
            message=uncertainty_msg,
            level="moderate" if ai_response.confidence_score < 0.7 else "low",
            missing_information=missing_info,
        )

    def _build_treatment_education(self, parsed: Dict[str, Any], ai_response: "AnalysisResponse") -> List[TreatmentEducation]:
        """Build treatment education from parsed data."""
        education = []
        
        # From AI response treatment information
        for raw in ai_response.treatment_information:
            item = _as_dict(raw)
            if item.get("intervention") and item.get("intervention") != "first_aid":
                # Dosage is deliberately not carried over: DEDAN gives
                # education, never prescriptions.
                source_title = item.get("source") or ""
                description = _without_doses(item.get("description") or "")
                contraindications = [_without_doses(str(c)) for c in (item.get("contraindications") or []) if c]
                if contraindications:
                    description = (
                        f"{description} Not suitable for everyone, for example: "
                        f"{'; '.join(contraindications)}. Ask a clinician first."
                    ).strip()
                education.append(TreatmentEducation(
                    category="clinical_care",
                    title=_without_doses(item["intervention"]),
                    description=description,
                    why_it_may_help=(
                        f"Commonly used for {item['condition']}." if item.get("condition")
                        else "Commonly used for this kind of problem."
                    ),
                    expected_timeline="Ask your clinician",
                    what_to_monitor=_without_doses("; ".join(item.get("precautions") or [])) or "How your symptoms change",
                    when_to_reassess="If symptoms worsen or do not improve",
                    evidence_level=_EVIDENCE_GRADES.get(
                        str(item.get("evidence_level", "")).lower(), EvidenceLevel.THEORETICAL
                    ),
                    sources=[Source(title=source_title, url="", type="guideline")] if source_title else [],
                ))
                continue
            if item.get("intervention") == "first_aid":
                try:
                    first_aid = json.loads(item.get("description", "[]"))
                    for i, step in enumerate(first_aid, 1):
                        if isinstance(step, dict):
                            education.append(TreatmentEducation(
                                category=step.get("category", "self_care"),
                                title=step.get("title", f"Step {i}"),
                                description=step.get("description", ""),
                                why_it_may_help=step.get("why_it_may_help", "Supports recovery"),
                                expected_timeline=step.get("expected_timeline", "Variable"),
                                what_to_monitor=step.get("what_to_monitor", "Symptom progression"),
                                when_to_reassess=step.get("when_to_reassess", "If symptoms worsen"),
                                evidence_level=EvidenceLevel.THEORETICAL,
                            ))
                except:
                    pass
        
        # From parsed treatment_education
        for te in parsed.get("treatment_education", []):
            if isinstance(te, dict):
                education.append(TreatmentEducation(
                    category=te.get("category", "self_care"),
                    title=te.get("title", "Treatment"),
                    description=te.get("description", ""),
                    why_it_may_help=te.get("why_it_may_help", ""),
                    expected_timeline=te.get("expected_timeline", "Variable"),
                    what_to_monitor=te.get("what_to_monitor", "Symptoms"),
                    when_to_reassess=te.get("when_to_reassess", "If not improving"),
                    evidence_level=_EVIDENCE_GRADES.get(
                        str(te.get("evidence_level", "")).lower(), EvidenceLevel.THEORETICAL
                    ),
                    sources=[
                        Source(title=s.get("title", ""), url=s.get("url", ""), type=s.get("type", ""), jurisdiction=s.get("jurisdiction", ""))
                        for s in te.get("sources", [])
                    ],
                ))
        
        # Default if empty
        if not education:
            education.append(TreatmentEducation(
                category="self_care",
                title="Rest and hydration",
                description="Rest and stay hydrated are commonly recommended for acute illnesses",
                why_it_may_help="Supports the immune system and prevents dehydration",
                expected_timeline="Improvement within 3-7 days for viral illnesses",
                what_to_monitor="Temperature, breathing, symptom progression",
                when_to_reassess="If symptoms worsen or do not improve in 7 days",
                evidence_level=EvidenceLevel.STRONG,
            ))
        
        return education

    def _build_medication_information(self, parsed: Dict[str, Any]) -> List[MedicationInfo]:
        """Build medication information from parsed data."""
        medications = []
        
        med_data = parsed.get("recommended_medicine_class")
        if med_data and isinstance(med_data, dict):
            medications.append(MedicationInfo(
                medication_name=med_data.get("medicine_class", "Not specified"),
                medication_class=med_data.get("medicine_class", "Not specified"),
                general_purpose=med_data.get("indication", ""),
                common_warnings=med_data.get("important_warnings", [
                    "Only take medications prescribed by a qualified healthcare professional",
                    "Follow dosage instructions exactly as prescribed",
                    "Inform your doctor of all other medications you are taking",
                    "Report any side effects immediately",
                ]),
                contraindication_categories=med_data.get("contraindications", []),
                potential_interactions=med_data.get("interactions", []),
                questions_to_ask=med_data.get("questions_to_ask", [
                    "What is the correct dose for my age?",
                    "Are there interactions with my other medications?",
                ]),
                package_check_items=med_data.get("package_check_items", [
                    "Active ingredient", "Strength", "Warnings", "Expiration date"
                ]),
                source=Source(
                    title=med_data.get("source_guideline", "WHO/National guidelines"),
                    url="https://www.who.int/medicines",
                    type="guideline",
                    jurisdiction="WHO",
                ),
                is_educational_only=True,
            ))
        
        return medications

    def _build_visual_education(self, parsed: Dict[str, Any]) -> List[VisualEducation]:
        """Build visual education from parsed data (will be enhanced separately)."""
        visuals = []
        for ve in parsed.get("visual_education", []):
            if isinstance(ve, dict):
                visuals.append(VisualEducation(
                    title=ve.get("title", "Educational visual"),
                    description=ve.get("description", ""),
                    visual_type=ve.get("visual_type", "illustration"),
                    source=ve.get("source", "Educational source"),
                    source_url=ve.get("source_url"),
                    license=ve.get("license"),
                    medical_context=ve.get("medical_context", "Educational reference"),
                    publication_info=ve.get("publication_info"),
                    is_ai_generated=ve.get("is_ai_generated", False),
                    ai_disclaimer=ve.get("ai_disclaimer"),
                ))
        return visuals

    def _build_follow_up(self, parsed: Dict[str, Any], ai_response: "AnalysisResponse") -> Dict[str, Any]:
        """Build follow-up guidance."""
        follow_up = parsed.get("follow_up", {})
        
        warning_signs = ai_response.warning_signs or [
            "Difficulty breathing",
            "Chest pain",
            "High fever",
            "Confusion",
            "Worsening symptoms",
        ]
        
        return {
            "recommended": follow_up.get("recommended", True),
            "timeframe": follow_up.get("timeframe", "3-7 days if symptoms persist"),
            "warning_signs": warning_signs,
        }

    def _build_sources(self, parsed: Dict[str, Any], ai_response: "AnalysisResponse") -> List[Source]:
        """Build sources from parsed data and AI response."""
        sources = []
        
        # From AI response
        for raw in ai_response.sources:
            src = _as_dict(raw)
            # A citation the patient cannot open is not a citation.
            if src.get("title") and str(src.get("url") or "").startswith(("https://", "http://")):
                sources.append(Source(
                    title=src["title"],
                    url=src.get("url") or "",
                    type=src.get("type") or "ai_analysis",
                    jurisdiction=src.get("jurisdiction") or "",
                    date_published=src.get("publication_date"),
                ))
        
        # From evidence retrieval
        for item in ai_response.medical_information:
            if isinstance(item, dict) and item.get("topic") == "full_analysis":
                try:
                    full = json.loads(item.get("content", "{}"))
                    for src in full.get("sources", []):
                        sources.append(Source(
                            title=src.get("title", ""),
                            url=src.get("url", ""),
                            type=src.get("type", "guideline"),
                            jurisdiction=src.get("jurisdiction", ""),
                        ))
                except:
                    pass
        
        # Default sources if none
        if not sources:
            sources.append(Source(
                title="WHO Guidelines",
                url="https://www.who.int/publications/guidelines",
                type="guideline",
                jurisdiction="WHO",
            ))
        
        return sources


# Global transformer instance
response_transformer = ResponseTransformer()