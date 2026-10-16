"""The safety stages wired together: provider output -> validators -> response.

Covers the failures found in review: emergencies reported as routine,
emergencies capped at "urgent", age 0 treated as "no age", Gemini refusals
read as routine, and the wrong country's emergency number.
"""

import asyncio
from types import SimpleNamespace

import pytest

from providers.models import AnalysisResponse, Modality, PatientProfile, TextAnalysisRequest
from providers.offline_provider import OfflineProvider
from safety_validator import safety_validator


def run(coro):
    return asyncio.run(coro)


def model_said(urgency="routine", confidence=0.9, uncertainty=""):
    return AnalysisResponse(
        provider="test",
        model="test",
        modality=Modality.TEXT,
        urgency=urgency,
        confidence_score=confidence,
        uncertainty=uncertainty,
        safety_notice="Not a diagnosis. Consult a healthcare professional. In an emergency call for help.",
    )


async def validate(response, text, profile=None):
    result = await safety_validator.validate_async(response, profile, original_text=text)
    return await safety_validator.apply_safety_result_async(response, result)


class TestOfflineProvider:
    @pytest.mark.parametrize(
        "text",
        [
            "I want to kill myself",
            "my baby is not breathing",
            "I took 30 paracetamol tablets",
            "his face is drooping on one side and his arm is weak",
        ],
    )
    def test_emergencies(self, text):
        response = run(OfflineProvider().analyze_text(TextAnalysisRequest(text=text)))
        assert response.urgency == "emergency"

    def test_negated_symptom_is_not_an_emergency(self):
        response = run(
            OfflineProvider().analyze_text(TextAnalysisRequest(text="no chest pain, just a mild cold"))
        )
        assert response.urgency != "emergency"

    def test_infant_age_from_patient_context(self):
        response = run(
            OfflineProvider().analyze_text(
                TextAnalysisRequest(text="fever since this morning", patient_context={"age": 0})
            )
        )
        assert response.urgency == "emergency"


class TestValidatorEscalates:
    def test_model_routine_but_patient_suicidal(self):
        response = run(validate(model_said("routine"), "I want to kill myself"))
        assert response.urgency == "emergency"
        assert "907" in response.safety_notice  # default number shown

    def test_model_urgent_is_raised_to_emergency(self):
        # Used to stay "urgent": the old check skipped responses already urgent.
        response = run(validate(model_said("urgent"), "He is having a stroke"))
        assert response.urgency == "emergency"

    def test_model_emergency_still_gets_emergency_instructions(self):
        response = run(validate(model_said("emergency"), "crushing chest pain"))
        assert response.urgency == "emergency"
        assert "emergency department" in response.safety_notice

    def test_never_lowers_the_model(self):
        response = run(validate(model_said("emergency"), "mild cold"))
        assert response.urgency == "emergency"

    def test_newborn_with_routine_answer(self):
        profile = PatientProfile(age=0)
        response = run(validate(model_said("self_care"), "a small rash", profile))
        assert response.urgency == "see_doctor_soon"
        assert "high_risk_patient:young_child" in response.safety_flags

    def test_older_adult_is_not_routine(self):
        profile = PatientProfile(age=85)
        response = run(validate(model_said("routine"), "a small rash", profile))
        assert response.urgency == "see_doctor_soon"

    def test_pregnant_patient_is_not_routine(self):
        profile = PatientProfile(age=28, pregnancy_status=True)
        response = run(validate(model_said("routine"), "mild nausea", profile))
        assert response.urgency == "see_doctor_soon"

    def test_very_low_confidence_is_not_reassurance(self):
        response = run(validate(model_said("routine", confidence=0.1), "mild cough"))
        assert response.urgency == "see_doctor_soon"

    def test_ethiopian_location_gets_ethiopian_number(self):
        profile = PatientProfile(age=40, location="Mekelle, Ethiopia")
        response = run(validate(model_said("routine"), "I can't breathe", profile))
        assert "907" in response.safety_notice
        assert "999" not in response.safety_notice

    def test_model_advice_is_not_scanned_for_red_flags(self):
        response = model_said("routine")
        response.recommended_next_step = "Seek care if chest pain develops."
        response = run(validate(response, "mild cough"))
        assert response.urgency == "routine"


class TestOrchestratorValidator:
    def test_emergency_is_not_capped_at_urgent(self):
        from providers.orchestrator import MultimodalClinicalContext, SafetyValidator

        context = MultimodalClinicalContext(text="I have chest pain")
        response = SafetyValidator().validate(model_said("routine"), context)
        assert response.urgency == "emergency"


class TestProviderFailures:
    def test_blocked_gemini_answer_is_not_routine(self):
        from providers.gemini_provider import GeminiProvider

        class Blocked:
            @property
            def text(self):
                raise ValueError("response was blocked by the safety filter")

        provider = GeminiProvider.__new__(GeminiProvider)
        provider.model_name = "gemini-test"
        result = provider._parse_response(Blocked(), Modality.TEXT)
        assert result.urgency == "see_doctor_soon"
        assert result.requires_professional_review is True

    def test_missing_urgency_is_not_routine(self):
        from providers.gemini_provider import GeminiProvider

        provider = GeminiProvider.__new__(GeminiProvider)
        provider.model_name = "gemini-test"
        result = provider._parse_response(SimpleNamespace(text='{"confidence_score": 0.8}'), Modality.TEXT)
        assert result.urgency == "see_doctor_soon"


class TestResponseTransformer:
    @pytest.mark.parametrize("label,expected", [("critical", "emergency"), ("EMERGENCY - call now", "emergency")])
    def test_unknown_labels_map_up_not_down(self, label, expected):
        from response_transformer import response_transformer

        response = model_said(label)
        safety = response_transformer._build_safety(response, None)
        assert safety.urgency.value == expected


def test_parse_error_never_lowers_the_models_emergency():
    """Review: a bad later field used to overwrite the model's "emergency"."""
    from providers.gemini_provider import GeminiProvider

    provider = GeminiProvider.__new__(GeminiProvider)
    provider.model_name = "gemini-test"
    raw = '{"urgency": "emergency", "confidence_score": "high", "recommended_next_step": "Call 907 now."}'
    result = provider._parse_response(SimpleNamespace(text=raw), Modality.TEXT)
    assert result.urgency == "emergency"
    assert result.recommended_next_step == "Call 907 now."
