"""
Gemini Provider Implementation

Implements the MultimodalAIProvider interface for Google's Gemini models,
using the `google-genai` SDK. (`google-generativeai`, used before, reached end
of life and warned on every start; its default model, gemini-1.5-pro, is
retired.)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

import clinical_triage

from .models import (
    Modality,
    ProviderCapabilities,
    ImageInput,
    AudioInput,
    TextAnalysisRequest,
    ImageAnalysisRequest,
    MultimodalAnalysisRequest,
    AnalysisResponse,
    ImageQuality,
    PossibleExplanation,
    ImageAssessment,
    MedicalInformation,
    TreatmentInformation,
    Source,
    TokenUsage,
    ProviderUnavailableError,
    ProviderRateLimitError,
    ProviderInvalidRequestError,
    ProviderSafetyError,
    ProviderTimeoutError,
    MultimodalAIProvider,
    parse_items,
)


def _strip_code_fence(text: str) -> str:
    """Remove a surrounding ```json ... ``` fence, if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    return stripped


class GeminiProvider(MultimodalAIProvider):
    """
    Google Gemini provider for multimodal AI analysis.

    Supports text, image and combined analysis with JSON output. Model ids are
    configured (`AI_*_MODEL`, `GEMINI_MODEL`); the `*-latest` aliases follow
    Google's current model of each class.
    """

    #: Limits used for capability reporting. Pricing is not tracked here:
    #: Google's price list changes, so cost estimates were stale guesses.
    MODELS = {
        "gemini-flash-lite-latest": {"context_window": 1_000_000, "max_output_tokens": 8192},
        "gemini-flash-latest": {"context_window": 1_000_000, "max_output_tokens": 8192},
        "gemini-pro-latest": {"context_window": 1_000_000, "max_output_tokens": 8192},
    }
    DEFAULT_MODEL = "gemini-flash-latest"

    #: Roles a client may put in conversation history. Anything else (e.g. a
    #: client-supplied "system") is treated as patient text, so history cannot
    #: be used to inject instructions.
    _ROLE_LABELS = {"user": "PATIENT", "patient": "PATIENT", "assistant": "ASSISTANT", "model": "ASSISTANT"}

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        config = config or {}

        self.api_key = config.get("api_key") or os.getenv("GEMINI_API_KEY")
        self.model_name = config.get("model") or self.DEFAULT_MODEL
        self.temperature = config.get("temperature", 0.3)
        self.max_tokens = config.get("max_tokens")
        self.timeout_seconds = float(config.get("timeout_seconds", 60.0))
        self.max_retries = config.get("max_retries", 3)
        self.retry_delay = config.get("retry_delay_seconds", 1.0)

        if not self.api_key:
            raise ProviderInvalidRequestError(
                "gemini", self.model_name,
                "GEMINI_API_KEY not configured"
            )

        # The request timeout is enforced by the client; previously no timeout
        # was passed and a hung call blocked the request forever.
        self._client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1000)),
        )

        # Medical content: DANGEROUS_CONTENT only blocks high-probability
        # harm. At medium, questions about overdoses or self-harm -- the very
        # messages that most need a careful answer -- were refused.
        threshold = types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE
        self.safety_settings = [
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=threshold),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=threshold),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=threshold),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
        ]
        self._config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_tokens or self.MODELS.get(self.model_name, {}).get("max_output_tokens", 8192),
            response_mime_type="application/json",
            safety_settings=self.safety_settings,
        )

    @property
    def provider_name(self) -> str:
        return "gemini"
    
    @property
    def default_model(self) -> str:
        return self.model_name
    
    @property
    def capabilities(self) -> ProviderCapabilities:
        model_info = self.MODELS.get(self.model_name, {})
        return ProviderCapabilities(
            provider_name="gemini",
            supports_text=True,
            supports_vision=True,
            supports_audio=False,
            supports_video=False,
            supports_document=False,
            max_image_size_mb=20,
            supported_image_formats=["jpeg", "png", "webp", "heic"],
            context_window=model_info.get("context_window", 1_000_000),
            max_output_tokens=model_info.get("max_output_tokens", 8192),
            supports_structured_output=True,
            supports_streaming=False,
            supported_languages=["en", "es", "fr", "sw", "am", "ar", "hi", "zh", "pt"],
            medical_safety_trained=True,
        )
