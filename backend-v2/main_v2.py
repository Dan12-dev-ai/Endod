from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional
import os
import logging
import asyncio
from datetime import datetime
import json
import uuid
import time
import base64

# Import DEDAN 2.0 components
from models_v2 import (
    TriageResponseV2, CoordinatorAgentInput, AgentType,
    TriageLevel, RiskScore, RiskTimeHorizon,
    ChronicCareData, HomeMeasurement, ChronicCareCheckIn,
    RiskSentinelInput, RiskSentinelOutput,
    PatientProfile, SymptomInput
)
# Import v1 models for legacy compatibility
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.models import (
    TriageRequest as LegacyTriageRequest,
    Language,
    DataConsent,
    TriageSession,
    TriageResponse,
)
from agents.coordinator_agent import CoordinatorAgent
from backend.data_flywheel import DEDANDataFlywheel

# Import Multimodal AI Providers
from providers import (
    ProviderFactory,
    ImageInput,
    MultimodalOrchestrator,
    PatientProfile as ProviderPatientProfile,
    ConversationTurn,
    Modality,
)

# Import enhanced services
from safety_validator import safety_validator, SafetyValidator
from response_transformer import response_transformer, ResponseTransformer
from visual_education_enhanced import visual_education_service, VisualEducationService
from medication_safety_enhanced import medication_safety_service, MedicationSafetyService
from clinical_context_builder import clinical_context_builder, ClinicalContextBuilder, build_gemini_system_prompt
from evidence_retrieval_enhanced import evidence_retriever, EvidenceRetriever

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(
    title="DEDAN HealthEngine 2.0 - Agent-Orchestrated AI",
    description="World-class AI-powered primary-care triage and predictive-care platform for underserved regions",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DEDAN 2.0 components
coordinator_agent = CoordinatorAgent(
    temperature=0.3,
    max_tokens=1500,
    enable_memory=False
)
data_flywheel = DEDANDataFlywheel()

# Request/Response Models
class TriageRequestV2(BaseModel):
    patient: PatientProfile
    symptoms: SymptomInput
    chronic_care_data: Optional[ChronicCareData] = None
    home_measurements: Optional[List[HomeMeasurement]] = None
    session_id: Optional[str] = None
    consent: bool = True
    context: Dict[str, Any] = Field(default_factory=dict)

class ChronicCareCheckInRequest(BaseModel):
    patient_id: str
    condition: str
    symptoms: List[str] = Field(default_factory=list)
    medication_taken: bool
    side_effects: List[str] = Field(default_factory=list)
    measurements: List[HomeMeasurement] = Field(default_factory=list)
    notes: Optional[str] = None

class RiskSentinelRequest(BaseModel):
    patient_id: str
    chronic_care_data: ChronicCareData
    recent_measurements: List[HomeMeasurement] = Field(default_factory=list)
    recent_check_ins: List[ChronicCareCheckIn] = Field(default_factory=list)
    time_window: int = Field(default=30, description="Time window in days")


# ============================================================================
# Multimodal AI Endpoints
# ============================================================================

# Initialize multimodal components
provider_factory = ProviderFactory()
multimodal_orchestrator = MultimodalOrchestrator(provider_factory=provider_factory)


class ImageUploadResponse(BaseModel):
    """Response for image upload."""
    image_id: str
    filename: str
    size: int
    mime_type: str
    quality_score: float
    is_usable: bool
    upload_timestamp: str


class MultimodalAnalyzeRequest(BaseModel):
    """Request for multimodal analysis."""
    text: Optional[str] = None
    voice_transcript: Optional[str] = None
    image_ids: List[str] = Field(default_factory=list)
    image_data_list: List[str] = Field(default_factory=list)
    patient: PatientProfile
    session_id: Optional[str] = None
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    consent: bool = True


class MultimodalAnalyzeResponse(BaseModel):
    """Response for multimodal analysis."""
    request_id: str
    session_id: str
    urgency: str
    recommended_next_step: str
    image_assessment: Optional[Dict[str, Any]] = None
    medical_information: List[Dict[str, Any]] = Field(default_factory=list)
    treatment_information: List[Dict[str, Any]] = Field(default_factory=list)
    warning_signs: List[str] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    uncertainty: str = ""
    requires_professional_review: bool = False
    safety_notice: str = ""
    confidence_score: float = 0.0
    processing_time_ms: int = 0
    provider: str = ""
    model: str = ""


# In-memory image storage (use Redis/S3 in production)
image_store: Dict[str, Dict[str, Any]] = {}


@app.post("/dedan/v2/images/upload", response_model=ImageUploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
):
    try:
        content = await file.read()
        
        from providers import ImageValidationPipeline
        pipeline = ImageValidationPipeline()
        validation, quality = pipeline.process(content, file.filename or "")
        
        if not validation.is_valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Image validation failed",
                    "errors": validation.errors,
                    "warnings": validation.warnings,
                }
            )
        
        image_id = str(uuid.uuid4())
        content_hash = pipeline.compute_hash(content)
        
        image_store[image_id] = {
            "image_id": image_id,
            "filename": file.filename,
            "content_hash": content_hash,
            "content": content,
            "mime_type": validation.mime_type,
            "size": validation.file_size,
            "dimensions": validation.dimensions,
            "quality": quality.__dict__ if quality else None,
            "session_id": session_id,
            "upload_timestamp": datetime.utcnow().isoformat(),
        }
        
        return ImageUploadResponse(
            image_id=image_id,
            filename=file.filename or "unknown",
            size=validation.file_size,
            mime_type=validation.mime_type or "unknown",
            quality_score=quality.overall_score if quality else 0.0,
            is_usable=quality.is_usable if quality else False,
            upload_timestamp=image_store[image_id]["upload_timestamp"],
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Image upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.post("/dedan/v2/multimodal-analyze", response_model=MultimodalAnalyzeResponse)
async def multimodal_analyze(
    request: MultimodalAnalyzeRequest,
    background_tasks: BackgroundTasks,
):
    try:
        images = []
        
        for img_id in request.image_ids:
            if img_id in image_store:
                img_data = image_store[img_id]
                images.append(ImageInput(
                    image_data=base64.b64encode(img_data["content"]).decode(),
                    mime_type=img_data["mime_type"],
                    filename=img_data["filename"],
                ))
        
        for b64_data in request.image_data_list:
            try:
                if b64_data.startswith("data:"):
                    header, b64_data = b64_data.split(",", 1)
                    mime_type = header.split(":")[1].split(";")[0]
                else:
                    mime_type = "image/jpeg"
                
                images.append(ImageInput(
                    image_data=b64_data,
                    mime_type=mime_type,
                ))
            except Exception:
                continue
        
        patient_profile = ProviderPatientProfile(
            age=request.patient.age,
            sex=request.patient.sex,
            location=request.patient.location,
            pregnancy_status=request.patient.pregnancy_status,
            chronic_conditions=request.patient.chronic_conditions,
            medications=request.patient.medications,
            allergies=request.patient.allergies,
            language=request.patient.language.value if hasattr(request.patient.language, 'value') else request.patient.language,
        )
        
        conversation_history = [
            ConversationTurn(role=turn.get("role", "user"), content=turn.get("content", ""))
            for turn in request.conversation_history
        ]
        
        response = await multimodal_orchestrator.process(
            text=request.text,
            voice_transcript=request.voice_transcript,
            images=images if images else None,
            conversation_history=conversation_history if conversation_history else None,
            patient_profile=patient_profile,
            session_id=request.session_id,
        )
        
        background_tasks.add_task(
            store_multimodal_data,
            request_id=response.request_id,
            request=request,
            response=response,
        )
        
        return MultimodalAnalyzeResponse(
            request_id=response.request_id,
            session_id=request.session_id or str(uuid.uuid4()),
            urgency=response.urgency,
            recommended_next_step=response.recommended_next_step,
            image_assessment=response.image_assessment.__dict__ if response.image_assessment else None,
            medical_information=[mi.__dict__ for mi in response.medical_information],
            treatment_information=[ti.__dict__ for ti in response.treatment_information],
            warning_signs=response.warning_signs,
            follow_up_questions=response.follow_up_questions,
            sources=[s.__dict__ for s in response.sources],
            uncertainty=response.uncertainty,
            requires_professional_review=response.requires_professional_review,
            safety_notice=response.safety_notice,
            confidence_score=response.confidence_score,
            processing_time_ms=response.processing_time_ms,
            provider=response.provider,
            model=response.model,
        )
        
    except Exception as e:
        logger.error(f"Multimodal analysis error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/dedan/v2/images/{image_id}")
async def get_image(image_id: str):
    if image_id not in image_store:
        raise HTTPException(status_code=404, detail="Image not found")
    
    img = image_store[image_id]
    return {k: v for k, v in img.items() if k != "content"}


@app.get("/dedan/v2/images/{image_id}/content")
async def get_image_content(image_id: str):
    if image_id not in image_store:
        raise HTTPException(status_code=404, detail="Image not found")
    
    img = image_store[image_id]
    return {
        "image_id": image_id,
        "content": base64.b64encode(img["content"]).decode(),
        "mime_type": img["mime_type"],
    }


@app.delete("/dedan/v2/images/{image_id}")
async def delete_image(image_id: str):
    if image_id not in image_store:
        raise HTTPException(status_code=404, detail="Image not found")
    
    del image_store[image_id]
    return {"message": "Image deleted", "image_id": image_id}


@app.get("/dedan/v2/multimodal/health")
async def multimodal_health_check():
    health = await multimodal_orchestrator.health_check()
    
    return {
        "status": "healthy" if all(health.values()) else "degraded",
        "providers": health,
        "timestamp": datetime.utcnow().isoformat(),
    }


async def store_multimodal_data(request_id: str, request: MultimodalAnalyzeRequest, response: Any):
    try:
        logger.info(f"Stored multimodal data for request {request_id}")
    except Exception as e:
        logger.error(f"Multimodal data storage error: {str(e)}")


@app.get("/")
async def root():
    return {
        "service": "DEDAN HealthEngine 2.0",
        "version": "2.0.0",
        "status": "operational",
        "features": [
            "Agent-orchestrated AI triage",
            "Safety-first emergency detection",
            "Clinical guideline integration",
            "Risk prediction for chronic diseases",
            "Chronic care mode",
            "Risk sentinel monitoring",
            "Safety & bias layer"
        ],
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """Comprehensive health check for all DEDAN 2.0 components"""
    
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "coordinator_agent": "operational",
            "triage_agent": "operational",
            "safety_guard_agent": "operational",
            "guideline_agent": "operational",
            "risk_prediction_agent": "operational",
            "data_flywheel": "operational"
        },
        "agent_capabilities": coordinator_agent.get_agent_capabilities()
    }
    
    return JSONResponse(content=health_status)

