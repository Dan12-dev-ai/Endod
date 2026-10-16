"""
Multimodal Orchestrator

Coordinates multimodal AI analysis by:
1. Detecting input modalities
2. Building clinical context
3. Selecting appropriate provider
4. Invoking AI with structured output
5. Running safety validation
6. Returning unified response
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import clinical_triage

from .models import (
    Modality,
    MultimodalAIProvider,
    ImageInput,
    AudioInput,
    TextAnalysisRequest,
    ImageAnalysisRequest,
    MultimodalAnalysisRequest,
    AnalysisResponse,
    ImageAssessment,
    PossibleExplanation,
    MedicalInformation,
    TreatmentInformation,
    Source,
    TokenUsage,
    ProviderError,
)
from .provider_factory import ProviderFactory
from .image_validation import ImageValidationPipeline, QualityAssessment


# =============================================================================
# Context Models
# =============================================================================

@dataclass
class ConversationTurn:
    """A single turn in the conversation."""
    role: str
    content: str
    modality: Modality = Modality.TEXT
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PatientProfile:
    """Patient profile for context."""
    age: Optional[int] = None
    sex: Optional[str] = None
    location: Optional[str] = None
    pregnancy_status: Optional[bool] = None
    chronic_conditions: List[str] = field(default_factory=list)
    medications: List[str] = field(default_factory=list)
    allergies: List[str] = field(default_factory=list)
    language: str = "en"


@dataclass
class MultimodalClinicalContext:
    """Complete clinical context for AI analysis."""
    text: Optional[str] = None
    voice_transcript: Optional[str] = None
    image_analysis: Optional[AnalysisResponse] = None
    image_quality: Optional[QualityAssessment] = None
    conversation_history: List[ConversationTurn] = field(default_factory=list)
    patient_profile: Optional[PatientProfile] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
# =============================================================================
# Multimodal Context Builder
# =============================================================================

class MultimodalContextBuilder:
    """Builds clinical context from multimodal inputs."""
    
    def __init__(self, image_pipeline: Optional[ImageValidationPipeline] = None):
        self.image_pipeline = image_pipeline or ImageValidationPipeline()
    
    async def build_context(
        self,
        text: Optional[str] = None,
        voice_transcript: Optional[str] = None,
        images: Optional[List[ImageInput]] = None,
        audio: Optional[List[AudioInput]] = None,
        conversation_history: Optional[List[ConversationTurn]] = None,
        patient_profile: Optional[PatientProfile] = None,
        session_id: Optional[str] = None,
    ) -> MultimodalClinicalContext:
        context = MultimodalClinicalContext(
            text=text,
            voice_transcript=voice_transcript,
            conversation_history=conversation_history or [],
            patient_profile=patient_profile,
            session_id=session_id,
        )
        
        if images:
            quality_results = []
            for img in images:
                if img.image_data:
                    import base64
                    image_bytes = base64.b64decode(img.image_data)
                elif img.image_url:
                    continue
                else:
                    continue
                
                validation, quality = self.image_pipeline.process(
                    image_bytes, img.filename or ""
                )
                
                if validation.is_valid:
                    quality_results.append(quality)
                    img.quality_score = quality.overall_score
                    img.quality_details = {
                        "resolution": quality.resolution,
                        "brightness": quality.brightness_score,
                        "contrast": quality.contrast_score,
                        "blur": quality.blur_score,
                        "is_usable": quality.is_usable,
                        "issues": quality.issues,
                    }
            
            if quality_results:
                best_quality = max(quality_results, key=lambda q: q.overall_score)
                context.image_quality = best_quality
        
        return context
    
    def build_provider_request(
        self,
        context: MultimodalClinicalContext,
        system_prompt: Optional[str] = None,
    ) -> MultimodalAnalysisRequest:
        combined_text = None
        if context.text and context.voice_transcript:
            combined_text = f"{context.text}\n\n[Voice Input]: {context.voice_transcript}"
        elif context.text:
            combined_text = context.text
        elif context.voice_transcript:
            combined_text = context.voice_transcript
        
        return MultimodalAnalysisRequest(
            text=combined_text,
            images=[],
            audio=[],
            system_prompt=system_prompt or self._get_default_system_prompt(),
            conversation_history=[
                {"role": t.role, "content": t.content}
                for t in context.conversation_history
            ],
            patient_context=self._patient_profile_to_dict(context.patient_profile) if context.patient_profile else None,
        )
    
    def _get_default_system_prompt(self) -> str:
        return """You are DEDAN Health's medical AI assistant. Analyze the patient's input (text, images, voice) and provide structured medical guidance.

CRITICAL RULES:
1. NEVER claim certainty from visual evidence alone. Use "may be consistent with", "cannot be reliably determined", "suggests".
2. Distinguish OBSERVATION (what you see) from INTERPRETATION (what it might mean).
3. Always include uncertainty and limitations.
4. Ground treatment information in verified medical sources.
5. Escalate to professional review when uncertain or high-risk.

