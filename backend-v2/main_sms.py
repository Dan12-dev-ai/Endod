"""The inbound SMS service: commands patients text to the short code (docs/sms.md).

Runs as its own service (``sms-inbound`` in deploy/docker-compose.yml), the
only part of the platform on the shared nginx's network besides the web app
(alias ``endod-sms-inbound``), published at
``https://api.endod-health.com/sms/v1/...`` (deploy/shared-nginx/endod.conf).
It serves nothing but ``/sms/v1/inbound/...`` (dedan_platform/api_sms.py:
404 while ``SMS_INBOUND_ENABLED`` is off) and ``/health``: the patient API is
not reachable through it.

    uvicorn main_sms:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from typing import Dict

from fastapi import FastAPI


def create_app() -> FastAPI:
    from dedan_platform import crypto
    from dedan_platform.api_sms import router

    # It reads (decrypts) lab results and reports to answer RESULT and REPORT.
    crypto.require_master_key("sms-inbound")
    crypto.verify_master_key()

    app = FastAPI(title="Endod inbound SMS", docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(router)

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "healthy", "service": "Endod inbound SMS"}

    return app


app = create_app()
