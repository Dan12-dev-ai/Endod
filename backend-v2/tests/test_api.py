"""
HTTP-level tests for the DEDAN Health Clinical API.

Covers the contract a client actually depends on:
  * health / discovery endpoints
  * request validation (missing, malformed, out-of-range fields)
  * the `/api/analyze` happy path and its structured response shape
  * safety-critical escalation for red-flag symptoms
  * consent enforcement
  * image upload validation and lifecycle
  * predictable error envelopes

All of this runs against the offline (deterministic) provider, so the suite is
hermetic: no credentials, no network, no paid calls.
"""

import base64
import io

import pytest

PNG_1PX = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    b"IQAAAABJRU5ErkJggg=="
)
import struct
import zlib

# The image pipeline rejects anything smaller than 224x224, so fixtures under
# test must clear that gate. A deliberately tiny image is kept for the
# "rejected" test.
PNG_1PX = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    b"IQAAAABJRU5ErkJggg=="
)


def make_png(width: int, height: int) -> bytes:
    """Build a valid, deterministic PNG without extra dependencies.

    Encoding it here (rather than committing a binary blob) keeps the test
    suite self-contained and reviewable, and avoids adding Pillow as a test
    dependency just to fabricate a fixture.

    The pixel data is pseudo-random rather than a smooth gradient: the image
    pipeline rejects files under 1 KiB as "possibly corrupted", and a
    compressible gradient would fall below that threshold.
    """
    rows = []
    for y in range(height):
        # Deterministic LCG — stable across runs, but not deflate-friendly.
        row = bytearray([0])  # PNG filter type 0 (None)
        seed = (y + 1) * 1103515245 + 12345
        for _ in range(width):
            seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
            row.append((seed >> 16) & 0xFF)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# Health & discovery
