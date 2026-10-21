"""The platform's internal API, for the hospital service only.

Runs as its own service (``internal-api`` in deploy/docker-compose.yml), the
only part of the platform on the private ``endod-bus`` network (alias
``endod-platform-api``). It serves nothing but ``/internal/...`` (each route
requires ``X-Platform-Key``) and ``/health``: the patient API is not reachable
from that network at all, and the patient app (main_clinical) does not serve
``/internal``.

No proxy sits in front of it, so forwarded-address headers are never trusted
(TRUST_PROXY_HEADERS is off for this service).

    uvicorn main_internal:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware

logger = logging.getLogger(__name__)

#: The names the hospital service and the container's own health check use.
DEFAULT_HOSTS = ["endod-platform-api", "localhost", "127.0.0.1"]


def allowed_hosts() -> List[str]:
    configured = [h.strip() for h in os.getenv("INTERNAL_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return configured or DEFAULT_HOSTS


def create_app() -> FastAPI:
    # No middleware here reads a client's address at all (no proxy headers,
    # no rate limit keyed on them); the service runs with TRUST_PROXY_HEADERS
    # off all the same.
    from dedan_platform.api_history import internal_router

    app = FastAPI(title="Endod internal API", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())
    app.include_router(internal_router)

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "healthy", "service": "Endod internal API"}

    return app


app = create_app()
