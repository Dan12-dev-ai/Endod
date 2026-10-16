"""The AI's answer reaches the patient instead of being replaced by defaults."""

import json
from types import SimpleNamespace

from providers.models import (
    AnalysisResponse,
    Modality,
    PossibleExplanation,
    Source,
    TreatmentInformation,
)
from response_transformer import response_transformer


def _response(**fields):
    return AnalysisResponse(provider="test", model="test", modality=Modality.TEXT, **fields)


class TestTransformer:
    def test_provider_differential_is_shown(self):
        response = _response(possible_explanations=[
            PossibleExplanation(condition="Malaria", likelihood="likely", confidence=0.8,
                                reasoning="Fever with chills in an endemic area"),
            PossibleExplanation(condition="Typhoid fever", likelihood="possible", confidence=0.5,
                                reasoning="Prolonged fever"),
        ])
        labels = [e.label for e in response_transformer.transform(response).possible_explanations]
        assert labels == ["Malaria", "Typhoid fever"]

    def test_treatments_are_kept_but_never_doses(self):
        response = _response(treatment_information=[
            TreatmentInformation(condition="Malaria", intervention="Antimalarial treatment",
                                 description="Confirmed with a malaria test first.", evidence_level="A",
                                 source="WHO malaria guidelines", dosage_info="1000 mg twice daily"),
        ])
        result = response_transformer.transform(response)
        titles = [t.title for t in result.treatment_education]
        assert "Antimalarial treatment" in titles
        assert "Rest and hydration" not in titles  # the generic default is not used
        assert "1000 mg" not in json.dumps(result.to_dict())

    def test_sources_are_kept(self):
        response = _response(sources=[
            Source(id="who", title="WHO Guidelines for malaria", type="guideline",
                   url="https://www.who.int/publications/i/item/guidelines-for-malaria"),
        ])
        titles = [s.title for s in response_transformer.transform(response).sources]
        assert titles == ["WHO Guidelines for malaria"]

    def test_first_aid_steps_render(self):
        steps = [{"title": "Cool the burn", "description": "Run cool water over it for 20 minutes."}]
        response = _response(treatment_information=[
            TreatmentInformation(condition="Burn", intervention="first_aid", description=json.dumps(steps),
                                 evidence_level="expert_opinion", source="Red Cross first aid"),
        ])
        titles = [t.title for t in response_transformer.transform(response).treatment_education]
        assert "Cool the burn" in titles

    def test_nothing_from_the_model_still_gives_safe_defaults(self):
        result = response_transformer.transform(_response())
        assert result.possible_explanations[0].label.startswith("Undetermined")


class TestProviderParsing:
    def _gemini(self):
        from providers.gemini_provider import GeminiProvider

        provider = GeminiProvider.__new__(GeminiProvider)
        provider.model_name = "gemini-test"
        return provider

    def test_top_level_differential_is_parsed(self):
        raw = json.dumps({
            "urgency": "routine",
            "possible_explanations": [
                {"condition": "Common cold", "likelihood": "likely", "confidence": 0.7, "reasoning": "Runny nose"},
            ],
        })
        result = self._gemini()._parse_response(SimpleNamespace(text=raw), Modality.TEXT)
        assert [e.condition for e in result.possible_explanations] == ["Common cold"]

    def test_one_malformed_item_does_not_discard_the_answer(self):
        raw = json.dumps({
            "urgency": "urgent",
            "recommended_next_step": "See a clinician today.",
            "possible_explanations": [
                {"condition": "Pneumonia", "likelihood": "possible", "confidence": 0.6, "reasoning": "Fever, cough"},
                {"condition": "missing required fields"},
            ],
            "sources": [{"title": "no id"}, {"id": "who", "title": "WHO", "type": "guideline"}],
        })
        result = self._gemini()._parse_response(SimpleNamespace(text=raw), Modality.TEXT)
        assert result.urgency == "urgent"
        assert result.recommended_next_step == "See a clinician today."
        assert [e.condition for e in result.possible_explanations] == ["Pneumonia"]
        assert [s.title for s in result.sources] == ["WHO"]
        assert not any(f.startswith("provider_response_unreadable") for f in result.safety_flags)


class TestEndToEnd:
    def test_offline_answer_names_conditions(self, client, valid_payload):
        valid_payload["symptom_description"] = "I have had fever, chills and sweating for three days"
        body = client.post("/api/analyze", json=valid_payload).json()
        labels = [e["label"] for e in body["possible_explanations"]]
        assert "Malaria" in labels
        assert not labels[0].startswith("Undetermined")


class TestReviewFindings:
    """Automated review (Qodo) of PR #6."""

    def test_prompt_asks_for_a_top_level_differential(self):
        from providers.orchestrator import MultimodalContextBuilder

        prompt = MultimodalContextBuilder()._get_default_system_prompt()
        assert prompt.index('"possible_explanations"') < prompt.index('"image_assessment"')

    def test_supporting_observations_support_the_condition(self):
        response = _response(possible_explanations=[
            PossibleExplanation(condition="Malaria", likelihood="likely", confidence=0.8,
                                reasoning="Typical pattern", supporting_observations=["fever", "chills"]),
        ])
        explanation = response_transformer.transform(response).possible_explanations[0]
        assert "fever" in explanation.why_it_fits
        assert "fever" not in explanation.what_does_not_fit

    def test_doses_in_free_text_are_removed(self):
        response = _response(treatment_information=[
            TreatmentInformation(condition="Fever", intervention="Paracetamol 500 mg",
                                 description="Take 2 tablets every 6 hours, twice a day.",
                                 evidence_level="A", source="WHO", precautions=["Max 4 g per day"]),
        ])
        payload = json.dumps(response_transformer.transform(response).to_dict())
        for dose in ("500 mg", "2 tablets", "every 6 hours", "twice a day", "4 g"):
            assert dose not in payload, dose
        assert "ask a clinician or pharmacist" in payload

    def test_contraindications_are_shown(self):
        response = _response(treatment_information=[
            TreatmentInformation(condition="Pain", intervention="Anti-inflammatory medicine",
                                 description="Reduces pain and swelling.", evidence_level="B",
                                 source="WHO", contraindications=["stomach ulcers", "late pregnancy"]),
        ])
        education = response_transformer.transform(response).treatment_education
        text = next(t for t in education if t.title == "Anti-inflammatory medicine").description
        assert "stomach ulcers" in text and "late pregnancy" in text

    def test_treatment_sources_are_serialised(self):
        response = _response(treatment_information=[
            TreatmentInformation(condition="Malaria", intervention="Antimalarial treatment",
                                 description="After a positive test.", evidence_level="A",
                                 source="WHO malaria guidelines"),
        ])
        treatments = response_transformer.transform(response).to_dict()["treatment_education"]
        assert treatments[0]["sources"][0]["title"] == "WHO malaria guidelines"

    def test_citations_without_a_link_are_not_published(self):
        response = _response(sources=[
            Source(id="a", title="Unlinked textbook", type="textbook"),
            Source(id="b", title="WHO", type="guideline", url="https://www.who.int"),
        ])
        titles = [s.title for s in response_transformer.transform(response).sources]
        assert titles == ["WHO"]

    def test_discarded_items_are_logged(self, caplog):
        from providers.models import parse_items

        with caplog.at_level("WARNING"):
            parse_items(Source, [{"title": "missing id and type"}])
        assert "provider_item_discarded" in caplog.text
        assert "model=Source" in caplog.text
