"""
OpenAI Provider Implementation

Implements the MultimodalAIProvider interface for OpenAI's GPT models.
Supports GPT-4o, GPT-4o-mini, GPT-4-turbo with vision capabilities.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

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


class OpenAIProvider(MultimodalAIProvider):
    """
    OpenAI provider for multimodal AI analysis.
    
    Supports:
    - Text analysis (GPT-4o, GPT-4o-mini, GPT-4-turbo)
    - Image analysis (GPT-4o vision)
    - Multimodal analysis (text + image)
    - Structured output via response_format
    """
    
    MODELS = {
        "gpt-4o": {
            "context_window": 128_000,
            "max_output_tokens": 16384,
            "cost_per_1k_input": 0.0025,
            "cost_per_1k_output": 0.01,
            "cost_per_image": 0.001,
            "supports_vision": True,
        },
        "gpt-4o-mini": {
            "context_window": 128_000,
            "max_output_tokens": 16384,
            "cost_per_1k_input": 0.00015,
            "cost_per_1k_output": 0.0006,
            "cost_per_image": 0.0005,
            "supports_vision": True,
        },
        "gpt-4-turbo": {
            "context_window": 128_000,
            "max_output_tokens": 4096,
            "cost_per_1k_input": 0.01,
            "cost_per_1k_output": 0.03,
            "cost_per_image": 0.002,
            "supports_vision": True,
        },
        "gpt-3.5-turbo": {
            "context_window": 16384,
            "max_output_tokens": 4096,
            "cost_per_1k_input": 0.0005,
            "cost_per_1k_output": 0.0015,
            "cost_per_image": 0.0,
            "supports_vision": False,
        },
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        
        self.api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY")
        self.model_name = config.get("model", "gpt-4o")
        self.temperature = config.get("temperature", 0.3)
        self.max_tokens = config.get("max_tokens")
        self.timeout_seconds = config.get("timeout_seconds", 60.0)
        self.max_retries = config.get("max_retries", 3)
        self.retry_delay = config.get("retry_delay_seconds", 1.0)
        
        if not self.api_key:
            raise ProviderInvalidRequestError(
                "openai", self.model_name,
                "OPENAI_API_KEY not configured"
            )
        
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            timeout=self.timeout_seconds,
            max_retries=self.max_retries,
        )
    
    @property
    def provider_name(self) -> str:
        return "openai"
    
    @property
    def default_model(self) -> str:
        return self.model_name
    
    @property
    def capabilities(self) -> ProviderCapabilities:
        model_info = self.MODELS.get(self.model_name, {})
        return ProviderCapabilities(
            provider_name="openai",
            supports_text=True,
            supports_vision=model_info.get("supports_vision", False),
            supports_audio=False,
            supports_video=False,
            supports_document=False,
            max_image_size_mb=20,
            supported_image_formats=["jpeg", "png", "webp", "gif"],
            context_window=model_info.get("context_window", 128_000),
            max_output_tokens=model_info.get("max_output_tokens", 16384),
            supports_structured_output=True,
            supports_streaming=True,
            supported_languages=["en", "es", "fr", "de", "it", "pt", "zh", "ja", "ko", "ar", "hi", "sw"],
            medical_safety_trained=False,
        )
    # -------------------------------------------------------------------------
    # Core Analysis Methods
    # -------------------------------------------------------------------------
    
    async def analyze_text(self, request: TextAnalysisRequest) -> AnalysisResponse:
        """Analyze text input using OpenAI."""
        start_time = time.time()
        try:
            messages = self._build_messages(request)
            response = await self._call_api(messages, request)
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
        """Analyze image input using OpenAI vision."""
        start_time = time.time()
        try:
            messages = self._build_image_messages(request)
            response = await self._call_api(messages, request)
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
        """Analyze combined text + image input using OpenAI."""
        start_time = time.time()
        try:
            messages = self._build_multimodal_messages(request)
            response = await self._call_api(messages, request)
            modality = Modality.IMAGE if request.images else Modality.TEXT
            result = self._parse_response(response, modality)
            result.processing_time_ms = int((time.time() - start_time) * 1000)
            result.provider = self.provider_name
            result.model = self.model_name
            result.modality = modality
            self._record_metrics(result, start_time)
            return result
        except Exception as e:
            self._record_error(e, start_time)
            raise
    
    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    
    def _build_messages(self, request: TextAnalysisRequest) -> List[ChatCompletionMessageParam]:
        """Build messages for text analysis."""
        messages: List[ChatCompletionMessageParam] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        for turn in request.conversation_history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": request.text})
        if request.patient_context:
            messages.append({
                "role": "system",
                "content": f"Patient context: {json.dumps(request.patient_context)}"
            })
        return messages
    
    def _build_image_messages(self, request: ImageAnalysisRequest) -> List[ChatCompletionMessageParam]:
        """Build messages for image analysis."""
        messages: List[ChatCompletionMessageParam] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        content: List[Dict[str, Any]] = [{"type": "text", "text": request.prompt}]
        for img in request.images:
            if img.image_data:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img.mime_type};base64,{img.image_data}",
                        "detail": "high"
                    }
                })
            elif img.image_url:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": str(img.image_url), "detail": "high"}
                })
        messages.append({"role": "user", "content": content})
        return messages
    
    def _build_multimodal_messages(self, request: MultimodalAnalysisRequest) -> List[ChatCompletionMessageParam]:
        """Build messages for multimodal analysis."""
        messages: List[ChatCompletionMessageParam] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        for turn in request.conversation_history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
        content: List[Dict[str, Any]] = []
        if request.text:
            content.append({"type": "text", "text": request.text})
        for img in request.images:
            if img.image_data:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img.mime_type};base64,{img.image_data}",
                        "detail": "high"
                    }
                })
            elif img.image_url:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": str(img.image_url), "detail": "high"}
                })
        if content:
            messages.append({"role": "user", "content": content})
        if request.patient_context:
            messages.append({
                "role": "system",
                "content": f"Patient context: {json.dumps(request.patient_context)}"
            })
        return messages
    
    async def _call_api(self, messages: List[ChatCompletionMessageParam], request: Any) -> Any:
        """Call OpenAI API with structured output."""
        import openai

        response_format = {"type": "json_object"} if request.response_schema else {"type": "text"}
        try:
            return await self._client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens or self.MODELS.get(self.model_name, {}).get("max_output_tokens"),
                response_format=response_format,
            )
        # SDK errors are mapped onto the provider contract so the factory can
        # fall back (it only falls back on these types). Unmapped, a bad key or
        # an outage surfaced as a 500.
        except openai.RateLimitError as exc:
            raise ProviderRateLimitError(self.provider_name, self.model_name) from exc
        except openai.APITimeoutError as exc:
            raise ProviderTimeoutError(self.provider_name, self.model_name, self.timeout_seconds) from exc
        except openai.APIError as exc:
            raise ProviderUnavailableError(self.provider_name, self.model_name) from exc
    
    def _parse_response(self, response: Any, modality: Modality) -> AnalysisResponse:
        """Parse OpenAI response into structured AnalysisResponse."""
        result = AnalysisResponse(
            provider=self.provider_name,
            model=self.model_name,
            modality=modality,
        )
        try:
            response_text = response.choices[0].message.content
            if response_text:
                if response_text.strip().startswith('{'):
                    data = json.loads(response_text)
                    self._populate_from_dict(result, data)
                else:
                    result.raw_response = response_text
                    self._extract_from_text(result, response_text)
            if response.usage:
                result.token_usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
        except json.JSONDecodeError:
            result.raw_response = response_text
            self._extract_from_text(result, response_text)
        except Exception as e:
            # An unreadable answer is not reassurance: ask for a clinician
            # rather than defaulting to the model contract's "routine".
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
        model_info = self.MODELS.get(self.model_name, {})
        input_cost = (prompt_tokens / 1000) * model_info.get("cost_per_1k_input", 0)
        output_cost = (completion_tokens / 1000) * model_info.get("cost_per_1k_output", 0)
        tokens.estimated_cost_usd = input_cost + output_cost
        self.record_request(latency_ms, tokens)
    
    def _record_error(self, error: Exception, start_time: float):
        """Record error metrics."""
        latency_ms = int((time.time() - start_time) * 1000)
        self.record_request(latency_ms, TokenUsage(), str(error))
    
    def estimate_cost(self, tokens: TokenUsage) -> float:
        """Estimate cost for token usage."""
        model_info = self.MODELS.get(self.model_name, {})
        input_cost = (tokens.prompt_tokens / 1000) * model_info.get("cost_per_1k_input", 0)
        output_cost = (tokens.completion_tokens / 1000) * model_info.get("cost_per_1k_output", 0)
        image_cost = tokens.image_tokens * model_info.get("cost_per_image", 0)
        return input_cost + output_cost + image_cost
    
    async def health_check(self) -> bool:
        """Check if OpenAI API is accessible."""
        try:
            await self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5,
            )
            return True
        except Exception:
            return False
