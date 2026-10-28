"""The platform's internal API, for the hospital service and the pharmacy site.

Runs as its own service (``internal-api`` in deploy/docker-compose.yml), the
only part of the platform on the private ``endod-bus`` network (alias
``endod-platform-api``). It serves nothing but ``/internal/...`` (each route
requires ``X-Platform-Key``), ``/pharmacy/...`` (each route requires
``X-Pharmacy-Key``; docs/pharmacy.md) and ``/health``: the patient API is not
reachable from that network at all, and the patient app (main_clinical)
serves neither ``/internal`` nor ``/pharmacy``.

No proxy sits in front of it, so forwarded-address headers are never trusted
(TRUST_PROXY_HEADERS is off for this service). The pharmacy routes' rate
limits use ``X-Client-IP``, which only the pharmacy site's server (holding
the key) can send.

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
    # No middleware here reads a client's address (no proxy headers); the
    # pharmacy routes key their limits on X-Client-IP, behind their key.
    from dedan_platform import crypto
    from dedan_platform.api_history import internal_router
    from dedan_platform.api_pharmacy import router as pharmacy_router

    # It decrypts records for pharmacies and shared files for hospitals: no
    # production start without the master key (dedan_platform/crypto.py).
    crypto.require_master_key()

    app = FastAPI(title="Endod internal API", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())
    app.include_router(internal_router)
    app.include_router(pharmacy_router)

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "healthy", "service": "Endod internal API"}

    return app


app = create_app()
