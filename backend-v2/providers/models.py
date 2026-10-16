"""
Provider-agnostic request/response models for multimodal AI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, HttpUrl
import uuid


# =============================================================================
# Capability Definitions
# =============================================================================

class Modality(str, Enum):
    """Supported input modalities."""
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


class ProviderCapabilities(BaseModel):
    """What a provider can do."""
    provider_name: str
    supports_text: bool = True
    supports_vision: bool = False
    supports_audio: bool = False
    supports_video: bool = False
    supports_document: bool = False
    max_image_size_mb: int = 10
    supported_image_formats: List[str] = field(default_factory=lambda: ["jpeg", "png", "webp"])
    supported_audio_formats: List[str] = field(default_factory=list)
    context_window: int = 8192
    max_output_tokens: int = 4096
    supports_structured_output: bool = True
    supports_streaming: bool = False
    supported_languages: List[str] = field(default_factory=lambda: ["en"])
    medical_safety_trained: bool = False


# =============================================================================
# Input Models
# =============================================================================

class ImageInput(BaseModel):
    """Image input for vision-capable providers."""
    # Either provide image_data (base64) OR image_url (pre-signed URL)
    image_data: Optional[str] = None  # base64 encoded
    image_url: Optional[HttpUrl] = None
    mime_type: str = "image/jpeg"
    filename: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Quality assessment results (filled by validation pipeline)
    quality_score: Optional[float] = None
    quality_details: Dict[str, Any] = field(default_factory=dict)


class AudioInput(BaseModel):
    """Audio input for audio-capable providers."""
    audio_data: Optional[str] = None  # base64 encoded
    audio_url: Optional[HttpUrl] = None
    mime_type: str = "audio/wav"
    duration_seconds: Optional[float] = None
    language: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class TextAnalysisRequest(BaseModel):
    """Request for text-only analysis."""
    text: str
    system_prompt: Optional[str] = None
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    patient_context: Optional[Dict[str, Any]] = None
    temperature: float = 0.3
    max_tokens: Optional[int] = None
    response_schema: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ImageAnalysisRequest(BaseModel):
    """Request for image analysis."""
    images: List[ImageInput] = Field(..., min_items=1)
    prompt: str  # What to analyze in the image
    system_prompt: Optional[str] = None
    patient_context: Optional[Dict[str, Any]] = None
    temperature: float = 0.2  # Lower for medical consistency
    max_tokens: Optional[int] = None
    response_schema: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class MultimodalAnalysisRequest(BaseModel):
    """Request for combined multimodal analysis."""
    text: Optional[str] = None
    images: List[ImageInput] = field(default_factory=list)
    audio: List[AudioInput] = field(default_factory=list)
    system_prompt: Optional[str] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    patient_context: Optional[Dict[str, Any]] = None
    temperature: float = 0.3
    max_tokens: Optional[int] = None
    response_schema: Optional[Dict[str, Any]] = None
# =============================================================================
# Output Models (Structured Medical Response)
# =============================================================================

class ImageQuality(BaseModel):
    """Image quality assessment results."""
    overall_score: float  # 0.0 - 1.0
    resolution: Dict[str, int]  # width, height
    brightness_score: float
    contrast_score: float
    blur_score: float
    is_usable: bool
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class PossibleExplanation(BaseModel):
    """A possible medical explanation for observations."""
    condition: str
    likelihood: str  # "possible" | "likely" | "unlikely" | "differential"
    confidence: float  # 0.0 - 1.0
    reasoning: str
    supporting_observations: List[str] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)
    icd10_code: Optional[str] = None


class ImageAssessment(BaseModel):
    """Structured image assessment output."""
    observations: List[str] = field(default_factory=list)
    possible_explanations: List[PossibleExplanation] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    image_quality: Optional[ImageQuality] = None
    requires_better_image: bool = False
    quality_issues: List[str] = field(default_factory=list)


class MedicalInformation(BaseModel):
    """Evidence-based medical information."""
    topic: str
    content: str
    source: str
    source_type: str  # "guideline" | "literature" | "protocol" | "consensus"
    relevance_score: float
    citation: Optional[str] = None


class TreatmentInformation(BaseModel):
    """Evidence-based treatment guidance."""
    condition: str
    intervention: str
    description: str
    evidence_level: str  # "A" | "B" | "C" | "D" | "expert_opinion"
    source: str
    contraindications: List[str] = field(default_factory=list)
    precautions: List[str] = field(default_factory=list)
    dosage_info: Optional[str] = None


class Source(BaseModel):
    """Citation/source reference."""
    id: str
    title: str
    type: str  # "guideline" | "pubmed" | "textbook" | "protocol" | "other"
    url: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    publication_date: Optional[str] = None
    snippet: Optional[str] = None


class AnalysisResponse(BaseModel):
    """Unified response from any provider."""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    provider: str
    model: str
    modality: Modality
    
    # Core medical output
    image_assessment: Optional[ImageAssessment] = None
    urgency: str = "routine"  # emergency | urgent | routine | self_care
    recommended_next_step: str = ""
    #: Differential for the patient's description (text, voice or images).
    #: Image-specific ones also live on `image_assessment`.
    possible_explanations: List[PossibleExplanation] = field(default_factory=list)
    
    # Evidence-based information
    medical_information: List[MedicalInformation] = field(default_factory=list)
    treatment_information: List[TreatmentInformation] = field(default_factory=list)
    warning_signs: List[str] = field(default_factory=list)
    follow_up_questions: List[str] = field(default_factory=list)
    
    # Metadata
    sources: List[Source] = field(default_factory=list)
    uncertainty: str = ""
    requires_professional_review: bool = False
    safety_notice: str = ""
    
    # Provider metadata
    confidence_score: float = 0.0
    processing_time_ms: int = 0
    token_usage: Dict[str, int] = field(default_factory=dict)
    raw_response: Optional[str] = None  # For debugging/audit
    
    # Safety
    safety_flags: List[str] = field(default_factory=list)
    content_filtered: bool = False
    
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
# =============================================================================
# Usage/Cost Tracking
# =============================================================================

@dataclass
class TokenUsage:
    """Token usage for cost tracking."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    image_tokens: int = 0
    
    def add(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            estimated_cost_usd=self.estimated_cost_usd + other.estimated_cost_usd,
            image_tokens=self.image_tokens + other.image_tokens,
        )


