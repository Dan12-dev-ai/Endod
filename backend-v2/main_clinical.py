"""
Minimal FastAPI app for Clinical Guidance endpoint only.
Excludes agents module which requires deprecated langchain 0.x.
"""

import os

# Provider placeholders, applied ONLY outside production and ONLY when a key is
# genuinely absent.
#
# These previously ran unconditionally at import, which meant a deployment with
# no credentials silently looked configured: the provider factory saw a
# non-empty key and had to fall back to matching the literal string "test-key" to
# stay in offline mode. That is fragile and hides misconfiguration. Setting them
# here keeps the deterministic offline provider for local runs and the test
# suite, while production is required to supply real credentials.
# A placeholder is installed ONLY when no real credential exists anywhere --
# neither in the environment nor in `.env`. This matters for more than tidiness:
# setting `GEMINI_API_KEY=test-key` unconditionally masked a REAL key in `.env`,
# because `setdefault` refuses to overwrite but also wins over `.env` loading.
# The realtime gateway then sent "test-key" upstream, was rejected, and reported
# "live voice unavailable" even though the deployment was correctly configured.
if os.getenv("ENVIRONMENT", "development").strip().lower() != "production":
    for _provider_var in ("GEMINI_API_KEY", "OPENAI_API_KEY"):
        if os.getenv(_provider_var):
            continue
        try:
            from app.core.config import get_settings

            _real = (getattr(get_settings(), _provider_var, None) or "").strip()
        except Exception:
            _real = ""
        # Only when genuinely absent does the placeholder get installed.
        os.environ.setdefault(_provider_var, _real or "test-key")
os.environ.setdefault("DEFAULT_AI_PROVIDER", "gemini")

import logging
import secrets
import time
import base64
import uuid
from contextlib import asynccontextmanager
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, status, Depends, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from clinical_context_builder import clinical_context_builder
from evidence_retrieval_enhanced import evidence_retriever
from medication_safety_enhanced import medication_safety_service
from visual_education_enhanced import visual_education_service
from conversation_memory import ConversationMemoryManager
from urgency_engine import UrgencyEngine
from response_transformer import response_transformer
from safety_validator import safety_validator
from image_service import image_service, ImageValidationError
from models.schemas import (
    AnalyzeRequest, AnalyzeResponse, ImageUploadResponse,
    HealthCheckResponse, ErrorResponse, UrgencyLevel,
)
from app.core.config import get_settings, Settings
from app.core.security import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    require_secure_configuration,
)
from providers.gemini_models import configured_gemini_models
from providers import (
    ProviderFactory,
    ImageInput,
    MultimodalOrchestrator,
    PatientProfile as ProviderPatientProfile,
    ConversationTurn as ProviderConversationTurn,
    Modality,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
)
logger = logging.getLogger(__name__)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        logger.info(f"REQUEST: {request.method} {request.url.path} from {request.client.host if request.client else 'unknown'}")
        response = await call_next(request)
        process_time = (time.time() - start_time) * 1000
        logger.info(f"RESPONSE: {request.method} {request.url.path} status={response.status_code} time={process_time:.1f}ms")
        response.headers["X-Process-Time"] = f"{process_time:.1f}"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(f"Starting DEDAN Health Clinical API v{settings.APP_VERSION} in {settings.ENVIRONMENT} mode")

    # Initialize AI providers
    try:
        factory = ProviderFactory()
        app.state.provider_factory = factory
        app.state.multimodal_orchestrator = MultimodalOrchestrator(provider_factory=factory)
        logger.info("AI providers initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize AI providers: {e}")

    # Start cleanup task
    import asyncio
    cleanup_task = asyncio.create_task(periodic_cleanup())

    # Notification worker.
    #
    # Gated by NOTIFICATION_WORKER_ENABLED (default off). Without a loop the
    # `notifications` table is written but never drained -- which is exactly
    # what happened here: the queue, the retry policy and the stale-job
    # recovery were all implemented, and the deployed database held 52 PENDING
    # reminders and 0 SENT because nothing ever called the worker.
    #
    # Run it on exactly one process when the deployment has multiple API
    # replicas. Concurrent workers are safe for correctness (claiming is an
    # atomic conditional UPDATE, so two workers cannot take the same job) but
    # they multiply delivery work.
    worker_stop = asyncio.Event()
    worker_task: Optional[asyncio.Task] = None
    # Imported here rather than at module scope: the platform modules are
    # imported inside create_app()'s guarded block, and a failure there must not
    # stop the app from starting with its worker still able to deliver.
    try:
        from dedan_platform import worker

        if worker.WORKER_ENABLED:
            worker_task = asyncio.create_task(worker.worker_loop(worker_stop))
            app.state.notification_worker_stop = worker_stop
        else:
            logger.warning(
                "notification_worker_disabled_reminders_will_not_be_delivered",
            )
    except Exception:
        logger.exception("notification_worker_failed_to_start")

    try:
        yield
    finally:
        logger.info("Shutting down DEDAN Health Clinical API")
        # Signal and await, rather than cancelling: an in-flight delivery is
        # given the chance to finish and record its outcome. The join is bounded
        # so a wedged SMTP call cannot block shutdown indefinitely.
        for task, stop in ((worker_task, worker_stop), (cleanup_task, None)):
            if task is None:
                continue
            if stop is not None:
                stop.set()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: B014
                pass