# ---------------------------------------------------------------------------
class TestHealthEndpoints:
    def test_api_health_reports_healthy(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "version" in body
        assert "components" in body

    def test_legacy_health_alias(self, client):
        """`/health` is kept as a stable alias for probes and load balancers."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_root_serves_the_portal(self, client):
        """`/` is the portal; the service identity lives on `/health`."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")

    def test_providers_endpoint_returns_a_valid_envelope(self, client):
        resp = client.get("/api/providers")
        assert resp.status_code == 200
        body = resp.json()
        assert {"providers", "primary", "fallback_order", "offline_mode", "registry"} <= set(body)
        assert body["offline_mode"] is True


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------
class TestAnalyzeValidation:
    def test_missing_required_fields_is_422(self, client):
        resp = client.post("/api/analyze", json={})
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "VALIDATION_ERROR"

    def test_missing_symptom_description_is_422(self, client, valid_payload):
        del valid_payload["symptom_description"]
        resp = client.post("/api/analyze", json=valid_payload)
        assert resp.status_code == 422

    def test_empty_symptom_description_is_422(self, client, valid_payload):
        """`symptom_description` enforces `min_length=10`."""
        valid_payload["symptom_description"] = ""
        resp = client.post("/api/analyze", json=valid_payload)
        assert resp.status_code == 422

    @pytest.mark.parametrize("age", [-1, 151, 999])
    def test_out_of_range_age_is_422(self, client, valid_payload, age):
        valid_payload["patient_age"] = age
        resp = client.post("/api/analyze", json=valid_payload)
        assert resp.status_code == 422

    def test_invalid_sex_is_422(self, client, valid_payload):
        valid_payload["patient_sex"] = "not-a-valid-sex"
        resp = client.post("/api/analyze", json=valid_payload)
        assert resp.status_code == 422

    def test_malformed_json_is_422(self, client):
        resp = client.post(
            "/api/analyze",
            content=b"{not-valid-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_without_consent_is_400(self, client, valid_payload):
        """Consent is a hard precondition: rejected before any AI call."""
        valid_payload["consent"] = False
        resp = client.post("/api/analyze", json=valid_payload)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Analyze happy path
# ---------------------------------------------------------------------------
class TestAnalyzeResponse:
    def test_returns_structured_clinical_response(self, client, valid_payload):
        resp = client.post("/api/analyze", json=valid_payload)
        assert resp.status_code == 200
        body = resp.json()

        # Identity / envelope
        assert body["response_id"]
        assert body["session_id"]
        assert body["timestamp"]

        # Structured clinical sections
        for key in (
            "health_summary",
            "safety",
            "possible_explanations",
            "uncertainty",
            "treatment_education",
            "medication_information",
            "follow_up",
            "sources",
        ):
            assert key in body, f"missing structured section: {key}"

        assert body["safety"]["urgency"] in {
            "emergency",
            "urgent",
            "routine",
            "self_care",
            "see_doctor_soon",
        }
        assert 0.0 <= body["confidence_score"] <= 1.0

    def test_response_carries_a_medical_disclaimer(self, client, valid_payload):
        resp = client.post("/api/analyze", json=valid_payload)
        disclaimer = resp.json().get("disclaimer", "").lower()
        # The disclaimer must disclaim diagnosis AND point to a professional.
        assert "does not provide medical diagnoses" in disclaimer
        assert "healthcare professional" in disclaimer
        assert "emergency" in disclaimer

    def test_session_id_is_echoed_when_supplied(self, client, valid_payload):
        valid_payload["session_id"] = "session-abc-123"
        resp = client.post("/api/analyze", json=valid_payload)
        assert resp.json()["session_id"] == "session-abc-123"

    def test_response_is_json_serialisable(self, client, valid_payload):
        import json

        resp = client.post("/api/analyze", json=valid_payload)
        # Round-trips without raising.
        json.dumps(resp.json())


# ---------------------------------------------------------------------------
# Safety behaviour
# ---------------------------------------------------------------------------
class TestSafetyEscalation:
    @pytest.mark.parametrize(
        "symptoms",
        [
            "severe chest pain and difficulty breathing",
            "sudden slurred speech and facial droop",
            "unconscious and not waking up",
        ],
    )
    def test_red_flag_symptoms_escalate_to_emergency(self, client, valid_payload, symptoms):
        """Red-flag language must never resolve to a routine disposition."""
        valid_payload["symptom_description"] = symptoms
        resp = client.post("/api/analyze", json=valid_payload)
        assert resp.status_code == 200
        safety = resp.json()["safety"]
        assert safety["urgency"] == "emergency"
        assert safety["requires_immediate_care"] is True

    def test_professional_review_is_recommended(self, client, valid_payload):
        resp = client.post("/api/analyze", json=valid_payload)
        assert resp.json()["safety"]["professional_review_required"] is True

    def test_medication_output_is_educational_only(self, client, valid_payload):
        """Medication entries must be flagged as education, not prescribing."""
        resp = client.post("/api/analyze", json=valid_payload)
        for med in resp.json()["medication_information"]:
            assert med.get("is_educational_only") is True


# ---------------------------------------------------------------------------
# Image endpoints
# ---------------------------------------------------------------------------
class TestImageEndpoints:
    def test_upload_png_and_read_metadata(self, client):
        resp = client.post(
            "/api/images/upload",
            files={"file": ("scan.png", io.BytesIO(make_png(256, 256)), "image/png")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["image_id"]
        assert body["mime_type"] == "image/png"

        meta = client.get(f"/api/images/{body['image_id']}")
        assert meta.status_code == 200
        assert meta.json()["image_id"] == body["image_id"]

    def test_rejects_unsupported_mime_type(self, client):
        resp = client.post(
            "/api/images/upload",
            files={"file": ("evil.exe", io.BytesIO(b"MZ..."), "application/x-msdownload")},
        )
        assert resp.status_code == 400

    def test_rejects_image_below_minimum_dimensions(self, client):
        """The quality gate rejects images under 224x224 before storage."""
        resp = client.post(
            "/api/images/upload",
            files={"file": ("tiny.png", io.BytesIO(PNG_1PX), "image/png")},
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "HTTP_400"

    def test_unknown_image_id_is_404(self, client):
        assert client.get("/api/images/does-not-exist").status_code == 404
        assert client.get("/api/images/does-not-exist/preview").status_code == 404

    def test_delete_image(self, client):
        created = client.post(
            "/api/images/upload",
            files={"file": ("scan.png", io.BytesIO(make_png(256, 256)), "image/png")},
        ).json()
        image_id = created["image_id"]

        deleted = client.delete(f"/api/images/{image_id}")
        assert deleted.status_code == 200
        assert client.get(f"/api/images/{image_id}").status_code == 404


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------
class TestErrorEnvelope:
    def test_validation_error_shape(self, client):
        body = client.post("/api/analyze", json={}).json()
        assert body["error_code"] == "VALIDATION_ERROR"
        # The shared error envelope is `{error, error_code, details, timestamp}`.
        assert "error" in body
        assert "timestamp" in body
        assert isinstance(body["details"], list)

    def test_internal_errors_do_not_leak_stack_traces(self, client):
        """With DEBUG=false, error bodies must not expose internals."""
        resp = client.post(
            "/api/analyze",
            content=b"\x00\x01\x02",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 422)
        assert "Traceback" not in resp.text
        assert 'File "' not in resp.text

