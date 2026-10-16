"""
Offline / deterministic AI provider.

DEDAN targets low-resource settings where valid provider credentials may be
absent (and in CI, where outbound network access must not be required). This
provider implements the full ``MultimodalAIProvider`` contract using
deterministic, rules-based clinical safety logic so that:

  * Every endpoint can be exercised end-to-end without API keys.
  * Responses are honest: ``provider="offline"`` is reported upstream, and the
    payload carries an explicit ``safety_notice`` stating it is not a
    diagnosis from a live model.
  * Emergency red-flag escalation still happens (safety is never relaxed).

It is selected when ``AI_PROVIDER_MODE=offline`` or when no usable credential
is configured (see ``provider_factory``).
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Dict, List, Optional

import clinical_triage

from .models import (
    AnalysisResponse,
    ImageAnalysisRequest,
    ImageAssessment,
    MedicalInformation,
    Modality,
    MultimodalAnalysisRequest,
    PossibleExplanation,
    ProviderCapabilities,
    Source,
    TextAnalysisRequest,
    TokenUsage,
    TreatmentInformation,
    MultimodalAIProvider,
)

# Symptom -> likely condition mapping used to build educational differentials.
_CONDITION_PATTERNS: List[tuple] = [
    ("Malaria", [r"fever", r"chills", r"sweating", r"malaria"], "B"),
    ("Common cold / viral upper respiratory infection",
     [r"cough", r"runny nose", r"sore throat", r"sneez", r"congestion"], "B"),
    ("Influenza (flu)",
     [r"flu", r"body aches", r"myalgia", r"fatigue.*fever"], "B"),
    ("Acute gastroenteritis",
     [r"diarrh", r"vomit", r"nausea", r"stomach", r"abdominal pain"], "B"),
    ("Tension-type headache / migraine",
     [r"headache", r"migraine", r"head pain"], "B"),
    ("Urinary tract infection",
     [r"burning.*urin", r"urinat", r"frequent urin", r"pee"], "C"),
    ("Acute bronchitis / lower respiratory infection",
     [r"cough", r"chest.*congest", r"phlegm"], "C"),
    ("Typhoid fever",
     [r"fever.*days", r"abdominal.*fever", r"typhoid"], "C"),
    ("Skin / soft tissue infection",
     [r"rash", r"redness", r"swelling", r"wound", r"itch"], "C"),
    ("Anemia",
     [r"tired", r"fatigue", r"weak", r"dizzy", r"pale"], "C"),
]

_SOURCES = [
    Source(
        id="who_ictmg",
        title="WHO Guidelines for the Treatment of Malaria",
        type="guideline",
        url="https://www.who.int/publications/i/item/9789240042479",
        authors=["World Health Organization"],
        publication_date="2015",
    ),
    Source(
        id="who_imci",
        title="WHO Integrated Management of Childhood Illness (IMCI)",
        type="guideline",
        url="https://www.who.int/teams/child-health-and-development/health-conditions/intergrated-management-of-childhood-illness",
        authors=["World Health Organization"],
    ),
    Source(
        id="who_cpg",
        title="WHO Primary Health Care / Clinical Problem Solving Guides",
        type="guideline",
        url="https://www.who.int/health-topics",
        authors=["World Health Organization"],
    ),
]

_OFFLINE_NOTICE = (
    "Offline rules-based assessment (no live AI model credential configured). "
    "This is educational guidance, NOT a medical diagnosis. Always confirm with "
    "a qualified clinician."
)


def _token_hash(text: str) -> str:
    return hashlib.sha256((text or "dedan").encode("utf-8")).hexdigest()[:12]


class OfflineProvider(MultimodalAIProvider):
    """Deterministic, credential-free provider implementing the full contract."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config or {})
        self.model_name = (config or {}).get("model", "dedan-rules-v1")

    # ------------------------------------------------------------------
    # Provider metadata
    # ------------------------------------------------------------------
    @property
    def provider_name(self) -> str:
        return "offline"

    @property
    def default_model(self) -> str:
        return self.model_name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name="offline",
            supports_text=True,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_document=False,
            max_image_size_mb=20,
            supported_image_formats=["jpeg", "png", "webp", "heic", "heif"],
            context_window=32768,
            max_output_tokens=4096,
            supports_structured_output=True,
            supports_streaming=False,
            supported_languages=["en", "sw", "am", "es", "fr"],
            medical_safety_trained=True,
        )

    # ------------------------------------------------------------------
    # Core analysis methods
    # ------------------------------------------------------------------
    async def analyze_text(self, request: TextAnalysisRequest) -> AnalysisResponse:
        start = time.time()
        response = self._analyze(
            text=request.text or "",
            modality=Modality.TEXT,
            patient_context=request.patient_context,
            has_image=False,
        )
        return self._finalize(response, start)

    async def analyze_image(self, request: ImageAnalysisRequest) -> AnalysisResponse:
        start = time.time()
        response = self._analyze(
            text=request.prompt or "",
            modality=Modality.IMAGE,
            patient_context=request.patient_context,
            has_image=True,
        )
        return self._finalize(response, start)

    async def analyze_multimodal(
        self, request: MultimodalAnalysisRequest
    ) -> AnalysisResponse:
        start = time.time()
        response = self._analyze(
            text=request.text or "",
            modality=Modality.IMAGE if request.images else Modality.TEXT,
            patient_context=request.patient_context,
            has_image=bool(request.images),
        )
        return self._finalize(response, start)

    # ------------------------------------------------------------------
    # Deterministic rules engine
    # ------------------------------------------------------------------
    def _analyze(
        self,
        text: str,
        modality: Modality,
        patient_context: Optional[Dict[str, Any]],
        has_image: bool,
    ) -> AnalysisResponse:
        combined = text or ""
        if patient_context:
            combined += " " + " ".join(str(v) for v in patient_context.values())
        haystack = combined.lower()

        # --- urgency: the shared red-flag rules (clinical_triage) ---
        context = patient_context or {}
        triage = clinical_triage.assess(
            text,
            age_years=context.get("age"),
            pregnant=bool(context.get("pregnancy_status")),
        )
        urgency = triage.urgency
        if urgency == "emergency":
            next_step = (
                "Seek emergency care now. Do not wait - this pattern can be "
                "life-threatening."
            )
        elif urgency == "urgent":
            next_step = (
                "See a clinician within 24 hours. Your symptoms suggest you "
                "should be evaluated promptly."
            )
        elif urgency == "see_doctor_soon":
            next_step = (
                "See a clinician in the next day or two, sooner if symptoms "
                "get worse."
            )
        else:
            next_step = (
                "Schedule a routine appointment with a clinician, or use "
                "self-care and re-check if symptoms worsen."
            )

        # --- differentials (top 3 by matched symptom coverage) ---
        scored: List[tuple] = []
        for condition, patterns, _evidence in _CONDITION_PATTERNS:
            hits = sum(1 for p in patterns if re.search(p, haystack))
            if hits:
                scored.append((hits, condition))
        scored.sort(key=lambda t: -t[0])
        top = scored[:3]

        observations = [text.strip()[:200]] if text.strip() else []
        if top:
            explanations = [
                PossibleExplanation(
                    condition=condition,
                    likelihood="likely" if i == 0 else "possible",
                    confidence=round(min(0.85, 0.45 + 0.12 * hits), 2),
                    reasoning=(
                        f"Reported symptoms overlap with known presentations of "
                        f"{condition.lower()}."
                    ),
                    supporting_observations=observations,
                    citations=["WHO Primary Health Care guidance"],
                )
                for i, (hits, condition) in enumerate(top)
            ]
        else:
            explanations = [
                PossibleExplanation(
                    condition="Insufficient symptom detail",
                    likelihood="differential",
                    confidence=0.2,
                    reasoning=(
                        "Symptoms provided are not specific enough to narrow the "
                        "differential. A clinician should take a full history."
                    ),
                    supporting_observations=observations,
                )
            ]

        primary_condition = explanations[0].condition
        medical_info = [
            MedicalInformation(
                topic=primary_condition,
                content=(
                    f"{primary_condition} is a common presentation in primary "
                    "care. Assessment depends on symptom duration, severity, "
                    "age, pregnancy status and chronic conditions."
                ),
                source="WHO Primary Health Care guidance",
                source_type="guideline",
                relevance_score=0.8,
            )
        ]
        treatment_info = [
            TreatmentInformation(
                condition=primary_condition,
                intervention="Clinical assessment",
                description=(
                    "Confirm the diagnosis with a clinician before starting "
                    "any prescription treatment. Rest, fluids and symptom "
                    "control may be advised in the meantime."
                ),
                evidence_level="B",
                source="WHO Primary Health Care guidance",
                precautions=[
                    "Do not start prescription medicines without a clinician's review",
                    "Complete the full course of any prescribed treatment",
                ],
            )
        ]

        warning_signs = [
            "Trouble breathing or chest pain",
            "Confusion, unusual drowsiness or difficulty waking",
            "Unable to keep fluids down or signs of severe dehydration",
            "Symptoms that rapidly worsen instead of improving",
        ]
        if urgency in ("emergency", "urgent"):
            warning_signs.insert(0, "Seek immediate care if any of these escalate")

        follow_up = [
            "How long have you had these symptoms?",
            "Have your symptoms gotten worse, better, or stayed the same?",
            "Have you taken any medicines for this already?",
            "Do you have any chronic conditions or are you pregnant?",
        ]

        return AnalysisResponse(
            provider=self.provider_name,
            model=self.model_name,
            modality=modality,
            urgency=urgency,
            recommended_next_step=next_step,
            medical_information=medical_info,
            treatment_information=treatment_info,
            warning_signs=warning_signs,
            follow_up_questions=follow_up,
            sources=_SOURCES,
            uncertainty=(
                "Deterministic rules-based assessment; no probabilistic model "
                "was consulted."
            ),
            requires_professional_review=True,
            safety_notice=_OFFLINE_NOTICE,
            confidence_score=0.55 if urgency == "routine" else 0.7,
            raw_response=f"offline_rules:{_token_hash(combined)}",
            safety_flags=[f"triage:{reason}" for reason in triage.reasons],
            content_filtered=False,
            image_assessment=self._image_assessment(has_image),
            metadata={"offline": True, "rules_version": 2},
        )

    def _image_assessment(self, has_image: bool) -> Optional[ImageAssessment]:
        if not has_image:
            return None
        return ImageAssessment(
            observations=[
                "Image received. Offline mode cannot perform computer vision; "
                "describe any visible findings to a clinician."
            ],
            possible_explanations=[],
            limitations=[
                "No AI vision model available in offline mode - image was not "
                "clinically interpreted."
            ],
            requires_better_image=False,
            quality_issues=[],
        )

    def _finalize(self, response: AnalysisResponse, start: float) -> AnalysisResponse:
        response.processing_time_ms = int((time.time() - start) * 1000)
        prompt_tokens = max(1, len(str(response.raw_response)) // 4)
        completion_tokens = 128
        response.token_usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        self.record_request(
            response.processing_time_ms,
            TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )
        return response

    # ------------------------------------------------------------------
    # Cost / health
    # ------------------------------------------------------------------
    def estimate_cost(self, tokens: TokenUsage) -> float:
        return 0.0

    async def health_check(self) -> bool:
        # Always available - it is pure local computation.
        return True