# -------------------------------------------------------------------------
    # Core Analysis Methods
    # -------------------------------------------------------------------------
    
    async def analyze_text(self, request: TextAnalysisRequest) -> AnalysisResponse:
        """Analyze text input using Gemini."""
        start_time = time.time()
        try:
            prompt = self._build_text_prompt(request)
            response = await self._generate_with_retry(prompt)
            result = self._parse_response(response, Modality.TEXT)
            result.processing_time_ms = int((time.time() - start_time) * 1000)
            result.provider = self.provider_name
            result.model = self.model_name
            result.modality = Modality.TEXT
            self._record_metrics(result, start_time)
            return result
        except Exception as e:
            self._record_error(e, start_time)
            raise
    
    async def analyze_image(self, request: ImageAnalysisRequest) -> AnalysisResponse:
        """Analyze image input using Gemini vision."""
        start_time = time.time()
        try:
            image_parts = await self._prepare_images(request.images)
            prompt_parts = [request.prompt]
            prompt_parts.extend(image_parts)
            if request.system_prompt:
                prompt_parts.insert(0, request.system_prompt)
            response = await self._generate_with_retry(prompt_parts)
            result = self._parse_response(response, Modality.IMAGE)
            result.processing_time_ms = int((time.time() - start_time) * 1000)
            result.provider = self.provider_name
            result.model = self.model_name
            result.modality = Modality.IMAGE
            self._record_metrics(result, start_time)
            return result
        except Exception as e:
            self._record_error(e, start_time)
            raise
    
    async def analyze_multimodal(self, request: MultimodalAnalysisRequest) -> AnalysisResponse:
        """Analyze combined text + image input using Gemini."""
        start_time = time.time()
        try:
            image_parts = []
            if request.images:
                image_parts = await self._prepare_images(request.images)
            prompt_parts = []
            if request.system_prompt:
                prompt_parts.append(request.system_prompt)
            for turn in request.conversation_history:
                content = turn.get("content", "")
                if content:
                    prompt_parts.append(f"[{self._role_label(turn.get('role'))}]: {content}")
            if request.text:
                prompt_parts.append(f"[PATIENT]: {request.text}")
            prompt_parts.extend(image_parts)
            if request.patient_context:
                context_str = json.dumps(request.patient_context, indent=2)
                prompt_parts.append(f"[PATIENT_CONTEXT]: {context_str}")
            response = await self._generate_with_retry(prompt_parts)
            result = self._parse_response(response, Modality.IMAGE if request.images else Modality.TEXT)
            result.processing_time_ms = int((time.time() - start_time) * 1000)
            result.provider = self.provider_name
            result.model = self.model_name
            result.modality = Modality.IMAGE if request.images else Modality.TEXT
            self._record_metrics(result, start_time)
            return result
        except Exception as e:
            self._record_error(e, start_time)
            raise
    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    
    def _build_text_prompt(self, request: TextAnalysisRequest) -> str:
        """Build prompt for text analysis."""
        parts = []
        if request.system_prompt:
            parts.append(request.system_prompt)
        for turn in request.conversation_history:
            content = turn.get("content", "")
            if content:
                parts.append(f"[{self._role_label(turn.get('role'))}]: {content}")
        parts.append(f"[PATIENT]: {request.text}")
        if request.patient_context:
            parts.append(f"[CONTEXT]: {json.dumps(request.patient_context)}")
        return "\n\n".join(parts)
    
    def _role_label(self, role: Any) -> str:
        return self._ROLE_LABELS.get(str(role or "user").lower(), "PATIENT")

    async def _prepare_images(self, images: List[ImageInput]) -> List[types.Part]:
        """Convert ImageInput objects to Gemini parts."""
        parts = []
        for img in images:
            if img.image_data:
                parts.append(types.Part.from_bytes(
                    data=base64.b64decode(img.image_data), mime_type=img.mime_type
                ))
            elif img.image_url:
                raise ProviderInvalidRequestError(
                    self.provider_name, self.model_name,
                    "Image URLs not supported directly; use base64 image_data"
                )
        return parts

    @staticmethod
    def _blocked(response: Any) -> bool:
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            return True
        candidates = getattr(response, "candidates", None) or []
        return bool(candidates) and getattr(candidates[0], "finish_reason", None) == types.FinishReason.SAFETY

    async def _generate_with_retry(self, prompt: Any) -> Any:
        """Generate content, retrying only transient failures."""
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self.model_name, contents=prompt, config=self._config,
                )
            except genai_errors.APIError as exc:
                code = getattr(exc, "code", None) or 0
                if code == 429:
                    last_error = ProviderRateLimitError(self.provider_name, self.model_name)
                elif code >= 500:
                    last_error = ProviderUnavailableError(self.provider_name, self.model_name)
                else:
                    # 4xx: a bad key, an unknown model, an invalid request.
                    # Retrying cannot fix it; unavailable lets the factory fall
                    # back to another provider.
                    raise ProviderUnavailableError(self.provider_name, self.model_name) from exc
            except (asyncio.TimeoutError, TimeoutError) as exc:
                last_error = ProviderTimeoutError(self.provider_name, self.model_name, self.timeout_seconds)
                last_error.__cause__ = exc
            except Exception as exc:  # network errors from the HTTP client
                if "timeout" in type(exc).__name__.lower():
                    last_error = ProviderTimeoutError(self.provider_name, self.model_name, self.timeout_seconds)
                else:
                    last_error = ProviderUnavailableError(self.provider_name, self.model_name)
                last_error.__cause__ = exc
            else:
                if self._blocked(response):
                    # Not retried: a blocked prompt is blocked every time.
                    raise ProviderSafetyError(
                        self.provider_name, self.model_name, "Response blocked by safety filter"
                    )
                return response
            if attempt < self.max_retries - 1:
                await asyncio.sleep(self.retry_delay * (2 ** attempt))
        raise last_error

    def _parse_response(self, response: Any, modality: Modality) -> AnalysisResponse:
        """Parse Gemini response into structured AnalysisResponse."""
        result = AnalysisResponse(
            provider=self.provider_name,
            model=self.model_name,
            modality=modality,
        )
        try:
            response_text = response.text if hasattr(response, 'text') else str(response)
            if response_text is None:
                raise ValueError("empty or blocked response")
            response_text = _strip_code_fence(response_text)
            if response_text.strip().startswith('{'):
                data = json.loads(response_text)
                self._populate_from_dict(result, data)
            else:
                result.raw_response = response_text
                self._extract_from_text(result, response_text)
            if hasattr(response, 'usage_metadata'):
                usage = response.usage_metadata
                result.token_usage = {
                    "prompt_tokens": getattr(usage, 'prompt_token_count', 0),
                    "completion_tokens": getattr(usage, 'candidates_token_count', 0),
                    "total_tokens": getattr(usage, 'total_token_count', 0),
                }
        except json.JSONDecodeError:
            result.raw_response = response_text
            self._extract_from_text(result, response_text)
        except Exception as e:
            # Includes Gemini refusing to answer (`response.text` raises when
            # the candidate was blocked). An unreadable answer is not
            # reassurance: ask for a clinician rather than defaulting to the
            # model contract's "routine".
            result.raw_response = str(e)
            result.safety_flags.append(f"provider_response_unreadable:{type(e).__name__}")
            # Escalate only: the model may already have said "emergency"
            # before a later field failed to parse.
            result.urgency = clinical_triage.max_urgency(result.urgency, "see_doctor_soon")
            result.requires_professional_review = True
            if not result.recommended_next_step:
                result.recommended_next_step = (
                    "We could not complete this assessment. Please see a clinician, "
                    "and seek emergency care if your symptoms are severe."
                )
        return result
    
    def _populate_from_dict(self, result: AnalysisResponse, data: Dict[str, Any]):
        """Populate AnalysisResponse from parsed JSON."""
        # A missing urgency is not reassurance.
        result.urgency = data.get("urgency") or "see_doctor_soon"
        result.recommended_next_step = data.get("recommended_next_step", "")
        result.confidence_score = float(data.get("confidence_score", 0.0))
        result.uncertainty = data.get("uncertainty", "")
        result.requires_professional_review = data.get("requires_professional_review", False)
        result.safety_notice = data.get("safety_notice", "")
        result.warning_signs = data.get("warning_signs", [])
        result.follow_up_questions = data.get("follow_up_questions", [])
        result.safety_flags = data.get("safety_flags", [])
        if "image_assessment" in data and data["image_assessment"]:
            img_data = data["image_assessment"]
            result.image_assessment = ImageAssessment(
                observations=img_data.get("observations", []),
                possible_explanations=parse_items(
                    PossibleExplanation, img_data.get("possible_explanations")
                ),
                limitations=img_data.get("limitations", []),
                requires_better_image=img_data.get("requires_better_image", False),
                quality_issues=img_data.get("quality_issues", []),
            )
            if "image_quality" in img_data and img_data["image_quality"]:
                result.image_assessment.image_quality = ImageQuality(**img_data["image_quality"])
        result.possible_explanations = parse_items(
            PossibleExplanation, data.get("possible_explanations")
        )
        result.medical_information = parse_items(MedicalInformation, data.get("medical_information"))
        result.treatment_information = parse_items(
            TreatmentInformation, data.get("treatment_information")
        )
        result.sources = parse_items(Source, data.get("sources"))
    
    def _extract_from_text(self, result: AnalysisResponse, text: str):
        """Fallback extraction from unstructured text."""
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["emergency", "immediately", "call 911", "emergency room"]):
            result.urgency = "emergency"
        elif any(kw in text_lower for kw in ["urgent", "within 24 hours", "see doctor soon"]):
            result.urgency = "urgent"
        elif any(kw in text_lower for kw in ["routine", "schedule appointment", "follow up"]):
            result.urgency = "routine"
        else:
            result.urgency = "routine"
        result.recommended_next_step = text[:500]
        result.uncertainty = "Response was not in structured format; extracted from text."
    
    def _record_metrics(self, result: AnalysisResponse, start_time: float):
        """Record request metrics."""
        latency_ms = int((time.time() - start_time) * 1000)
        prompt_tokens = result.token_usage.get("prompt_tokens", 0)
        completion_tokens = result.token_usage.get("completion_tokens", 0)
        total_tokens = result.token_usage.get("total_tokens", prompt_tokens + completion_tokens)
        tokens = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        tokens.estimated_cost_usd = self.estimate_cost(tokens)
        self.record_request(latency_ms, tokens)
    
    def _record_error(self, error: Exception, start_time: float):
        """Record error metrics."""
        latency_ms = int((time.time() - start_time) * 1000)
        self.record_request(latency_ms, TokenUsage(), str(error))
    
    def estimate_cost(self, tokens: TokenUsage) -> float:
        """Not estimated: prices change and a stale table misled budgets."""
        return 0.0
    
    async def health_check(self) -> bool:
        """Check that the configured model answers."""
        try:
            await self._client.aio.models.generate_content(
                model=self.model_name,
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=5),
            )
            return True
        except Exception:
            return False
