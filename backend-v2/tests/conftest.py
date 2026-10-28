"""
Shared pytest configuration and fixtures for the DEDAN Health backend suite.

Design constraints
------------------
1. The suite MUST run with no provider credentials and no network access.
   `AI_PROVIDER_MODE=offline` is exported *before* the application module is
   imported so `ProviderFactory` selects the deterministic `OfflineProvider`.
2. `backend-v2/` uses a flat module layout (not a package), so the backend root
   is prepended to `sys.path`. This keeps `pytest` runnable from any cwd.
"""

import os
import sys
from pathlib import Path

import pytest

# --- Credential-free, deterministic mode -------------------------------------
# Set before importing the application: the factory reads these at init time.
os.environ.setdefault("AI_PROVIDER_MODE", "offline")
# Suppress the interactive docs and stack-trace leakage in error payloads.
os.environ.setdefault("DEBUG", "false")
# Blank out credentials so a developer's real keys in the shell cannot cause a
# live provider call (which would also make the suite non-deterministic).
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")

# A real master key file (32 random bytes) for the encryption of health data,
# as deployments mount one (dedan_platform/crypto.py). Without it, tests that
# run with ENVIRONMENT=production would be refused, as production is.
if not os.environ.get("PLATFORM_MASTER_KEY_FILE"):
    import atexit
    import shutil
    import tempfile

    _key_dir = tempfile.mkdtemp(prefix="endod-test-key-")
    atexit.register(shutil.rmtree, _key_dir, ignore_errors=True)
    _key_path = os.path.join(_key_dir, "master.key")
    with open(_key_path, "wb") as _key_file:
        _key_file.write(os.urandom(32))
    os.environ["PLATFORM_MASTER_KEY_FILE"] = _key_path
    # The key is new on every run, and the database records which key its data
    # keys are wrapped with: tests that use the default database get a fresh
    # one per run too, not ./dedan_platform.db from an earlier run.
    os.environ.setdefault("DEDAN_DATABASE_URL", f"sqlite:///{os.path.join(_key_dir, 'default.db')}")

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# The app enforces an in-process per-IP rate limit (30 req/min by default).
# A full test run issues far more requests than that from a single client, so
# the limit is raised here. It is NOT disabled: tests still assert the limiter
# is present, and the production default is unchanged.
os.environ.setdefault("RATE_LIMIT_REQUESTS", "100000")


@pytest.fixture(scope="session")
def app_module():
    """Import the FastAPI application module once per session."""
    import main_clinical

    return main_clinical


@pytest.fixture(scope="session")
def client(app_module):
    """A synchronous ``TestClient`` bound to the ASGI app."""
    from fastapi.testclient import TestClient

    return TestClient(app_module.app)


@pytest.fixture
def valid_payload():
    """A minimal request body that satisfies ``AnalyzeRequest`` validation."""
    return {
        "patient_age": 30,
        "patient_sex": "female",
        "symptom_description": "persistent headache for two days",
        "consent": True,
    }


# --- Chapa, as its API behaves (payments and refunds) ------------------------------