@dataclass
class ProviderMetrics:
    """Metrics for provider monitoring."""
    provider: str
    model: str
    request_count: int = 0
    error_count: int = 0
    total_latency_ms: int = 0
    total_tokens: TokenUsage = field(default_factory=TokenUsage)
    last_used: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)


# =============================================================================
# Exceptions
# =============================================================================

class ProviderError(Exception):
    """Base provider exception."""
    def __init__(self, message: str, provider: str, model: str, code: str = "PROVIDER_ERROR"):
        self.provider = provider
        self.model = model
        self.code = code
        super().__init__(message)


class ProviderUnavailableError(ProviderError):
    """Provider is temporarily unavailable."""
    def __init__(self, provider: str, model: str, message: str = "Provider unavailable"):
        super().__init__(message, provider, model, "PROVIDER_UNAVAILABLE")


class ProviderRateLimitError(ProviderError):
    """Provider rate limit exceeded."""
    def __init__(self, provider: str, model: str, retry_after_seconds: Optional[int] = None):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Rate limit exceeded", provider, model, "RATE_LIMIT")


class ProviderInvalidRequestError(ProviderError):
    """Invalid request to provider."""
    def __init__(self, provider: str, model: str, message: str):
        super().__init__(message, provider, model, "INVALID_REQUEST")


class ProviderSafetyError(ProviderError):
    """Safety filter triggered."""
    def __init__(self, provider: str, model: str, message: str = "Content blocked by safety filter"):
        super().__init__(message, provider, model, "SAFETY_VIOLATION")


class ProviderTimeoutError(ProviderError):
    """Provider request timed out."""
    def __init__(self, provider: str, model: str, timeout_seconds: float):
        super().__init__(f"Request timed out after {timeout_seconds}s", provider, model, "TIMEOUT")
# =============================================================================
# Abstract Base Provider
# =============================================================================

_items_logger = logging.getLogger("providers.models")


def parse_items(model, items: Any) -> List[Any]:
    """Validate each item of a model-provided list, skipping invalid ones.

    A single malformed entry (a missing field, a wrong type) used to raise and
    discard the provider's entire answer.
    """
    parsed = []
    for index, item in enumerate(items if isinstance(items, list) else []):
        if not isinstance(item, dict):
            _items_logger.warning("provider_item_discarded model=%s index=%d reason=not_an_object",
                                  model.__name__, index)
            continue
        try:
            parsed.append(model.model_validate(item))
        except Exception as exc:  # noqa: BLE001 - pydantic.ValidationError and friends
            fields = sorted({str(err.get("loc", ("?",))[0]) for err in getattr(exc, "errors", lambda: [])()})
            _items_logger.warning("provider_item_discarded model=%s index=%d fields=%s",
                                  model.__name__, index, ",".join(fields) or type(exc).__name__)
    return parsed


from abc import ABC, abstractmethod