OUTPUT FORMAT (JSON):
{
  "urgency": "emergency|urgent|routine|self_care",
  "recommended_next_step": "specific actionable guidance",
  "image_assessment": {
    "observations": ["visible finding 1", "visible finding 2"],
    "possible_explanations": [
      {"condition": "condition name", "likelihood": "possible|likely|unlikely", "confidence": 0.0-1.0, "reasoning": "why", "citations": ["source1"]}
    ],
    "limitations": ["limitation 1", "limitation 2"],
    "requires_better_image": false,
    "quality_issues": []
  },
  "medical_information": [{"topic": "", "content": "", "source": "", "source_type": "guideline|literature|protocol", "relevance_score": 0.0}],
  "treatment_information": [{"condition": "", "intervention": "", "description": "", "evidence_level": "A|B|C|D|expert_opinion", "source": ""}],
  "warning_signs": ["sign 1", "sign 2"],
  "follow_up_questions": ["question 1", "question 2"],
  "sources": [{"id": "", "title": "", "type": "guideline|pubmed|textbook", "url": ""}],
  "uncertainty": "explicit uncertainty statement",
  "requires_professional_review": true/false,
  "safety_notice": "standard medical disclaimer",
  "confidence_score": 0.0-1.0
}"""
    
    def _patient_profile_to_dict(self, profile: Optional[PatientProfile]) -> Optional[Dict[str, Any]]:
        if not profile:
            return None
        return {
            "age": profile.age,
            "sex": profile.sex,
            "location": profile.location,
            "pregnancy_status": profile.pregnancy_status,
            "chronic_conditions": profile.chronic_conditions,
            "medications": profile.medications,
            "allergies": profile.allergies,
            "language": profile.language,
        }

# =============================================================================
# Safety Validator
# =============================================================================

class SafetyValidator:
    """Validates AI responses for medical safety."""
    
    REVIEW_TRIGGERS = {
        "high_risk": ["pregnancy", "child", "infant", "elderly", "immunocompromised", "cancer"],
        "uncertainty": ["cannot determine", "unclear", "insufficient", "need better image", "blurry", "dark"],
    }
    
    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold
    
    def validate(self, response: AnalysisResponse, context: MultimodalClinicalContext) -> AnalysisResponse:
        # Red-flag rules on what the patient said (text and voice). This used
        # to force any emergency keyword to "urgent", which capped real
        # emergencies below "emergency"; it now escalates only.
        profile = context.patient_profile
        triage = clinical_triage.assess(
            " ".join(filter(None, [context.text, context.voice_transcript])),
            age_years=profile.age if profile else None,
            pregnant=bool(profile and profile.pregnancy_status),
        )
        if clinical_triage.urgency_rank(triage.urgency) > clinical_triage.urgency_rank(response.urgency):
            response.safety_flags.append(f"triage_escalation:{triage.urgency}")
            response.urgency = triage.urgency
        if clinical_triage.urgency_rank(triage.urgency) >= clinical_triage.urgency_rank("urgent"):
            response.requires_professional_review = True
        
        if context.patient_profile:
            if context.patient_profile.pregnancy_status:
                response.safety_flags.append("pregnant_patient")
                response.requires_professional_review = True
            # `is not None`: age 0 (an infant) is falsy.
            if context.patient_profile.age is not None and context.patient_profile.age < 5:
                response.safety_flags.append("pediatric_patient")
                response.requires_professional_review = True
            if context.patient_profile.age is not None and context.patient_profile.age >= 75:
                response.safety_flags.append("geriatric_patient")
        
        if context.image_quality and not context.image_quality.is_usable:
            response.safety_flags.append("poor_image_quality")
            response.requires_professional_review = True
            if response.image_assessment:
                response.image_assessment.requires_better_image = True
                response.image_assessment.quality_issues.extend(context.image_quality.issues)
        
        if response.uncertainty and any(
            kw in response.uncertainty.lower() 
            for kw in self.REVIEW_TRIGGERS["uncertainty"]
        ):
            response.safety_flags.append("ai_uncertainty")
            response.requires_professional_review = True
        
        if response.confidence_score < self.threshold:
            response.safety_flags.append(f"low_confidence:{response.confidence_score:.2f}")
        
        if not response.safety_notice:
            response.safety_notice = (
                "DEDAN Health provides health guidance for informational purposes only. "
                "This is not a medical diagnosis. Seek professional medical care for "
                "any concerning symptoms or emergencies."
            )
        
        return response


# =============================================================================
# Audit Logger
# =============================================================================

class AuditLogger:
    """Logs AI operations for compliance and monitoring."""
    
    def __init__(self):
        self.logs: List[Dict[str, Any]] = []
    
    def log_request(
        self,
        request_id: str,
        session_id: Optional[str],
        input_modalities: List[Modality],
        provider: str,
        model: str,
        context: MultimodalClinicalContext,
    ):
        self.logs.append({
            "timestamp": datetime.utcnow().isoformat(),
            "event": "request",
            "request_id": request_id,
            "session_id": session_id,
            "input_modalities": [m.value for m in input_modalities],
            "provider": provider,
            "model": model,
            "has_patient_context": context.patient_profile is not None,
            "conversation_turns": len(context.conversation_history),
            "has_images": context.image_quality is not None,
        })
    
    def log_response(
        self,
        request_id: str,
        response: AnalysisResponse,
        latency_ms: int,
        token_usage: TokenUsage,
        cost_usd: float,
    ):
        self.logs.append({
            "timestamp": datetime.utcnow().isoformat(),
            "event": "response",
            "request_id": request_id,
            "provider": response.provider,
            "model": response.model,
            "urgency": response.urgency,
            "confidence_score": response.confidence_score,
            "requires_professional_review": response.requires_professional_review,
            "safety_flags": response.safety_flags,
            "latency_ms": latency_ms,
            "token_usage": {
                "prompt": token_usage.prompt_tokens,
                "completion": token_usage.completion_tokens,
                "total": token_usage.total_tokens,
            },
            "cost_usd": cost_usd,
        })
    
    def log_error(
        self,
        request_id: str,
        error: Exception,
        provider: str,
        model: str,
    ):
        self.logs.append({
            "timestamp": datetime.utcnow().isoformat(),
            "event": "error",
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "error_type": type(error).__name__,
            "error_message": str(error),
        })
    
    def get_logs(self, request_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if request_id:
            return [log for log in self.logs if log.get("request_id") == request_id]
        return self.logs
    
    def clear(self):
        self.logs.clear()

# =============================================================================
# Multimodal Orchestrator
# =============================================================================

class MultimodalOrchestrator:
    """
    Main orchestrator for multimodal AI analysis.
    
    Responsibilities:
    1. Detect input modalities
    2. Build clinical context
    3. Select appropriate provider
    4. Invoke AI with structured output
    5. Run safety validation
    6. Return unified response
    """
    
    def __init__(
        self,
        provider_factory: Optional[ProviderFactory] = None,
        context_builder: Optional[MultimodalContextBuilder] = None,
        safety_validator: Optional[SafetyValidator] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.provider_factory = provider_factory or ProviderFactory()
        self.context_builder = context_builder or MultimodalContextBuilder()
        self.safety_validator = safety_validator or SafetyValidator()
        self.audit_logger = audit_logger or AuditLogger()
    
    async def process(
        self,
        text: Optional[str] = None,
        voice_transcript: Optional[str] = None,
        images: Optional[List[ImageInput]] = None,
        audio: Optional[List[AudioInput]] = None,
        conversation_history: Optional[List[ConversationTurn]] = None,
        patient_profile: Optional[PatientProfile] = None,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> AnalysisResponse:
        request_id = str(uuid.uuid4())
        start_time = time.time()
        
        modalities = []
        if text: modalities.append(Modality.TEXT)
        if voice_transcript: modalities.append(Modality.AUDIO)
        if images: modalities.append(Modality.IMAGE)
        if audio: modalities.append(Modality.AUDIO)
        
        context = await self.context_builder.build_context(
            text=text,
            voice_transcript=voice_transcript,
            images=images,
            audio=audio,
            conversation_history=conversation_history,
            patient_profile=patient_profile,
            session_id=session_id,
        )
        
        provider = self.provider_factory.get_provider_for_modalities(
            has_text=bool(text or voice_transcript),
            has_image=bool(images),
            has_audio=bool(audio),
        )
        
        self.audit_logger.log_request(
            request_id, session_id, modalities,
            provider.provider_name, provider.default_model, context
        )
        
        try:
            provider_request = self.context_builder.build_provider_request(
                context, system_prompt
            )
            
            if images:
                provider_request.images = images
            if audio:
                provider_request.audio = audio
            
            response = await self.provider_factory.with_fallback(
                provider, "analyze_multimodal", provider_request
            )
            
            response = self.safety_validator.validate(response, context)
            
            latency_ms = int((time.time() - start_time) * 1000)
            response.processing_time_ms = latency_ms
            
            token_usage = TokenUsage(
                prompt_tokens=response.token_usage.get("prompt_tokens", 0),
                completion_tokens=response.token_usage.get("completion_tokens", 0),
                total_tokens=response.token_usage.get("total_tokens", 0),
            )
            cost = provider.estimate_cost(token_usage)
            
            self.audit_logger.log_response(
                request_id, response, latency_ms, token_usage, cost
            )
            
            return response
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            self.audit_logger.log_error(request_id, e, provider.provider_name, provider.default_model)
            raise
    
    async def process_text_only(
        self,
        text: str,
        conversation_history: Optional[List[ConversationTurn]] = None,
        patient_profile: Optional[PatientProfile] = None,
        session_id: Optional[str] = None,
    ) -> AnalysisResponse:
        return await self.process(
            text=text,
            conversation_history=conversation_history,
            patient_profile=patient_profile,
            session_id=session_id,
        )
    
    async def process_image_only(
        self,
        images: List[ImageInput],
        prompt: str = "Analyze this medical image for any visible abnormalities.",
        patient_profile: Optional[PatientProfile] = None,
        session_id: Optional[str] = None,
    ) -> AnalysisResponse:
        return await self.process(
            text=prompt,
            images=images,
            patient_profile=patient_profile,
            session_id=session_id,
        )
    
    async def health_check(self) -> Dict[str, bool]:
        return await self.provider_factory.health_check_all()