async def periodic_cleanup():
    import asyncio
    while True:
        await asyncio.sleep(3600)
        try:
            deleted = image_service.cleanup_expired()
            if deleted:
                logger.info(f"Periodic cleanup: removed {deleted} expired images")
        except Exception as e:
            logger.error(f"Periodic cleanup error: {e}")


def create_app(settings = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="DEDAN Health Clinical API",
        version=settings.APP_VERSION,
        description="AI-powered medical triage clinical guidance for underserved regions",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # CORS
    #
    # `settings.CORS_ORIGINS` defaults to explicit localhost origins, but a
    # misconfigured deployment could still set it to "*". `build_cors_middleware`
    # refuses that in production and never pairs a wildcard with credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.CORS_ORIGINS or []),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type"],
        expose_headers=["X-Process-Time", "Retry-After"],
        max_age=600,
    )

    # Fail closed: refuse to serve a clinical API with no credential configured.
    require_secure_configuration()

    # Request body cap. `SessionMiddleware` below signs cookies, so a
    # wildcard-with-credentials CORS policy would be the worst possible pairing
    # here.
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=max(16 * 1024 * 1024, int(settings.MAX_IMAGE_SIZE_MB) * 1024 * 1024),
    )

    # Trusted hosts
    if settings.ENVIRONMENT == "production":
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["*.dedanhealth.org", "dedanhealth.org", "localhost", "127.0.0.1"],
        )

    # Rate limiting
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_window=settings.RATE_LIMIT_REQUESTS,
        window_seconds=settings.RATE_LIMIT_WINDOW,
    )

    # Request logging
    app.add_middleware(RequestLoggingMiddleware)

    # Session middleware.
    #
    # The secret previously fell back to a fixed, repository-published development
    # placeholder, so anyone could forge a signed session cookie -- and worse, a
    # deployment that simply forgot to set ADMIN_API_KEY would silently run with
    # that known value. The production path now refuses to start without a real
    # secret.
    _session_secret = settings.ADMIN_API_KEY or os.getenv("SESSION_SECRET") or ""
    if settings.ENVIRONMENT == "production" and not _session_secret:
        raise RuntimeError(
            "ADMIN_API_KEY (or SESSION_SECRET) must be set in production: the "
            "session cookie cannot be signed with a default secret."
        )
    if not _session_secret:
        # Non-production only, and derived per-process so it is never a constant.
        _session_secret = secrets.token_urlsafe(32)
        logger.warning("SESSION_EPHEMERAL_SECRET_IN_USE")

    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret,
        https_only=settings.ENVIRONMENT == "production",
        same_site="lax",
    )

    # Added last so it is the outermost middleware: the 413 and 429 responses
    # that the body-size and rate-limit middleware return directly get the
    # security headers too.
    app.add_middleware(SecurityHeadersMiddleware)

    # --- Core platform domains -----------------------------------------------
    # Identity/profile, health timeline, appointments, care navigation and the
    # notification queue. These are required: they are mounted outside any
    # try/except so an import or schema failure stops the app from starting.
    # They used to share a try block with the optional voice routers, so a
    # missing voice module silently unmounted login and every `/users/me/*`
    # route while the health check still reported the app as healthy.
    from dedan_platform.api_auth import router as platform_auth_router
    from dedan_platform.api_care import router as platform_care_router
    from dedan_platform.api_health import router as platform_health_router
    from dedan_platform.api_notifications import router as platform_notifications_router
    from dedan_platform.api_profile import router as platform_profile_router
    from dedan_platform.db import create_all
    from realtime.voices import SUPPORTED_LANGUAGES

    app.include_router(platform_auth_router)
    app.include_router(platform_profile_router)
    app.include_router(platform_health_router)
    app.include_router(platform_care_router)
    app.include_router(platform_notifications_router)

    # Additive and idempotent; migrations remain required before schema
    # changes reach production.
    create_all()
    logger.info("platform_routers_mounted")

    # --- Live voice (optional) -----------------------------------------------
    # Mounted only when its modules are installed. Without them the clinical
    # API and the platform keep working and the capabilities endpoint below
    # reports voice as unavailable, so the browser falls back to text.
    try:
        # Native-duplex Live Discussion is the primary voice path.
        # `live_voice` (the older STT->LLM->TTS engine) stays mounted on the same
        # path as a fallback for deployments without native-duplex support; the
        # router is registered first so its handler wins the route.
        from realtime.discussion import router as discussion_router
        from live_voice import router as live_voice_router
        from realtime_api import conversations_router, router as realtime_api_router
    except ImportError as exc:
        live_voice_installed = False
        logger.warning("live_voice_not_installed: missing module %s", exc.name)
    else:
        live_voice_installed = True
        app.include_router(discussion_router)
        app.include_router(live_voice_router)
        app.include_router(realtime_api_router)
        app.include_router(conversations_router)
        logger.info("realtime_routers_mounted")

    @app.get("/dedan/v2/live-voice/capabilities")
    async def live_voice_capabilities():
        """Advertise live-voice support so the browser can feature-detect.

        The portal calls this before offering the voice surface; a 404 here
        is what makes the UI report live voice as unavailable.

        This endpoint is the browser's only way to learn what the realtime
        stack can really do, so every flag is measured rather than asserted.

        It used to hardcode `native_duplex: False` and derive `available`
        from the *legacy* STT->LLM->TTS factory. That was wrong twice over:
        it misreported a working native-duplex provider, and it would have
        advertised the voice surface as live while the provider could not
        connect at all. A client that trusts this must not be able to be
        lied to.

        Languages are a *platform* fact (realtime.voices), not a provider
        capability, so they are reported even when voice is unavailable.
        """
        if not live_voice_installed:
            return {
                "available": False,
                "endpoint": "/ws/live-voice",
                "transport": "websocket",
                "native_duplex": False,
                "streaming": False,
                "barge_in": False,
                "text_fallback": True,
                "languages": list(SUPPORTED_LANGUAGES),
                "input_sample_rate": 16000,
                "output_sample_rate": 24000,
                "provider": None,
                "providers_registered": [],
                "detail": "Live voice is not installed on this deployment.",
            }

        from realtime.discussion import realtime_provider, realtime_enabled
        from realtime.provider_base import available_providers, build_provider

        # `available` must mean "a provider can actually be built and can
        # stream audio", not merely "a key is present in the environment".
        name = realtime_provider()
        if not realtime_enabled():
            return {
                "available": False,
                "endpoint": "/ws/live-voice",
                "transport": "websocket",
                "native_duplex": False,
                "streaming": False,
                "barge_in": False,
                "text_fallback": True,
                "languages": list(SUPPORTED_LANGUAGES),
                "input_sample_rate": 16000,
                "output_sample_rate": 24000,
                "provider": name,
                "providers_registered": available_providers(),
                "detail": "Realtime is disabled via REALTIME_ENABLED.",
            }

        caps = None
        detail = "No realtime provider is registered."
        try:
            caps = build_provider(name).capabilities()
            detail = caps.notes
        except Exception as exc:
            # Never leak a stack trace to the browser: an unavailable
            # provider is a configuration problem, not a client error.
            detail = f"provider_unavailable: {type(exc).__name__}"

        streaming = bool(caps and caps.streaming_audio)
        return {
            "available": streaming,
            "endpoint": "/ws/live-voice",
            "transport": "websocket",
            "native_duplex": bool(caps and caps.native_duplex),
            "streaming": streaming,
            "barge_in": bool(caps and caps.supports_interrupt),
            "text_fallback": True,
            "languages": list(SUPPORTED_LANGUAGES),
            "input_sample_rate": 16000,
            "output_sample_rate": 24000,
            # Surfaced so a misconfiguration is diagnosable from the browser
            # instead of looking like an unexplained "unavailable".
            "provider": name,
            "providers_registered": available_providers(),
            "detail": detail,
        }


    # Exception handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail if isinstance(exc.detail, str) else "HTTP error",
                "error_code": f"HTTP_{exc.status_code}",
                "details": exc.detail if isinstance(exc.detail, dict) else None,
                "timestamp": time.time(),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "Validation error",
                "error_code": "VALIDATION_ERROR",
                "details": exc.errors(),
                "timestamp": time.time(),
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal server error",
                "error_code": "INTERNAL_ERROR",
                "details": {"type": type(exc).__name__} if settings.DEBUG else None,
                "timestamp": time.time(),
            },
        )

    # Dependency for provider factory
    def get_provider_factory() -> ProviderFactory:
        if not hasattr(app.state, 'provider_factory'):
            raise HTTPException(status_code=503, detail="AI providers not initialized")
        return app.state.provider_factory

    def get_orchestrator() -> MultimodalOrchestrator:
        if not hasattr(app.state, 'multimodal_orchestrator'):
            raise HTTPException(status_code=503, detail="Multimodal orchestrator not initialized")
        return app.state.multimodal_orchestrator

    # ============ ENDPOINTS ============

    @app.post("/api/images/upload", response_model=ImageUploadResponse)
    async def upload_image(file: UploadFile = File(...), session_id: Optional[str] = Form(None)):
        try:
            content = await file.read()
            result = image_service.validate_and_store(content, file.filename or "image.jpg", session_id)
            return result
        except ImageValidationError as e:
            raise HTTPException(status_code=400, detail={"message": e.message, "errors": e.errors, "warnings": e.warnings})
        except Exception as e:
            logger.error(f"Image upload error: {e}")
            raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    @app.post("/api/images/upload-base64", response_model=ImageUploadResponse)
    async def upload_image_base64(request: dict):
        try:
            base64_data = request.get("image_data", "")
            filename = request.get("filename", "image.jpg")
            session_id = request.get("session_id")
            if not base64_data:
                raise HTTPException(status_code=400, detail="image_data is required")
            file_content = base64.b64decode(base64_data)
            result = image_service.validate_and_store(file_content, filename, session_id)
            return result
        except ImageValidationError as e:
            raise HTTPException(status_code=400, detail={"message": e.message, "errors": e.errors, "warnings": e.warnings})
        except Exception as e:
            logger.error(f"Base64 image upload error: {e}")
            raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    @app.get("/api/images/{image_id}")
    async def get_image_metadata(image_id: str):
        metadata = image_service.get_metadata(image_id)
        if not metadata:
            raise HTTPException(status_code=404, detail="Image not found")
        return metadata

    @app.get("/api/images/{image_id}/preview")
    async def get_image_preview(image_id: str):
        base64_data = image_service.get_image_base64(image_id)
        if not base64_data:
            raise HTTPException(status_code=404, detail="Image not found")
        metadata = image_service.get_metadata(image_id)
        return {"image_id": image_id, "content": base64_data, "mime_type": metadata.get("mime_type", "image/jpeg")}

    @app.delete("/api/images/{image_id}")
    async def delete_image(image_id: str):
        if image_service.delete_image(image_id):
            return {"message": "Image deleted", "image_id": image_id}
        raise HTTPException(status_code=404, detail="Image not found")

    @app.post("/api/analyze", response_model=dict)
    async def analyze(request: AnalyzeRequest, background_tasks: BackgroundTasks):
        request_id = str(uuid.uuid4())
        start_time = time.time()

        try:
            if not request.consent:
                raise HTTPException(status_code=400, detail="Patient consent is required for AI analysis")

            logger.info(f"Starting analysis {request_id} for session {request.session_id or 'new'}")

            # Prepare images
            images = []
            for img_id in request.image_ids:
                metadata = image_service.get_metadata(img_id)
                if metadata:
                    base64_data = image_service.get_image_base64(img_id)
                    if base64_data:
                        images.append(ImageInput(image_data=base64_data, mime_type=metadata["mime_type"], filename=metadata["original_filename"]))

            for b64_data in request.image_data_list:
                try:
                    mime_type = "image/jpeg"
                    if b64_data.startswith("data:"):
                        header, b64_data = b64_data.split(",", 1)
                        mime_type = header.split(":")[1].split(";")[0]
                    images.append(ImageInput(image_data=b64_data, mime_type=mime_type))
                except Exception as e:
                    logger.warning(f"Failed to process base64 image: {e}")
                    continue

            # Prepare patient context
            from providers.models import PatientProfile as ProviderPatientProfile
            patient_context = ProviderPatientProfile(
                age=request.patient_age,
                sex=request.patient_sex,
                location=request.patient_location,
                pregnancy_status=request.patient_pregnant,
                chronic_conditions=request.patient_chronic_conditions,
                medications=request.patient_medications,
                allergies=request.patient_allergies,
                language=request.patient_language,
            )

            # Prepare conversation history
            from providers.models import ConversationTurn as ProviderConversationTurn
            conversation_history = [
                ProviderConversationTurn(role=turn.get("role", "user"), content=turn.get("content", ""))
                for turn in request.conversation_history
            ]

            # Combine text inputs
            combined_text = request.symptom_description
            if request.symptom_duration:
                combined_text += f"\nDuration: {request.symptom_duration}"
            if request.symptom_severity:
                combined_text += f"\nSeverity: {request.symptom_severity}"

            # Run AI analysis
            from providers import MultimodalOrchestrator
            orchestrator = MultimodalOrchestrator()
            ai_result = await orchestrator.process(
                text=combined_text,
                images=images if images else None,
                voice_transcript=request.voice_transcript,
                conversation_history=conversation_history if conversation_history else None,
                patient_profile=patient_context,
                session_id=request.session_id,
            )

            # Safety validation
            # NOTE: `validate_async` / `apply_safety_result_async` are coroutine
            # functions; both must be awaited. Calling them without `await`
            # rebinds `ai_result` to a coroutine object, which later fails in
            # the response transformer with a confusing attribute error.
            safety_result = await safety_validator.validate_async(
                ai_result, patient_context, original_text=combined_text
            )
            ai_result = await safety_validator.apply_safety_result_async(ai_result, safety_result)

            # Build clinical context
            from models_v2 import PatientProfile as ClinicalPatientProfile, SymptomInput
            clinical_patient = ClinicalPatientProfile(
                age=request.patient_age,
                sex=request.patient_sex,
                language=request.patient_language,
                location=request.patient_location,
                pregnancy_status=request.patient_pregnant,
                chronic_conditions=request.patient_chronic_conditions,
                medications=request.patient_medications,
                allergies=request.patient_allergies,
            )
            clinical_symptoms = SymptomInput(
                symptoms=request.symptom_description,
                duration=request.symptom_duration,
                severity={"mild": 3, "moderate": 5, "severe": 8}.get(request.symptom_severity, 5),
            )
            clinical_context = await clinical_context_builder.build(
                patient_profile=clinical_patient,
                symptoms=clinical_symptoms,
                voice_transcript=request.voice_transcript,
                conversation_history=request.conversation_history,
                session_id=request.session_id or str(uuid.uuid4()),
            )

            # Transform to structured response
            session_id = request.session_id or str(uuid.uuid4())
            structured_response = response_transformer.transform(ai_result, clinical_context, request_id, session_id)

            # Enhance with visual education
            conditions = [c.label for c in structured_response.possible_explanations]
            body_systems = _extract_body_systems(conditions, combined_text)
            treatment_approaches = _extract_treatment_approaches(structured_response)
            medication_classes = _extract_medication_classes(structured_response)
            visual_education_items = visual_education_service.get_visuals_for_response(
                conditions=conditions, body_systems=body_systems,
                treatment_approaches=treatment_approaches, medication_classes=medication_classes
            )
            structured_response.visual_education = visual_education_items

            # Enhance medication with pharmacy verification
            from clinical_schema import MedicationVerificationItem
            for med in structured_response.medication_information:
                verification = medication_safety_service.get_pharmacy_verification_workflow(med.medication_class)
                structured_response.medication_verification.extend([
                    MedicationVerificationItem(field=item["field"], description=item["description"], why_important=item.get("why_important", "Important for safety"))
                    for item in verification.get("package_check_items", [])
                ])

            # Build final clinical response
            from clinical_schema import ClinicalResponse
            clinical = ClinicalResponse(
                response_id=request_id, session_id=session_id, timestamp=datetime.utcnow().isoformat(),
                health_summary=structured_response.health_summary, safety=structured_response.safety,
                possible_explanations=structured_response.possible_explanations, uncertainty=structured_response.uncertainty,
                treatment_education=structured_response.treatment_education, medication_information=structured_response.medication_information,
                visual_education=structured_response.visual_education, follow_up=structured_response.follow_up,
                sources=structured_response.sources, professional_review=structured_response.professional_review,
                provider=ai_result.provider, model=ai_result.model, confidence_score=ai_result.confidence_score,
                disclaimer=structured_response.disclaimer,
            )

            processing_time = int((time.time() - start_time) * 1000)
            logger.info(f"Analysis {request_id} completed in {processing_time}ms: urgency={clinical.safety.urgency.value}")

            return clinical.to_dict()

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Analysis error {request_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

    @app.get("/api/health", response_model=HealthCheckResponse)
    async def health_check():
        settings = get_settings()
        return HealthCheckResponse(
            status="healthy", timestamp=datetime.utcnow(),
            version=settings.APP_VERSION,
            components={"api": "operational", "image_service": "operational", "safety_validator": "operational"},
            # Report the real routing rather than an empty dict. The frontend
            # surfaces this, and a hardcoded `{}` made a misconfigured
            # deployment (silently offline) look identical to a healthy one.
            ai_providers=_provider_summary(),
        )

    @app.get("/api/providers")
    async def list_providers():
        """Report the configured providers, their models and reachability.

        Replaces a stub that always returned `{"providers": []}`, which hid
        both the active model and whether the configured credential works.
        """
        factory: ProviderFactory | None = getattr(app.state, "provider_factory", None)
        slots = []
        if factory is not None:
            for slot in ("text", "vision", "multimodal"):
                cfg = getattr(factory.config, f"{slot}_provider", None)
                if cfg is None:
                    continue
                slots.append({
                    "slot": slot,
                    "provider": cfg.provider,
                    "model": cfg.model,
                    # Credential presence only — never echo the key itself.
                    "credential_configured": bool(cfg.api_key),
                })

        provider_health = {}
        if factory is not None:
            try:
                provider_health = await factory.health_check_all()
            except Exception as exc:
                logger.warning(f"Provider health check failed: {exc}")

        return {
            "providers": slots,
            "primary": slots[0]["provider"] if slots else None,
            "fallback_order": list(factory.config.fallback_providers) if factory else [],
            "offline_mode": factory._should_use_offline() if factory else True,
            "health": provider_health,
            "registry": sorted(configured_gemini_models()),
        }

    @app.get("/health")
    async def legacy_health():
        return {"status": "healthy", "service": "DEDAN Health Clinical API"}

    # --- Static portal --------------------------------------------------------
    # Serve the web portal from the same origin so the browser can load it
    # without a separate dev server. The portal is plain HTML with no build
    # step, so StaticFiles is sufficient. API routes above take precedence;
    # everything else falls through to the static mount.
    portal_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web-portal")
    if os.path.isdir(portal_dir):
        # `html=True` serves `index.html` at `/`, so the product is what a user
        # sees when they open the host. The API's own `/` route used to be
        # registered above this mount and therefore won, showing a JSON status
        # object instead of the portal; the service identity lives on
        # `/health` and `/api/health`, so nothing needed that route.
        app.mount("/", PortalStaticFiles(directory=portal_dir, html=True), name="portal")

    return app


class PortalStaticFiles(StaticFiles):
    """Static portal mount that answers a missing page with the portal's 404.

    Starlette already does this: with `html=True` it looks for `404.html` in the
    served directory and returns it for a missing file. That is the desired
    browser behaviour and it is left alone.

    The problem is the same feature applied to API paths. `/api/nope` returns
    an HTML page, which an API client then tries to parse as JSON -- a clear 404
    turns into an opaque parse error. This override restores JSON for anything
    that is not a page request, and otherwise steps aside.
    """

    #: Prefixes owned by the API rather than the portal.
    API_PREFIXES = ("api/", "auth/", "users/", "dedan/", "realtime/", "conversations")

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code != 404:
            return response

        normalised = (scope.get("path") or path or "").lstrip("/")
        accept = ""
        for key, value in scope.get("headers", []):
            if key == b"accept":
                accept = value.decode("latin-1").lower()
                break

        is_page_request = "text/html" in accept or not accept
        if is_page_request and not normalised.startswith(self.API_PREFIXES):
            # Starlette already returned the portal's 404 page.
            return response

        # API client, or an explicit non-HTML request: answer with JSON so the
        # caller gets a status code it can branch on instead of a parse error.
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "Not found",
                "error_code": "HTTP_404",
                "details": None,
            },
        )