class MultimodalAIProvider(ABC):
    """
    Abstract base class for all multimodal AI providers.
    
    All providers must implement the core analysis methods and
    provide capability information.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        # Defer metrics initialization until after child class __init__ completes
        self._metrics = None
    
    def _init_metrics(self):
        """Initialize metrics after child class initialization."""
        if self._metrics is None:
            self._metrics = ProviderMetrics(
                provider=self.provider_name,
                model=self.default_model
            )
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier (e.g., 'gemini', 'openai')."""
        pass
    
    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model name for this provider."""
        pass
    
    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Return provider capabilities."""
        pass
    
    # -------------------------------------------------------------------------
    # Core Analysis Methods
    # -------------------------------------------------------------------------
    
    @abstractmethod
    async def analyze_text(self, request: TextAnalysisRequest) -> AnalysisResponse:
        """Analyze text input. Must be implemented by text-capable providers."""
        pass
    
    @abstractmethod
    async def analyze_image(self, request: ImageAnalysisRequest) -> AnalysisResponse:
        """Analyze image input. Must be implemented by vision-capable providers."""
        pass
    
    @abstractmethod
    async def analyze_multimodal(self, request: MultimodalAnalysisRequest) -> AnalysisResponse:
        """Analyze combined multimodal input. Must be implemented by multimodal providers."""
        pass
    
    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    
    def get_metrics(self) -> ProviderMetrics:
        """Return provider usage metrics."""
        self._init_metrics()
        return self._metrics
    
    def record_request(self, latency_ms: int, tokens: TokenUsage, error: Optional[str] = None):
        """Record request metrics."""
        self._init_metrics()
        self._metrics.request_count += 1
        self._metrics.total_latency_ms += latency_ms
        self._metrics.total_tokens = self._metrics.total_tokens.add(tokens)
        self._metrics.last_used = datetime.utcnow()
        if error:
            self._metrics.error_count += 1
            self._metrics.errors.append(f"{datetime.utcnow().isoformat()}: {error}")
    
    def estimate_cost(self, tokens: TokenUsage) -> float:
        """Estimate cost in USD for token usage. Override in subclasses."""
        return tokens.estimated_cost_usd
    
    async def health_check(self) -> bool:
        """Check if provider is available. Override for custom checks."""
        return True


# =============================================================================
# Provider Registry
# =============================================================================

class ProviderRegistry:
    """Registry of available providers."""
    
    _providers: Dict[str, type] = {}
    _instances: Dict[str, MultimodalAIProvider] = {}
    
    @classmethod
    def register(cls, provider_class: type) -> type:
        """Register a provider class."""
        # Don't instantiate - just register the class
        # Provider name will be available via the class property
        temp_instance = provider_class.__new__(provider_class)
        temp_instance.__dict__ = {}
        # We can't access provider_name without initializing, so we'll defer
        cls._providers[provider_class.__name__.lower().replace('provider', '')] = provider_class
        return provider_class
    
    @classmethod
    def get_provider_class(cls, name: str) -> Optional[type]:
        """Get provider class by name."""
        return cls._providers.get(name)
    
    @classmethod
    def create_provider(cls, name: str, config: Optional[Dict[str, Any]] = None) -> MultimodalAIProvider:
        """Create or get cached provider instance."""
        if name not in cls._instances:
            provider_class = cls.get_provider_class(name)
            if not provider_class:
                raise ProviderError(f"Unknown provider: {name}", name, "", "UNKNOWN_PROVIDER")
            cls._instances[name] = provider_class(config)
        return cls._instances[name]
    
    @classmethod
    def get_all_capabilities(cls) -> Dict[str, ProviderCapabilities]:
        """Get capabilities of all registered providers."""
        return {
            name: provider_class().capabilities 
            for name, provider_class in cls._providers.items()
        }
    
    @classmethod
    def list_providers(cls) -> List[str]:
        """List registered provider names."""
        return list(cls._providers.keys())


# =============================================================================
# Configuration Models
# =============================================================================

class ProviderConfig(BaseModel):
    """Configuration for a specific provider."""
    provider: str
    model: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    temperature: float = 0.3
    max_tokens: Optional[int] = None
    timeout_seconds: float = 60.0
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    extra_params: Dict[str, Any] = field(default_factory=dict)


class MultimodalConfig(BaseModel):
    """Global multimodal AI configuration."""
    text_provider: ProviderConfig
    vision_provider: ProviderConfig
    multimodal_provider: ProviderConfig
    
    # Fallback configuration
    enable_fallback: bool = True
    fallback_providers: List[str] = field(default_factory=list)
    
    # Cost controls
    max_cost_per_request_usd: float = 1.0
    daily_budget_usd: Optional[float] = None
    
    # Safety
    safety_threshold: float = 0.7
    require_professional_review_threshold: float = 0.8
    
    class Config:
        arbitrary_types_allowed = True
class PatientProfile(BaseModel):
    """Patient profile for provider context."""
    age: Optional[int] = None
    sex: Optional[str] = None
    location: Optional[str] = None
    pregnancy_status: Optional[bool] = None
    chronic_conditions: List[str] = Field(default_factory=list)
    medications: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    language: str = "en"

class ConversationTurn(BaseModel):
    """A single turn in a conversation."""
    role: str
    content: str
    modality: Optional[str] = "text"
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
