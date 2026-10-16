"""Tests for clinical_schema module."""

import pytest

import pytest
from datetime import datetime, timedelta

from clinical_schema import (
    ClinicalResponse, HealthSummary, SafetyClassification,
    PossibleExplanation, UncertaintyStatement, TreatmentEducation,
    MedicationInfo, VisualEducation, Source, UrgencyLevel,
    EvidenceLevel, Observation,
)


class TestClinicalResponse:
    def test_full_response_serialization(self):
        safety = SafetyClassification(
            urgency=UrgencyLevel.ROUTINE,
            recommended_action="Monitor symptoms",
            red_flags=[],
            requires_immediate_care=False,
            emergency_message=None,
            professional_review_required=False,
        )
        uncertainty = UncertaintyStatement(
            message="Not enough info",
            level="moderate",
            missing_information=["Temperature"],
        )
        response = ClinicalResponse(
            response_id="test-123",
            session_id="session-456",
            timestamp=datetime.now().isoformat(),
            health_summary=HealthSummary(
                duration="2 days",
                severity="mild",
                symptoms=["headache"],
            ),
            safety=safety,
            possible_explanations=[],
            uncertainty=uncertainty,
            treatment_education=[],
            medication_information=[],
            visual_education=[],
            follow_up={"recommended": False},
            sources=[],
            confidence_score=0.75,
        )
        d = response.to_dict()
        assert d["response_id"] == "test-123"
        assert d["safety"]["urgency"] == "routine"
        assert d["uncertainty"]["level"] == "moderate"
        assert d["confidence_score"] == 0.75
        assert d["disclaimer"] == "This is AI-generated health information, not a diagnosis. Always consult a qualified healthcare professional."

    def test_emergency_safety_classification(self):
        safety = SafetyClassification(
            urgency=UrgencyLevel.EMERGENCY,
            recommended_action="Seek emergency care immediately",
            red_flags=["chest pain"],
            requires_immediate_care=True,
            emergency_message="Call emergency services",
            professional_review_required=True,
        )
        assert safety.requires_immediate_care is True
        assert safety.emergency_message is not None

    def test_medication_info_educational_only(self):
        med = MedicationInfo(
            medication_name="Acetaminophen",
            medication_class="Analgesic",
            general_purpose="Pain relief",
            common_warnings=["Do not exceed"],
            contraindication_categories=["Liver disease"],
            potential_interactions=["Warfarin"],
            questions_to_ask=["Correct dose?"],
            package_check_items=["Active ingredient"],
            is_educational_only=True,
        )
        assert med.is_educational_only is True

    def test_visual_education_ai_generated_label(self):
        ve = VisualEducation(
            title="Test diagram",
            description="Educational illustration",
            visual_type="illustration",
            source="DEDAN Health",
            medical_context="General education",
            is_ai_generated=True,
            ai_disclaimer="AI-generated educational illustration",
        )
        assert ve.is_ai_generated is True
        assert ve.ai_disclaimer is not None


class TestUrgencyEngine:
    def setup_method(self):
        from urgency_engine import UrgencyEngine
        self.engine = UrgencyEngine()

    def test_emergency_keyword_detection(self):
        safety = self.engine.classify(
            symptoms="I have chest pain and difficulty breathing",
        )
        assert safety.urgency == UrgencyLevel.EMERGENCY
        assert safety.requires_immediate_care is True

    def test_urgent_keyword_detection(self):
        safety = self.engine.classify(
            symptoms="I have high fever and severe pain",
        )
        assert safety.urgency == UrgencyLevel.URGENT
        assert safety.professional_review_required is True

    def test_routine_keyword_detection(self):
        safety = self.engine.classify(
            symptoms="Mild sore throat, occasional",
        )
        assert safety.urgency == UrgencyLevel.ROUTINE
        assert safety.professional_review_required is False

    def test_unclear_symptoms_soon(self):
        safety = self.engine.classify(
            symptoms="I feel unwell",
        )
        assert safety.urgency == UrgencyLevel.SOON
        assert safety.professional_review_required is True

    def test_red_flags_tracked(self):
        safety = self.engine.classify(
            symptoms="mild headache",
            red_flags=["chest pain"],
        )
        assert safety.red_flags == ["chest pain"]


