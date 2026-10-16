"""
Gemini Provider Implementation

Implements the MultimodalAIProvider interface for Google's Gemini models.
Uses the current google-generativeai SDK with structured output support.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

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
)


class GeminiProvider(MultimodalAIProvider):
    """
    Google Gemini provider for multimodal AI analysis.
    
    Supports:
    - Text analysis (gemini-1.5-pro, gemini-1.5-flash)
    - Image analysis (vision)
    - Multimodal analysis (text + image)
    - Structured output via response_schema
    - Medical safety settings
    """
    
    # Model configurations
    MODELS = {
        "gemini-1.5-pro": {
            "context_window": 2_000_000,
            "max_output_tokens": 8192,
            "cost_per_1k_input": 0.00125,
            "cost_per_1k_output": 0.005,
            "cost_per_image": 0.000125,
        },
        "gemini-1.5-flash": {
            "context_window": 1_000_000,
            "max_output_tokens": 8192,
            "cost_per_1k_input": 0.000075,
            "cost_per_1k_output": 0.0003,
            "cost_per_image": 0.0000375,
        },
        "gemini-1.0-pro-vision": {
            "context_window": 16384,
            "max_output_tokens": 2048,
            "cost_per_1k_input": 0.0005,
            "cost_per_1k_output": 0.0015,
            "cost_per_image": 0.0025,
        },
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        
        # Configuration
        self.api_key = config.get("api_key") or os.getenv("GEMINI_API_KEY")
        self.model_name = config.get("model", "gemini-1.5-pro")
        self.temperature = config.get("temperature", 0.3)
        self.max_tokens = config.get("max_tokens")
        self.timeout_seconds = config.get("timeout_seconds", 60.0)
        self.max_retries = config.get("max_retries", 3)
        self.retry_delay = config.get("retry_delay_seconds", 1.0)
        
        if not self.api_key:
            raise ProviderInvalidRequestError(
                "gemini", self.model_name,
                "GEMINI_API_KEY not configured"
            )
        
        # Configure the SDK
        genai.configure(api_key=self.api_key)
        
        # Safety settings for medical content
        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        }
        
        # Initialize model
        self._model = genai.GenerativeModel(
            model_name=self.model_name,
            safety_settings=self.safety_settings,
            generation_config=genai.GenerationConfig(
                temperature=self.temperature,
                max_output_tokens=self.max_tokens or self.MODELS.get(self.model_name, {}).get("max_output_tokens", 8192),
                response_mime_type="application/json",
            )
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
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if content:
                    prompt_parts.append(f"[{role.upper()}]: {content}")
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
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if content:
                parts.append(f"[{role.upper()}]: {content}")
        parts.append(f"[PATIENT]: {request.text}")
        if request.patient_context:
            parts.append(f"[CONTEXT]: {json.dumps(request.patient_context)}")
        return "\n\n".join(parts)
    
    async def _prepare_images(self, images: List[ImageInput]) -> List[Dict[str, Any]]:
        """Convert ImageInput objects to Gemini-compatible parts."""
        parts = []
        for img in images:
            if img.image_data:
                image_bytes = base64.b64decode(img.image_data)
                parts.append({"mime_type": img.mime_type, "data": image_bytes})
            elif img.image_url:
                raise ProviderInvalidRequestError(
                    self.provider_name, self.model_name,
                    "Image URLs not supported directly; use base64 image_data"
                )
        return parts
    
    async def _generate_with_retry(self, prompt: Any) -> Any:
        """Generate content with retry logic."""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, lambda: self._model.generate_content(prompt)
                )
                if response.candidates and response.candidates[0].finish_reason == 3:
                    raise ProviderSafetyError(
                        self.provider_name, self.model_name,
                        "Response blocked by safety filter"
                    )
                return response
            except ProviderSafetyError:
                # A blocked prompt is blocked every time; retrying only delays
                # the patient's answer.
                raise
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
                else:
                    break
        if "quota" in str(last_error).lower() or "rate" in str(last_error).lower():
            raise ProviderRateLimitError(self.provider_name, self.model_name)
        elif "timeout" in str(last_error).lower():
            raise ProviderTimeoutError(self.provider_name, self.model_name, self.timeout_seconds)
        elif "unavailable" in str(last_error).lower() or "503" in str(last_error):
            raise ProviderUnavailableError(self.provider_name, self.model_name)
        raise ProviderError(f"Generation failed: {last_error}", self.provider_name, self.model_name)
    
    def _parse_response(self, response: Any, modality: Modality) -> AnalysisResponse:
        """Parse Gemini response into structured AnalysisResponse."""
        result = AnalysisResponse(
            provider=self.provider_name,
            model=self.model_name,
            modality=modality,
        )
        try:
            response_text = response.text if hasattr(response, 'text') else str(response)
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
                possible_explanations=[
                    PossibleExplanation(**exp) for exp in img_data.get("possible_explanations", [])
                ],
                limitations=img_data.get("limitations", []),
                requires_better_image=img_data.get("requires_better_image", False),
                quality_issues=img_data.get("quality_issues", []),
            )
            if "image_quality" in img_data and img_data["image_quality"]:
                result.image_assessment.image_quality = ImageQuality(**img_data["image_quality"])
        result.medical_information = [
            MedicalInformation(**mi) for mi in data.get("medical_information", [])
        ]
        result.treatment_information = [
            TreatmentInformation(**ti) for ti in data.get("treatment_information", [])
        ]
        result.sources = [Source(**s) for s in data.get("sources", [])]
    
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
        """Check if Gemini API is accessible."""
        try:
            test_model = genai.GenerativeModel("gemini-1.5-flash")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: test_model.generate_content("test", 
                    generation_config=genai.GenerationConfig(max_output_tokens=5))
            )
            return True
        except Exception:
            return False