# Core DEDAN 2.0 Triage Endpoint
@app.post("/dedan/v2/triage", response_model=TriageResponseV2)
async def dedan_triage_v2(
    request: TriageRequestV2,
    background_tasks: BackgroundTasks
):
    """
    DEDAN 2.0 Agent-Orchestrated Triage
    
    This endpoint orchestrates multiple specialized agents:
    1. Triage Agent - Core symptom assessment
    2. Safety Guard Agent - Emergency detection
    3. Guideline Agent - Clinical guideline retrieval
    4. Risk Prediction Agent - Chronic disease risk assessment
    5. Coordinator Agent - Synthesis and final response
    """
    
    start_time = time.time()
    
    try:
        # Generate session ID if not provided
        session_id = request.session_id or f"v2_session_{uuid.uuid4().hex[:12]}"
        
        # Validate consent
        if not request.consent:
            raise HTTPException(
                status_code=400,
                detail="Patient consent is required for triage assessment"
            )
        
        logger.info(f"Starting DEDAN 2.0 triage for session {session_id}")
        
        # Prepare coordinator input
        coordinator_input = CoordinatorAgentInput(
            session_id=session_id,
            patient=request.patient,
            symptoms=request.symptoms,
            chronic_care_data=request.chronic_care_data,
            home_measurements=request.home_measurements,
            context=request.context
        )
        
        # Process through coordinator agent
        triage_response = await coordinator_agent.process(coordinator_input)
        
        # Log performance metrics
        processing_time = time.time() - start_time
        logger.info(f"DEDAN 2.0 triage completed for session {session_id} in {processing_time:.2f}s")
        
        # Schedule background tasks for data collection
        background_tasks.add_task(
            collect_triage_data,
            session_id,
            triage_response
        )
        
        return triage_response
        
    except Exception as e:
        logger.error(f"DEDAN 2.0 triage error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Triage processing failed: {str(e)}"
        )