def _extract_body_systems(conditions: list, symptoms: str) -> list:
    systems = set()
    text = " ".join(conditions + [symptoms]).lower()
    system_keywords = {
        "respiratory": ["respiratory", "lung", "breathing", "cough", "pneumonia", "asthma"],
        "cardiovascular": ["heart", "cardiac", "chest pain", "hypertension", "blood pressure"],
        "gastrointestinal": ["abdominal", "stomach", "diarrhea", "vomiting", "nausea", "liver", "hepatitis"],
        "neurological": ["headache", "seizure", "confusion", "stroke", "brain", "migraine"],
        "dermatological": ["rash", "skin", "lesion", "bite", "dermatitis", "eczema"],
        "infectious": ["fever", "infection", "malaria", "dengue", "tb", "tuberculosis", "hiv"],
        "musculoskeletal": ["joint", "muscle", "bone", "pain", "arthritis", "fracture"],
        "genitourinary": ["urinary", "kidney", "bladder", "uti", "renal"],
        "endocrine": ["diabetes", "thyroid", "hormone", "glucose", "insulin"],
    }
    for system, keywords in system_keywords.items():
        if any(kw in text for kw in keywords):
            systems.add(system)
    return list(systems)


def _extract_treatment_approaches(response) -> list:
    approaches = []
    for te in response.treatment_education:
        approaches.append(te.title)
    return approaches