class FakeChapa:
    """Chapa's initialize, verify and refund endpoints, with payments the test
    can mark paid and refunds it can move along or make fail."""

    KEY = "Bearer CHASECK_TEST-key"

    def __init__(self):
        self.payments = {}  # tx_ref -> {"amount": "100.00", "status": "pending", "currency": "ETB"}
        self.initialized = []
        self.outage = None  # an HTTP status Chapa answers verify with (e.g. 503)
        self.refund_requests = []  # bodies of POST /refund/{tx_ref}, with "tx_ref" added
        self.refunds = {}  # ref_id -> {"status": "processing", "reference": ...}
        #: How POST /refund answers: None (accepts), an HTTP status (e.g. 503), "refuse",
        #: or "lost" (accepts it, but the answer never arrives: a timeout).
        self.refund_outcome = None

    def handler(self, request):
        import json

        import httpx

        assert request.headers["Authorization"] == self.KEY
        path = request.url.path
        if path.endswith("/transaction/initialize"):
            body = json.loads(request.content)
            self.initialized.append(body)
            self.payments[body["tx_ref"]] = {"amount": body["amount"], "status": "pending", "currency": "ETB"}
            return httpx.Response(200, json={"status": "success", "message": "Hosted Link",
                                             "data": {"checkout_url": f"https://checkout.chapa.co/{body['tx_ref']}"}})
        if "/transaction/verify/" in path:
            if self.outage:
                return httpx.Response(self.outage, json={"message": "unavailable"})
            tx_ref = path.rsplit("/", 1)[-1]
            payment = self.payments.get(tx_ref)
            if payment is None:
                return httpx.Response(404, json={"status": "failed", "message": "Invalid transaction", "data": None})
            return httpx.Response(200, json={"status": "success", "data": {
                "status": payment["status"], "amount": payment["amount"], "currency": payment["currency"],
                "tx_ref": tx_ref, "reference": "APabc123"}})
        if path.endswith("/verify") and "/refund/" in path:
            ref_id = path.split("/")[-2]
            refund = self.refunds.get(ref_id)
            if refund is None:
                return httpx.Response(404, json={"status": "failed", "message": "Refund not found", "data": None})
            return httpx.Response(200, json={"status": "success", "data": {"ref_id": ref_id, **refund}})
        if "/refund/" in path and request.method == "POST":
            tx_ref = path.rsplit("/", 1)[-1]
            body = json.loads(request.content)
            self.refund_requests.append({**body, "tx_ref": tx_ref})
            if isinstance(self.refund_outcome, int):
                return httpx.Response(self.refund_outcome, json={"message": "unavailable"})
            if self.refund_outcome == "refuse":
                return httpx.Response(400, json={"status": "failed", "message": "Insufficient balance", "data": None})
            if any(r["reference"] == body.get("reference") for r in self.refunds.values()):
                return httpx.Response(400, json={"status": "failed", "message": "Duplicate reference", "data": None})
            payment = self.payments.get(tx_ref)
            if payment is None or payment["status"] != "success":
                return httpx.Response(400, json={"status": "failed", "message": "Not refundable", "data": None})
            ref_id = f"MERC-REF-{len(self.refunds) + 1}"
            self.refunds[ref_id] = {"status": "processing", "reference": body.get("reference"),
                                    "amount": body.get("amount"), "tx_ref": tx_ref}
            if self.refund_outcome == "lost":
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(200, json={"status": "success", "message": "Refund initiated successfully",
                                             "data": {"ref_id": ref_id, "payment_reference": "APabc123"}})
        return httpx.Response(404)

    def pay(self, tx_ref, amount=None, currency="ETB"):
        payment = self.payments[tx_ref]
        payment["status"] = "success"
        payment["currency"] = currency
        if amount is not None:
            payment["amount"] = amount

    def pay_booking(self, client, response, amount=None, currency="ETB"):
        """Pay the booking ``response`` (from POST /users/me/appointments) on
        Chapa and let the callback confirm it. Returns the appointment id."""
        body = response.json()
        assert response.status_code == 201, body
        tx_ref = body["payment"]["tx_ref"]
        self.pay(tx_ref, amount=amount, currency=currency)
        client.get(f"/payments/chapa/callback?trx_ref={tx_ref}")
        return body["appointment"]["appointment_id"]

    def finish_refunds(self, status="refunded"):
        """Chapa finishes its refunds; a completed one shows on the payment too."""
        for refund in self.refunds.values():
            refund["status"] = status
            if status == "refunded":
                self.payments[refund["tx_ref"]]["status"] = "refunded"


@pytest.fixture
def chapa_api(monkeypatch):
    import httpx

    from dedan_platform import chapa

    fake = FakeChapa()
    monkeypatch.setattr(chapa, "_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setenv("CHAPA_SECRET_KEY", "CHASECK_TEST-key")
    return fake