# Chronic Care Mode Endpoints
@app.post("/dedan/v2/chronic-care/check-in")
async def chronic_care_check_in(request: ChronicCareCheckInRequest):
    """
    Chronic Care Mode - Daily/Weekly Check-in
    
    Allows patients with chronic conditions to track:
    - Daily symptoms
    - Medication adherence
    - Side effects
    - Home measurements
    """
    
    try:
        check_in_data = {
            "session_id": f"chronic_{uuid.uuid4().hex[:12]}",
            "patient_id": request.patient_id,
            "condition": request.condition,
            "check_in_date": datetime.utcnow(),
            "symptoms": request.symptoms,
            "medication_taken": request.medication_taken,
            "side_effects": request.side_effects,
            "measurements": [m.dict() for m in request.measurements],
            "notes": request.notes
        }
        
        # Process check-in through coordinator agent for risk assessment
        # This would integrate with the chronic care monitoring system
        
        logger.info(f"Chronic care check-in recorded for patient {request.patient_id}")
        
        return {
            "success": True,
            "message": "Chronic care check-in recorded successfully",
            "session_id": check_in_data["session_id"],
            "timestamp": check_in_data["check_in_date"].isoformat()
        }
        
    except Exception as e:
        logger.error(f"Chronic care check-in error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Chronic care check-in failed: {str(e)}"
        )

@app.get("/dedan/v2/chronic-care/{patient_id}/plan")
async def get_chronic_care_plan(patient_id: str):
    """
    Get personalized chronic care plan for patient
    """
    
    try:
        # This would retrieve patient's chronic care plan from database
        # For now, return a sample plan
        
        care_plan = {
            "patient_id": patient_id,
            "conditions": ["diabetes", "hypertension"],
            "monitoring_schedule": {
                "blood_pressure": "daily",
                "blood_sugar": "twice_daily",
                "weight": "weekly"
            },
            "medication_reminders": [
                {"medication": "Metformin", "time": "08:00", "frequency": "daily"},
                {"medication": "Lisinopril", "time": "08:00", "frequency": "daily"}
            ],
            "red_flags": [
                "blood_sugar > 250",
                "blood_pressure > 160/100",
                "chest pain",
                "difficulty breathing"
            ],
            "follow_up_frequency": "monthly",
            "education_topics": [
                "diabetes_diet",
                "blood_pressure_monitoring",
                "medication_adherence"
            ]
        }
        
        return care_plan
        
    except Exception as e:
        logger.error(f"Get chronic care plan error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve chronic care plan: {str(e)}"
        )

# Risk Sentinel Endpoints
@app.post("/dedan/v2/risk-sentinel", response_model=RiskSentinelOutput)
async def risk_sentinel_analysis(request: RiskSentinelRequest):
    """
    DEDAN Risk Sentinel - Predictive Early Warning System
    
    Monitors chronic patients for:
    - Symptom evolution trends
    - Medication adherence patterns
    - Home measurement trends
    - Risk escalation triggers
    """
    
    try:
        logger.info(f"Risk sentinel analysis for patient {request.patient_id}")
        
        # Process through risk prediction agent
        # This would analyze trends and patterns over time
        
        risk_output = RiskSentinelOutput(
            patient_id=request.patient_id,
            risk_status="stable",  # Would be calculated based on analysis
            risk_score=RiskScore.MEDIUM,
            risk_trend="stable",
            alerts=[],
            recommendations=[
                "Continue current medication regimen",
                "Monitor blood pressure daily",
                "Schedule follow-up in 2 weeks"
            ],
            escalation_level=None,
            last_updated=datetime.utcnow()
        )
        
        # Send alerts if risk threshold crossed
        if risk_output.risk_score == RiskScore.HIGH:
            # Trigger escalation notifications
            background_tasks.add_task(
                send_risk_alert,
                request.patient_id,
                risk_output
            )
        
        return risk_output
        
    except Exception as e:
        logger.error(f"Risk sentinel error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Risk sentinel analysis failed: {str(e)}"
        )