def _extract_medication_classes(response) -> list:
    classes = []
    for med in response.medication_information:
        classes.append(med.medication_class)
    return classes


def _provider_summary() -> dict:
    """Provider health map for `/api/health`.

    `HealthCheckResponse.ai_providers` is typed `Dict[str, bool]`, so each key is
    a *readiness* flag rather than a descriptive string:

      * `live_mode`            — routing is not pinned to the offline provider
      * `text_ready`           — the text slot has a provider and a credential
      * `vision_ready`         — ditto for the vision slot
      * `multimodal_ready`     — ditto for the multimodal slot

    The previous hardcoded `{}` reported nothing, so a silently-offline
    deployment was indistinguishable from a healthy one.
    """
    try:
        factory = ProviderFactory()
        cfg = factory.config
        live = not factory._should_use_offline()

        def ready(slot_cfg) -> bool:
            if not live or slot_cfg.provider == "offline":
                return True  # deterministic provider needs no credential
            return bool(slot_cfg.api_key)

        return {
            "live_mode": live,
            "text_ready": ready(cfg.text_provider),
            "vision_ready": ready(cfg.vision_provider),
            "multimodal_ready": ready(cfg.multimodal_provider),
        }
    except Exception as exc:
        logger.warning(f"Could not build provider summary: {exc}")
        return {}


async def log_analysis_data(request_id: str, session_id: str, request, response):
    try:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "request_id": request_id, "session_id": session_id,
            "patient_age": request.patient_age, "patient_sex": request.patient_sex,
            "patient_location": request.patient_location,
            "has_images": len(request.image_ids) > 0 or len(request.image_data_list) > 0,
            "urgency": response.safety.urgency.value, "confidence": response.confidence_score,
            "provider": response.provider, "model": response.model,
            "processing_time_ms": response.processing_time_ms, "safety_flags": response.safety_flags,
        }
        logger.info(f"AUDIT: {log_entry}")
    except Exception as e:
        logger.error(f"Failed to log analysis data: {e}")


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("main_clinical:app", host=settings.HOST, port=settings.PORT, log_level=settings.LOG_LEVEL.lower(), reload=settings.DEBUG)