class TestEvidenceRetrieval:
    def setup_method(self):
        from evidence_retrieval import EvidenceRetriever
        self.retriever = EvidenceRetriever()

    def test_retrieve_caches_results(self):
        result1 = self.retriever.retrieve("headache", EvidenceLevel.MODERATE)
        result2 = self.retriever.retrieve("headache", EvidenceLevel.MODERATE)
        assert result1 == result2

    def test_retrieve_returns_sources(self):
        result = self.retriever.retrieve("diabetes", EvidenceLevel.STRONG)
        assert "sources" in result
        assert len(result["sources"]) > 0

    def test_get_sources_for_topic(self):
        sources = self.retriever.get_sources_for_topic("cold")
        assert isinstance(sources, list)
        for s in sources:
            assert hasattr(s, 'title')
            assert hasattr(s, 'url')


class TestMedicationSafety:
    def setup_method(self):
        from medication_safety import MedicationSafetyService
        self.service = MedicationSafetyService()

    def test_get_medication_info(self):
        info = self.service.get_medication_info("acetaminophen")
        assert info.medication_name == "acetaminophen"
        assert info.is_educational_only is True
        assert len(info.common_warnings) > 0

    def test_verify_medication(self):
        result = self.service.verify_medication("ibuprofen")
        assert result["verification_required"] is True
        assert "Always check the actual package label" in result["note"]

    def test_unknown_medication(self):
        info = self.service.get_medication_info("unknown_drug_xyz")
        assert info.medication_name == "unknown_drug_xyz"
        assert info.medication_class == "Unknown"

    def test_never_prescribes(self):
        """Medication info is educational only — never a prescription."""
        info = self.service.get_medication_info("amoxicillin")
        assert info.is_educational_only is True
        assert "antibiotic" in info.medication_class.lower()


class TestVisualEducationService:
    def setup_method(self):
        from visual_education import VisualEducationService
        self.service = VisualEducationService()

    def test_search_visuals(self):
        visuals = self.service.search_visuals("diabetes", "disease_overview")
        assert len(visuals) > 0
        for v in visuals:
            assert v.is_ai_generated is False
            assert v.source is not None

    def test_label_ai_generated(self):
        ve = self.service.label_ai_generated(
            "Test diagram",
            "Educational illustration",
        )
        assert ve.is_ai_generated is True
        assert "AI-generated" in (ve.ai_disclaimer or "")

    def test_get_disease_overview(self):
        visuals = self.service.get_disease_overview("flu")
        assert len(visuals) > 0


class TestConversationMemory:
    def setup_method(self):
        from conversation_memory import ConversationMemoryManager, ConversationTurn
        self.manager = ConversationMemoryManager()
        self.Turn = ConversationTurn

    def test_create_and_get_context(self):
        ctx = self.manager.get_or_create("session-1")
        assert ctx.session_id == "session-1"
        assert len(ctx.turns) == 0

    def test_add_turn(self):
        ctx = self.manager.get_or_create("session-2")
        turn = self.Turn(role="patient", content="I have a headache")
        ctx.add_turn(turn)
        assert len(ctx.turns) == 1

    def test_get_context_for_ai(self):
        ctx = self.manager.get_or_create("session-3")
        ctx.set_patient_facts({"age": 30, "chronic_conditions": []})
        ctx.add_turn(self.Turn(role="patient", content="I have a headache"))
        ctx.add_turn(self.Turn(role="assistant", content="Let me check"))
        context = ctx.get_context_for_ai(current_question="Why?")
        assert context["patient_facts"]["age"] == 30
        assert context["current_question"] == "Why?"
        assert len(context["recent_turns"]) == 2

    def test_context_limits(self):
        ctx = self.manager.get_or_create("session-4")
        for i in range(30):
            ctx.add_turn(self.Turn(role="patient", content=f"Message {i}"))
        assert len(ctx.turns) <= 20

    def test_cleanup_expired(self):
        manager = self.manager
        from conversation_memory import ConversationContext
        ctx = ConversationContext("old-session")
        # UTC, like the code under test: local time made this pass only on
        # machines whose clock is at or behind UTC (it failed in Ethiopia, UTC+3).
        ctx.created_at = datetime.utcnow() - timedelta(hours=25)
        manager._contexts["old-session"] = ctx
        removed = manager.cleanup_expired(max_age_hours=24)
        assert removed >= 1