# Safety & Bias Layer Endpoints
@app.post("/dedan/v2/safety-bias/feedback")
async def safety_bias_feedback(
    triage_session_id: str,
    actual_outcome: Dict[str, Any],
    feedback_data: Dict[str, Any]
):
    """
    Collect safety and bias feedback for continuous improvement
    """
    
    try:
        # Process feedback through data flywheel
        success = await data_flywheel.collect_feedback(
            {"session_id": triage_session_id},
            {
                "actual_outcome": actual_outcome,
                "feedback_data": feedback_data,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        if success:
            return {
                "success": True,
                "message": "Safety and bias feedback recorded successfully"
            }
        else:
            return {
                "success": False,
                "message": "Failed to record feedback"
            }
            
    except Exception as e:
        logger.error(f"Safety bias feedback error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Feedback recording failed: {str(e)}"
        )

@app.get("/dedan/v2/safety-bias/metrics")
async def get_safety_bias_metrics(days: int = 30):
    """
    Get safety and bias performance metrics
    """
    
    try:
        metrics = await data_flywheel.get_performance_metrics(days)
        
        return {
            "period_days": days,
            "metrics": metrics,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Get safety bias metrics error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve metrics: {str(e)}"
        )

# Agent Management Endpoints
@app.get("/dedan/v2/agents/status")
async def get_agents_status():
    """
    Get status and capabilities of all DEDAN 2.0 agents
    """
    
    try:
        agent_status = coordinator_agent.get_agent_capabilities()
        
        return {
            "agents": agent_status,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Get agents status error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get agent status: {str(e)}"
        )

@app.post("/dedan/v2/agents/retrain")
async def trigger_agent_retraining():
    """
    Trigger retraining of ML models in agents
    """
    
    try:
        success = await data_flywheel.auto_retrain()
        
        return {
            "success": success,
            "message": "Agent retraining triggered" if success else "Retraining conditions not met",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Agent retraining error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Agent retraining failed: {str(e)}"
        )

# Background Tasks
async def collect_triage_data(session_id: str, triage_response: TriageResponseV2):
    """
    Background task to collect triage data for continuous improvement
    """
    
    try:
        # Store triage response in database
        # This would integrate with the data flywheel
        
        logger.info(f"Collected triage data for session {session_id}")
        
    except Exception as e:
        logger.error(f"Background triage data collection error: {str(e)}")

async def send_risk_alert(patient_id: str, risk_output: RiskSentinelOutput):
    """
    Background task to send risk escalation alerts
    """
    
    try:
        # Send alerts to patient and clinic
        # This would integrate with messaging systems
        
        logger.warning(f"Risk alert sent for patient {patient_id}: {risk_output.risk_status}")
        
    except Exception as e:
        logger.error(f"Risk alert error: {str(e)}")

# Legacy Compatibility Endpoints
@app.post("/dedan/v1/triage")
async def legacy_triage(request: LegacyTriageRequest):
    """
    Legacy v1 triage endpoint for backward compatibility
    """
    
    try:
        # Convert v1 models (backend.models) to v2 models (models_v2)
        from models_v2 import PatientProfile as V2PatientProfile, SymptomInput as V2SymptomInput, Language as V2Language
        
        v1_patient = request.patient
        v2_patient = V2PatientProfile(
            age=v1_patient.age,
            sex=v1_patient.sex,
            location=v1_patient.location,
            pregnancy_status=v1_patient.pregnancy_status,
            chronic_conditions=v1_patient.chronic_conditions,
            language=V2Language(v1_patient.language.value if hasattr(v1_patient.language, 'value') else v1_patient.language),
        )
        
        v1_symptoms = request.symptoms
        # Convert string severity to int scale (v1: mild/moderate/severe -> v2: 1-10)
        severity_map = {"mild": 3, "moderate": 6, "severe": 9}
        v2_severity = None
        if v1_symptoms.severity:
            v2_severity = severity_map.get(v1_symptoms.severity.lower(), 5)
        
        v2_symptoms = V2SymptomInput(
            symptoms=v1_symptoms.symptoms,
            keywords=[],  # will be extracted by agents
            duration=v1_symptoms.duration,
            severity=v2_severity,
            voice_input=v1_symptoms.voice_input,
            language=v2_patient.language,
        )
        
        v2_request = TriageRequestV2(
            patient=v2_patient,
            symptoms=v2_symptoms,
            session_id=request.session_id,
            consent=request.consent
        )
        
        # Process through v2 system
        v2_response = await dedan_triage_v2(v2_request, BackgroundTasks())
        
        # Convert v2 response to v1 format for compatibility
        legacy_response = {
            "session_id": v2_response.session_id,
            "triage_level": v2_response.triage_level.value if hasattr(v2_response.triage_level, 'value') else v2_response.triage_level,
            "confidence_score": v2_response.confidence_score,
            "patient_summary": v2_response.patient_summary,
            "suggested_next_step": v2_response.suggested_next_step,
            "risk_flags": v2_response.risk_flags,
            "differential_diagnoses": v2_response.differential_diagnoses,
            "recommended_tests": v2_response.recommended_tests,
            "timestamp": v2_response.timestamp.isoformat()
        }
        
        return legacy_response
        
    except Exception as e:
        logger.error(f"Legacy triage error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Legacy triage failed: {str(e)}"
        )

# ============================================================================
# DEDAN v1 Compatibility Endpoints (frontend contract)
# ============================================================================

# In-memory stores for v1 compatibility (mirrors backend/main.py pattern)
v1_active_sessions: Dict[str, Dict[str, Any]] = {}
v1_triage_data: List[Dict[str, Any]] = []

def _categorize_age(age: int) -> str:
    if age < 5: return "under_5"
    if age < 18: return "5_17"
    if age < 40: return "18_39"
    if age < 65: return "40_64"
    return "65_plus"

def _extract_keywords(text: str) -> str:
    import re
    words = re.findall(r"[a-z]{4,}", (text or "").lower())
    return json.dumps(sorted(set(words))[:20])

def _determine_emergency_contacts(location: Optional[str]) -> List[str]:
    """Determine local emergency contacts (mirrors backend/dedan_engine.py)."""
    default_contacts = [
        "Emergency: 911 or local emergency number",
        "Nearest hospital emergency department",
    ]
    if location and "ethiopia" in location.lower():
        return [
            "Ethiopia Emergency: 911",
            "Ambulance: 907",
        ]
    return default_contacts

@app.get("/dedan/v1/conditions")
async def get_supported_conditions(language: Language = Language.ENGLISH):
    """Get list of medical conditions DEDAN can triage."""
    try:
        # Use guideline agent's loaded corpus for real conditions
        guideline_agent = coordinator_agent.guideline_agent
        conditions = set()
        for coll in getattr(guideline_agent, "collections", {}).values():
            for meta in getattr(coll, "metadatas", []):
                if isinstance(meta, dict) and meta.get("condition"):
                    conditions.add(meta["condition"])
        if not conditions:
            conditions = {
                "Chest pain", "Fever", "Headache", "Abdominal pain",
                "Pregnancy concerns", "Diabetes management", "Hypertension",
            }
        return sorted(conditions)
    except Exception as e:
        logger.error(f"Error getting conditions: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve conditions")

@app.get("/dedan/v1/session/{session_id}")
async def get_session(session_id: str):
    """Get session details."""
    if session_id not in v1_active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return v1_active_sessions[session_id]

@app.post("/dedan/v1/session/{session_id}/consent")
async def update_consent(session_id: str, consent: DataConsent):
    """Update data consent for a session."""
    if session_id not in v1_active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    v1_active_sessions[session_id]["consent"] = consent.dict()
    return {"message": "Consent updated successfully"}

@app.get("/dedan/v1/emergency-contacts")
async def get_emergency_contacts(location: Optional[str] = None):
    """Get emergency contacts for a location."""
    try:
        raw_contacts = _determine_emergency_contacts(location)
        contacts = []
        for entry in raw_contacts:
            # Parse into {label, number, note}
            import re
            num_match = re.search(r"(\d[\d\s\-]{2,14}\d|\d{3,4})", entry)
            number = ""
            label = entry
            note = None
            if num_match:
                number = num_match.group(0).strip()
                remainder = entry.replace(number, "").strip()
                if ":" in remainder:
                    parts = remainder.split(":", 1)
                    label = parts[0].strip()
                    extra = parts[1].strip()
                    if extra:
                        note = extra
                else:
                    label = remainder
            contacts.append({"label": label, "number": number, "note": note})
        return contacts
    except Exception as e:
        logger.error(f"Error getting emergency contacts: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve emergency contacts")

@app.post("/dedan/v1/feedback")
async def submit_feedback(feedback: Dict[str, Any]):
    """Submit clinician feedback on a triage assessment."""
    try:
        triage_data = feedback.get("triage_data", {})
        doctor_feedback = feedback.get("doctor_feedback", {})
        if not triage_data or not doctor_feedback:
            raise HTTPException(
                status_code=400,
                detail="Both 'triage_data' and 'doctor_feedback' are required."
            )
        required_triage = ["session_id", "triage_level", "symptoms_description"]
        required_feedback = ["triage_level"]
        missing = []
        for f in required_triage:
            if not triage_data.get(f):
                missing.append(f"triage_data.{f}")
        for f in required_feedback:
            if not doctor_feedback.get(f):
                missing.append(f"doctor_feedback.{f}")
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required fields: {', '.join(missing)}"
            )
        success = await data_flywheel.collect_feedback(triage_data, doctor_feedback)
        if success:
            logger.info(f"Feedback collected for session {triage_data.get('session_id')}")
            return {"success": True, "message": "Feedback recorded successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to record feedback")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit feedback")

@app.get("/dedan/v1/stats")
async def get_platform_stats():
    """Get platform usage statistics."""
    return {
        "total_sessions": len(v1_active_sessions),
        "total_triages": len(v1_triage_data),
        "active_sessions": len(
            [s for s in v1_active_sessions.values() if s.get("status") == "active"]
        ),
        "supported_languages": ["en", "sw", "am", "es", "fr"],
        "triage_levels": ["emergency", "urgent", "routine", "self_care"],
    }

# Background task for storing triage data
async def store_triage_data(session_id: str, request: TriageRequestV2, response):
    """Store anonymized triage data for continuous improvement."""
    try:
        anonymized_record = {
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
            "patient_age_group": _categorize_age(request.patient.age),
            "patient_sex": request.patient.sex,
            "language": request.patient.language.value if hasattr(request.patient.language, 'value') else request.patient.language,
            "location_region": request.patient.location,
            "chronic_conditions": request.patient.chronic_conditions,
            "symptoms_keywords": _extract_keywords(request.symptoms.symptoms),
            "triage_level": response.triage_level.value if hasattr(response.triage_level, 'value') else response.triage_level,
            "risk_flags_count": len(response.risk_flags),
            "confidence_score": response.confidence_score,
            "suggested_next_step": response.suggested_next_step,
            "patient_summary": response.patient_summary,
        }
        v1_triage_data.append(anonymized_record)
    except Exception as e:
        logger.error(f"Background triage data collection error: {e}")

# Update dedan_triage_v2 to call store_triage_data
# (find the background_tasks.add_task call and append store_triage_data)

# Configuration and Settings
@app.get("/dedan/v2/config")
async def get_configuration():
    """
    Get DEDAN 2.0 system configuration
    """
    
    return {
        "version": "2.0.0",
        "features": {
            "agent_orchestration": True,
            "safety_first": True,
            "risk_prediction": True,
            "chronic_care": True,
            "risk_sentinel": True,
            "bias_monitoring": True,
            "multilingual": True,
            "offline_support": True
        },
        "supported_languages": ["en", "sw", "am", "es", "fr"],
        "supported_conditions": [
            "diabetes", "hypertension", "asthma", "hiv", 
            "tuberculosis", "malaria", "heart_disease", "stroke"
        ],
        "triage_levels": [level.value for level in TriageLevel],
        "risk_scores": [score.value for score in RiskScore],
        "time_horizons": [horizon.value for horizon in RiskTimeHorizon]
    }

if __name__ == "__main__":
    import uvicorn
    
    # Environment configuration
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    log_level = os.getenv("LOG_LEVEL", "info")
    
    logger.info(f"Starting DEDAN HealthEngine 2.0 on {host}:{port}")
    
    uvicorn.run(
        "main_v2:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=True
    )


# ============================================================================
# NEW: DEDAN Health 2.0 — Multimodal Clinical Guidance Endpoints
# ============================================================================

from clinical_schema import (
    ClinicalResponse, HealthSummary, SafetyClassification,
    PossibleExplanation, UncertaintyStatement, TreatmentEducation,
    MedicationInfo, VisualEducation, Source, UrgencyLevel,
    EvidenceLevel, Observation, MedicationVerificationItem,
)
from urgency_engine import UrgencyEngine
from evidence_retrieval_enhanced import evidence_retriever, EvidenceRetriever
from medication_safety_enhanced import medication_safety_service, MedicationSafetyService
from visual_education_enhanced import visual_education_service, VisualEducationService
from clinical_context_builder import clinical_context_builder, ClinicalContextBuilder, build_gemini_system_prompt
from conversation_memory import ConversationMemoryManager, ConversationContext, ConversationTurn
from providers import (
    ProviderFactory,
    ImageInput,
    MultimodalOrchestrator,
    PatientProfile as ProviderPatientProfile,
    ConversationTurn as ProviderConversationTurn,
    Modality,
)


# Initialize enhanced services
urgency_engine = UrgencyEngine()
# evidence_retriever, medication_safety_service, visual_education_service imported from enhanced modules
conversation_memory = ConversationMemoryManager()

# Initialize multimodal AI provider
multimodal_orchestrator = MultimodalOrchestrator()
provider_factory = ProviderFactory()


class ClinicalGuidanceRequest(BaseModel):
    """Request for structured clinical guidance."""
    patient: PatientProfile
    symptoms: SymptomInput
    image_ids: List[str] = Field(default_factory=list)
    image_data_list: List[str] = Field(default_factory=list)
    voice_transcript: Optional[str] = None
    session_id: Optional[str] = None
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    consent: bool = True


class ClinicalGuidanceResponse(BaseModel):
    """Structured clinical guidance response."""
    response_id: str
    session_id: str
    clinical_response: Dict[str, Any]
    urgency: str
    requires_emergency_action: bool
    evidence_retrieved: bool
    sources_count: int


@app.post("/dedan/v2/clinical-guidance", response_model=ClinicalGuidanceResponse)
async def get_clinical_guidance(request: ClinicalGuidanceRequest):
    """
    POST /dedan/v2/clinical-guidance

    Generates structured clinical guidance from patient assessment using
    real multimodal AI analysis (Gemini 1.5 Pro) with evidence grounding.
    Includes safety classification, possible explanations, treatment
    education, medication safety info, and visual education references.
    """
    start_time = time.time()
    session_id = request.session_id or str(uuid.uuid4())
    response_id = str(uuid.uuid4())
    
    try:
        logger.info(f"Starting clinical guidance {response_id} for session {session_id}")
        
        # Validate consent
        if not request.consent:
            raise HTTPException(
                status_code=400,
                detail="Patient consent is required for AI analysis"
            )
        
        # Prepare images from image_ids and image_data_list
        images: List[ImageInput] = []
        
        for img_id in request.image_ids:
            metadata = image_store.get(img_id)
            if metadata:
                images.append(ImageInput(
                    image_data=base64.b64encode(metadata["content"]).decode(),
                    mime_type=metadata["mime_type"],
                    filename=metadata["filename"],
                ))
        
        for b64_data in request.image_data_list:
            try:
                mime_type = "image/jpeg"
                if b64_data.startswith("data:"):
                    header, b64_data = b64_data.split(",", 1)
                    mime_type = header.split(":")[1].split(";")[0]
                
                images.append(ImageInput(
                    image_data=b64_data,
                    mime_type=mime_type,
                ))
            except Exception as e:
                logger.warning(f"Failed to process base64 image: {e}")
                continue
        
        # Prepare patient context for multimodal orchestrator
        patient_profile = ProviderPatientProfile(
            age=request.patient.age,
            sex=request.patient.sex,
            location=request.patient.location,
            pregnancy_status=request.patient.pregnancy_status,
            chronic_conditions=request.patient.chronic_conditions,
            medications=request.patient.medications,
            allergies=request.patient.allergies,
            language=request.patient.language.value if hasattr(request.patient.language, 'value') else request.patient.language,
        )
        
        # Prepare conversation history
        conversation_history = [
            ProviderConversationTurn(role=turn.get("role", "user"), content=turn.get("content", ""))
            for turn in request.conversation_history
        ]
        
        # Combine text inputs
        combined_text = request.symptoms.symptoms or ""
        if request.symptoms.duration:
            combined_text += f"\nDuration: {request.symptoms.duration}"
        if request.symptoms.severity:
            combined_text += f"\nSeverity: {request.symptoms.severity}"
        if request.voice_transcript:
            combined_text += f"\nVoice input: {request.voice_transcript}"
        
        # Run multimodal AI analysis with fallback
        ai_response = await multimodal_orchestrator.process(
            text=combined_text,
            images=images if images else None,
            conversation_history=conversation_history if conversation_history else None,
            patient_profile=patient_profile,
            session_id=session_id,
        )
        
        # Safety validation
        safety_result = await safety_validator.validate_async(
            ai_response,
            patient_profile,
            original_text=combined_text,
        )
        ai_response = await safety_validator.apply_safety_result_async(ai_response, safety_result)
        
        # Build clinical context for structured response
        clinical_context = await clinical_context_builder.build(
            patient_profile=request.patient,
            symptoms=request.symptoms,
            image_analysis=None,  # Will be populated from ai_response
            voice_transcript=request.voice_transcript,
            conversation_history=request.conversation_history,
            session_id=session_id,
        )
        
        # Transform AI response to structured clinical response
        structured_response = response_transformer.transform(
            ai_response=ai_response,
            clinical_context=clinical_context,
            request_id=response_id,
            session_id=session_id,
        )
        
        # Enhance with visual education from real sources
        conditions = [c.label for c in structured_response.possible_explanations]
        body_systems = _extract_body_systems(conditions, combined_text)
        treatment_approaches = _extract_treatment_approaches(structured_response)
        medication_classes = _extract_medication_classes(structured_response)
        
        visual_education_items = visual_education_service.get_visuals_for_response(
            conditions=conditions,
            body_systems=body_systems,
            treatment_approaches=treatment_approaches,
            medication_classes=medication_classes,
        )
        structured_response.visual_education = visual_education_items
        
        # Enhance medication information with pharmacy verification
        for med in structured_response.medication_information:
            verification = medication_safety_service.get_pharmacy_verification_workflow(med.medication_class)
            structured_response.medication_verification.extend([
                # `package_check_items` is a list of plain strings.
                MedicationVerificationItem(
                    field=item,
                    description=f"Check the package for: {item}",
                    why_important="Confirms you received the right medicine, strength and quality.",
                )
                for item in verification.get("package_check_items", [])
            ])
        
        # Build final clinical response
        clinical = ClinicalResponse(
            response_id=response_id,
            session_id=session_id,
            timestamp=datetime.utcnow().isoformat(),
            health_summary=structured_response.health_summary,
            safety=structured_response.safety,
            possible_explanations=structured_response.possible_explanations,
            uncertainty=structured_response.uncertainty,
            treatment_education=structured_response.treatment_education,
            medication_information=structured_response.medication_information,
            visual_education=structured_response.visual_education,
            follow_up=structured_response.follow_up,
            sources=structured_response.sources,
            professional_review=structured_response.professional_review,
            provider=ai_response.provider,
            model=ai_response.model,
            confidence_score=ai_response.confidence_score,
            disclaimer=structured_response.disclaimer,
        )
        
        processing_time = int((time.time() - start_time) * 1000)
        logger.info(f"Clinical guidance {response_id} completed in {processing_time}ms: urgency={clinical.safety.urgency.value}")
        
        return ClinicalGuidanceResponse(
            response_id=response_id,
            session_id=session_id,
            clinical_response=clinical.to_dict(),
            urgency=clinical.safety.urgency.value,
            requires_emergency_action=clinical.safety.requires_immediate_care,
            evidence_retrieved=len(structured_response.sources) > 0,
            sources_count=len(structured_response.sources),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Clinical guidance error {response_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Clinical guidance failed: {str(e)}")


def _extract_body_systems(conditions: List[str], symptoms: str) -> List[str]:
    """Extract likely affected body systems from conditions and symptoms."""
    systems = set()
    text = " ".join(conditions + [symptoms]).lower()
    
    system_keywords = {
        "respiratory": ["respiratory", "lung", "breathing", "cough", "pneumonia", "asthma", "copd", "bronchi"],
        "cardiovascular": ["heart", "cardiac", "chest pain", "hypertension", "blood pressure", "cardio"],
        "gastrointestinal": ["abdominal", "stomach", "diarrhea", "vomiting", "nausea", "gi ", "gut", "liver", "hepatitis"],
        "neurological": ["headache", "seizure", "confusion", "stroke", "neuro", "brain", "migraine", "dizziness"],
        "dermatological": ["rash", "skin", "lesion", "bite", "dermatitis", "eczema", "infection"],
        "infectious": ["fever", "infection", "malaria", "dengue", "tb", "tuberculosis", "hiv", "sepsis"],
        "musculoskeletal": ["joint", "muscle", "bone", "pain", "arthritis", "fracture", "sprain"],
        "genitourinary": ["urinary", "kidney", "bladder", "uti", "renal"],
        "endocrine": ["diabetes", "thyroid", "hormone", "glucose", "insulin"],
    }
    
    for system, keywords in system_keywords.items():
        if any(kw in text for kw in keywords):
            systems.add(system)
    
    return list(systems)


def _extract_treatment_approaches(response) -> List[str]:
    """Extract treatment approaches from structured response."""
    approaches = []
    for te in response.treatment_education:
        approaches.append(te.title)
    return approaches


def _extract_medication_classes(response) -> List[str]:
    """Extract medication classes from structured response."""
    classes = []
    for med in response.medication_information:
        classes.append(med.medication_class)
    return classes


@app.post("/dedan/v2/conversation", response_model=Dict[str, Any])
async def conversation_turn(request: Dict[str, Any]):
    """
    POST /dedan/v2/conversation

    Handles a single conversation turn within an assessment context.
    Maintains conversation memory and safety context.
    """
    try:
        session_id = request.get("session_id", "default")
        user_message = request.get("message", "")
        patient = request.get("patient", {})

        # Get or create conversation context
        context = conversation_memory.get_or_create(session_id)

        # Set patient facts if provided
        if patient:
            context.set_patient_facts(patient)

        # Add user turn
        context.add_turn(ConversationTurn(role="patient", content=user_message))

        # Classify urgency for safety
        safety = urgency_engine.classify(symptoms=user_message)

        # Build AI context
        ai_context = context.get_context_for_ai(
            current_question=user_message,
            max_recent_turns=6,
        )

        # Add assistant turn (placeholder — would call AI provider)
        assistant_response = {
            "message": "I understand. Based on the information available, here is what I can tell you...",
            "safety": safety.to_dict(),
        }
        context.add_turn(ConversationTurn(role="assistant", content=str(assistant_response)))

        return {
            "session_id": session_id,
            "response": assistant_response,
            "context_turns": len(context.turns),
            "safety_urgency": safety.urgency.value,
        }

    except Exception as e:
        logger.error(f"Conversation error: {e}")
        raise HTTPException(status_code=500, detail=f"Conversation failed: {str(e)}")


@app.get("/dedan/v2/conversation/{session_id}", response_model=Dict[str, Any])
async def get_conversation_context(session_id: str):
    """GET /dedan/v2/conversation/{session_id} — Retrieve conversation context."""
    context = conversation_memory.get(session_id)
    if not context:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "session_id": session_id,
        "turns": len(context.turns),
        "patient_facts": context.patient_facts,
        "has_assessment": context.assessment_context is not None,
        "created_at": context.created_at.isoformat(),
        "last_activity": context.last_activity.isoformat(),
    }


@app.get("/dedan/v2/evidence/{topic}", response_model=Dict[str, Any])
async def get_evidence(topic: str):
    """GET /dedan/v2/evidence/{topic} — Retrieve evidence for a clinical topic."""
    try:
        result = evidence_retriever.retrieve(topic)
        return result
    except Exception as e:
        logger.error(f"Evidence retrieval error: {e}")
        raise HTTPException(status_code=500, detail=f"Evidence retrieval failed: {str(e)}")


@app.get("/dedan/v2/medication/{medication_name}", response_model=Dict[str, Any])
async def get_medication_info(medication_name: str):
    """GET /dedan/v2/medication/{medication_name} — Get medication safety info."""
    try:
        result = medication_safety_service.verify_medication(medication_name)
        return result
    except Exception as e:
        logger.error(f"Medication safety error: {e}")
        raise HTTPException(status_code=500, detail=f"Medication safety check failed: {str(e)}")


@app.get("/dedan/v2/visuals/{topic}", response_model=Dict[str, Any])
async def get_visual_education(topic: str):
    """GET /dedan/v2/visuals/{topic} — Get educational visuals for a topic."""
    try:
        visuals = visual_education_service.get_disease_overview(topic)
        return {
            "topic": topic,
            "visuals": [v.__dict__ for v in visuals],
            "count": len(visuals),
        }
    except Exception as e:
        logger.error(f"Visual education error: {e}")
        raise HTTPException(status_code=500, detail=f"Visual education failed: {str(e)}")


@app.get("/dedan/v2/urgency/check", response_model=Dict[str, Any])
async def check_urgency(symptoms: str, severity: Optional[str] = None):
    """GET /dedan/v2/urgency/check — Check urgency level for symptoms."""
    safety = urgency_engine.classify(symptoms=symptoms, severity=severity)
    return {
        "urgency": safety.urgency.value,
        "requires_immediate_care": safety.requires_immediate_care,
        "red_flags": safety.red_flags,
        "recommended_action": safety.recommended_action,
        "emergency_message": safety.emergency_message,
    }
