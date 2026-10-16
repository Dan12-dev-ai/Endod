"""
Clinical Response Schema — DEDAN Health 2.0

Structured response schema for AI-generated clinical information.
Separates educational content from personalized clinical recommendations.
Never allows the model to invent prescriptions or definitive diagnoses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class UrgencyLevel(str, Enum):
    """Safety classification levels."""
    ROUTINE = "routine"
    SOON = "soon"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class EvidenceLevel(str, Enum):
    """Strength of supporting evidence."""
    STRONG = "strong"
    MODERATE = "moderate"
    LIMITED = "limited"
    THEORETICAL = "theoretical"


@dataclass
class Source:
    """Evidence source citation."""
    title: str
    url: str
    type: str
    date_published: Optional[str] = None
    jurisdiction: Optional[str] = None


@dataclass
class UncertaintyStatement:
    """Explicit uncertainty disclosure."""
    message: str
    level: str
    missing_information: List[str] = field(default_factory=list)


@dataclass
class PossibleExplanation:
    """A possible explanation for reported symptoms."""
    label: str
    why_it_fits: str
    what_does_not_fit: str
    evidence_level: EvidenceLevel = EvidenceLevel.THEORETICAL
    requires_more_info: List[str] = field(default_factory=list)


@dataclass
class Observation:
    """An observed feature."""
    description: str
    category: str
    confidence: str
    source: str


@dataclass
class MedicationInfo:
    """Educational medication information — NOT a prescription."""
    medication_name: str
    medication_class: str
    general_purpose: str
    common_warnings: List[str] = field(default_factory=list)
    contraindication_categories: List[str] = field(default_factory=list)
    potential_interactions: List[str] = field(default_factory=list)
    questions_to_ask: List[str] = field(default_factory=list)
    package_check_items: List[str] = field(default_factory=list)
    source: Optional[Source] = None
    is_educational_only: bool = True


@dataclass
class TreatmentEducation:
    """Treatment education — explains approaches without prescribing."""
    category: str
    title: str
    description: str
    why_it_may_help: str
    expected_timeline: str
    what_to_monitor: str
    when_to_reassess: str
    evidence_level: EvidenceLevel = EvidenceLevel.THEORETICAL
    sources: List[Source] = field(default_factory=list)


@dataclass
class VisualEducation:
    """Educational visual reference."""
    title: str
    description: str
    visual_type: str
    source: str
    medical_context: str
    source_url: Optional[str] = None
    license: Optional[str] = None
    publication_info: Optional[str] = None
    is_ai_generated: bool = False
    ai_disclaimer: Optional[str] = None


@dataclass
class SafetyClassification:
    """Safety classification for the assessment."""
    urgency: UrgencyLevel
    recommended_action: str
    red_flags: List[str] = field(default_factory=list)
    requires_immediate_care: bool = False
    emergency_message: Optional[str] = None
    professional_review_required: bool = False


@dataclass
class HealthSummary:
    """Summary of what the patient reported."""
    duration: str
    severity: str
    symptoms: List[str] = field(default_factory=list)
    relevant_history: List[str] = field(default_factory=list)
    images_provided: bool = False
    other_information: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClinicalResponse:
    """
    Complete structured clinical response.

    Every field is explicitly qualified — never presents uncertainty as certainty.
    Safety-critical fields are always present.
    """
    response_id: str
    session_id: str
    timestamp: str
    health_summary: HealthSummary
    safety: SafetyClassification
    possible_explanations: List[PossibleExplanation]
    uncertainty: UncertaintyStatement
    treatment_education: List[TreatmentEducation]
    medication_information: List[MedicationInfo]
    medication_verification: List[MedicationVerificationItem] = field(default_factory=list)
    visual_education: List[VisualEducation] = field(default_factory=list)
    follow_up: Dict[str, Any] = field(default_factory=dict)
    warning_signs: List[str] = field(default_factory=list)
    next_steps: Dict[str, List[str]] = field(default_factory=dict)
    sources: List[Source] = field(default_factory=list)
    professional_review: bool = True
    professional_review_reason: Optional[str] = None
    provider: str = "gemini"
    model: str = "unknown"
    confidence_score: float = 0.0
    disclaimer: str = "This is AI-generated health information, not a diagnosis. Always consult a qualified healthcare professional."
    safety_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "response_id": self.response_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "health_summary": {
                "symptoms": self.health_summary.symptoms,
                "duration": self.health_summary.duration,
                "severity": self.health_summary.severity,
                "relevant_history": self.health_summary.relevant_history,
                "images_provided": self.health_summary.images_provided,
                "other_information": self.health_summary.other_information,
            },
            "safety": {
                "urgency": self.safety.urgency.value,
                "red_flags": self.safety.red_flags,
                "requires_immediate_care": self.safety.requires_immediate_care,
                "emergency_message": self.safety.emergency_message,
                "recommended_action": self.safety.recommended_action,
                "professional_review_required": self.safety.professional_review_required,
            },
            "possible_explanations": [
                {
                    "label": pe.label,
                    "why_it_fits": pe.why_it_fits,
                    "what_does_not_fit": pe.what_does_not_fit,
                    "evidence_level": pe.evidence_level.value,
                    "requires_more_info": pe.requires_more_info,
                }
                for pe in self.possible_explanations
            ],
            "uncertainty": {
                "message": self.uncertainty.message,
                "level": self.uncertainty.level,
                "missing_information": self.uncertainty.missing_information,
            },
            "treatment_education": [
                {
                    "category": te.category,
                    "title": te.title,
                    "description": te.description,
                    "why_it_may_help": te.why_it_may_help,
                    "expected_timeline": te.expected_timeline,
                    "what_to_monitor": te.what_to_monitor,
                    "when_to_reassess": te.when_to_reassess,
                    "evidence_level": te.evidence_level.value,
                    "sources": [
                        {"title": s.title, "url": s.url, "type": s.type, "jurisdiction": s.jurisdiction}
                        for s in te.sources
                    ],
                }
                for te in self.treatment_education
            ],
            "medication_information": [
                {
                    "medication_name": mi.medication_name,
                    "medication_class": mi.medication_class,
                    "general_purpose": mi.general_purpose,
                    "common_warnings": mi.common_warnings,
                    "contraindication_categories": mi.contraindication_categories,
                    "potential_interactions": mi.potential_interactions,
                    "questions_to_ask": mi.questions_to_ask,
                    "package_check_items": mi.package_check_items,
                    "is_educational_only": mi.is_educational_only,
                }
                for mi in self.medication_information
            ],
            "visual_education": [
                {
                    "title": ve.title,
                    "description": ve.description,
                    "visual_type": ve.visual_type,
                    "source": ve.source,
                    "medical_context": ve.medical_context,
                    "is_ai_generated": ve.is_ai_generated,
                    "ai_disclaimer": ve.ai_disclaimer,
                }
                for ve in self.visual_education
            ],
            "follow_up": self.follow_up,
            "sources": [
                {
                    "title": s.title,
                    "url": s.url,
                    "type": s.type,
                    "date_published": s.date_published,
                    "jurisdiction": s.jurisdiction,
                }
                for s in self.sources
            ],
            "professional_review": self.professional_review,
            "provider": self.provider,
            "model": self.model,
            "confidence_score": self.confidence_score,
            "disclaimer": self.disclaimer,
        }


@dataclass
class BodyMechanismStep:
    """A step in the body mechanism explanation chain."""
    step_number: int
    title: str
    description: str
    visual_reference: Optional[str] = None  # e.g., "normal_tissue", "inflamed_tissue"


@dataclass
class TreatmentApproach:
    """Structured treatment approach explanation."""
    goal: str  # What treatment is trying to achieve
    mechanism: str  # Why this approach is used (biological mechanism)
    patient_actions: List[str]  # What patient can generally do
    professional_actions: List[str]  # What requires clinician
    expected_improvement: str  # What improvement looks like
    timeline: str  # Evidence-based timeline
    warning_signs: List[str]  # Deterioration indicators
    evidence_level: EvidenceLevel = EvidenceLevel.THEORETICAL
    sources: List[Source] = field(default_factory=list)


@dataclass
class MedicationVerificationItem:
    """Item to verify at pharmacy."""
    field: str  # e.g., "active_ingredient", "strength", "expiry"
    description: str
    why_important: str


@dataclass
class PostAssessmentResponse:
    """
    Complete post-assessment AI health response.
    
    Transforms multimodal patient input into structured, evidence-grounded,
    highly understandable health explanation and care-navigation experience.
    """
    response_id: str
    session_id: str
    timestamp: str
    
    # Health Summary - "What did DEDAN understand?"
    health_summary: HealthSummary
    
    # Symptom Analysis - "What may be happening"
    symptom_analysis: Dict[str, Any]
    
    # Possible Explanations - qualified, not diagnoses
    possible_explanations: List[PossibleExplanation]
    
    # Image Analysis - separate observation from interpretation
    image_analysis: Optional[Dict[str, Any]] = None
    
    # Urgency Classification
    urgency: UrgencyLevel = UrgencyLevel.SOON
    requires_immediate_care: bool = False
    emergency_message: Optional[str] = None
    
    # Body Mechanism Explanation - "What is happening inside the body?"
    body_mechanism: List[BodyMechanismStep] = field(default_factory=list)
    
    # Treatment Education - structured approach
    treatment_approach: Optional[TreatmentApproach] = None
    treatment_education: List[TreatmentEducation] = field(default_factory=list)
    
    # Medication Information - educational only
    medication_information: List[MedicationInfo] = field(default_factory=list)
    medication_verification: List[MedicationVerificationItem] = field(default_factory=list)
    
    # Visual Education - real medical visuals
    visual_education: List[VisualEducation] = field(default_factory=list)
    
    # Warning Signs
    warning_signs: List[str] = field(default_factory=list)
    
    # Next Steps
    follow_up: Dict[str, Any] = field(default_factory=dict)
    next_steps: Dict[str, List[str]] = field(default_factory=dict)
    
    # Professional Escalation
    professional_review: bool = True
    professional_review_reason: Optional[str] = None
    
    # Sources
    sources: List[Source] = field(default_factory=list)
    
    # Metadata
    provider: str = "gemini"
    model: str = "unknown"
    confidence_score: float = 0.0
    disclaimer: str = "This is AI-generated health information, not a diagnosis. Always consult a qualified healthcare professional."
    uncertainty: Optional[UncertaintyStatement] = None
    safety_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "response_id": self.response_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "health_summary": {
                "symptoms": self.health_summary.symptoms,
                "duration": self.health_summary.duration,
                "severity": self.health_summary.severity,
                "relevant_history": self.health_summary.relevant_history,
                "images_provided": self.health_summary.images_provided,
                "other_information": self.health_summary.other_information,
            },
            "symptom_analysis": self.symptom_analysis,
            "possible_explanations": [
                {
                    "label": pe.label,
                    "why_it_fits": pe.why_it_fits,
                    "what_does_not_fit": pe.what_does_not_fit,
                    "evidence_level": pe.evidence_level.value,
                    "requires_more_info": pe.requires_more_info,
                }
                for pe in self.possible_explanations
            ],
            "image_analysis": self.image_analysis,
            "urgency": self.urgency.value,
            "requires_immediate_care": self.requires_immediate_care,
            "emergency_message": self.emergency_message,
            "body_mechanism": [
                {
                    "step_number": bm.step_number,
                    "title": bm.title,
                    "description": bm.description,
                    "visual_reference": bm.visual_reference,
                }
                for bm in self.body_mechanism
            ],
            "treatment_approach": {
                "goal": self.treatment_approach.goal if self.treatment_approach else "",
                "mechanism": self.treatment_approach.mechanism if self.treatment_approach else "",
                "patient_actions": self.treatment_approach.patient_actions if self.treatment_approach else [],
                "professional_actions": self.treatment_approach.professional_actions if self.treatment_approach else [],
                "expected_improvement": self.treatment_approach.expected_improvement if self.treatment_approach else "",
                "timeline": self.treatment_approach.timeline if self.treatment_approach else "",
                "warning_signs": self.treatment_approach.warning_signs if self.treatment_approach else [],
                "evidence_level": self.treatment_approach.evidence_level.value if self.treatment_approach else EvidenceLevel.THEORETICAL.value,
                "sources": [
                    {"title": s.title, "url": s.url, "type": s.type, "jurisdiction": s.jurisdiction}
                    for s in (self.treatment_approach.sources if self.treatment_approach else [])
                ],
            } if self.treatment_approach else None,
            "treatment_education": [
                {
                    "category": te.category,
                    "title": te.title,
                    "description": te.description,
                    "why_it_may_help": te.why_it_may_help,
                    "expected_timeline": te.expected_timeline,
                    "what_to_monitor": te.what_to_monitor,
                    "when_to_reassess": te.when_to_reassess,
                    "evidence_level": te.evidence_level.value,
                    "sources": [
                        {"title": s.title, "url": s.url, "type": s.type, "jurisdiction": s.jurisdiction}
                        for s in te.sources
                    ],
                }
                for te in self.treatment_education
            ],
            "medication_information": [
                {
                    "medication_name": mi.medication_name,
                    "medication_class": mi.medication_class,
                    "general_purpose": mi.general_purpose,
                    "common_warnings": mi.common_warnings,
                    "contraindication_categories": mi.contraindication_categories,
                    "potential_interactions": mi.potential_interactions,
                    "questions_to_ask": mi.questions_to_ask,
                    "package_check_items": mi.package_check_items,
                    "is_educational_only": mi.is_educational_only,
                    "source": {
                        "title": mi.source.title,
                        "url": mi.source.url,
                        "type": mi.source.type,
                        "jurisdiction": mi.source.jurisdiction,
                    } if mi.source else None,
                }
                for mi in self.medication_information
            ],
            "medication_verification": [
                {
                    "field": mv.field,
                    "description": mv.description,
                    "why_important": mv.why_important,
                }
                for mv in self.medication_verification
            ],
            "visual_education": [
                {
                    "title": ve.title,
                    "description": ve.description,
                    "visual_type": ve.visual_type,
                    "source": ve.source,
                    "source_url": ve.source_url,
                    "license": ve.license,
                    "medical_context": ve.medical_context,
                    "is_ai_generated": ve.is_ai_generated,
                    "ai_disclaimer": ve.ai_disclaimer,
                }
                for ve in self.visual_education
            ],
            "warning_signs": self.warning_signs,
            "follow_up": self.follow_up,
            "next_steps": self.next_steps,
            "professional_review": self.professional_review,
            "professional_review_reason": self.professional_review_reason,
            "sources": [
                {"title": s.title, "url": s.url, "type": s.type, "jurisdiction": s.jurisdiction}
                for s in self.sources
            ],
            "provider": self.provider,
            "model": self.model,
            "confidence_score": self.confidence_score,
            "disclaimer": self.disclaimer,
            "uncertainty": {
                "message": self.uncertainty.message,
                "level": self.uncertainty.level,
                "missing_information": self.uncertainty.missing_information,
            } if self.uncertainty else None,
            "safety_flags": self.safety_flags,
        }


# Emergency indicators — never silently downgrade
EMERGENCY_KEYWORDS = [
    "chest pain", "difficulty breathing", "severe bleeding",
    "loss of consciousness", "stroke symptoms", "severe allergic reaction",
    "suicidal", "confusion", "slurred speech", "facial drooping",
    "arm weakness", "severe headache", "high fever with rash",
    "seizure", "severe abdominal pain", "vomiting blood",
    "black tarry stools", "severe dehydration", "unable to wake",
]

URGENT_KEYWORDS = [
    "worsening symptoms", "high fever", "severe pain",
    "bloody diarrhea", "difficulty swallowing", "rapid heartbeat",
    "shortness of breath", "stiff neck",
]

ROUTINE_KEYWORDS = [
    "mild", "occasional", "intermittent", "minor",
    "cold symptoms", "low-grade fever", "sore throat",
]
