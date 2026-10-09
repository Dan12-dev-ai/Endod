#!/usr/bin/env python3
"""Capture screenshots of every portal page for visual review.

Runs the real journey (register -> consent -> consult -> book) so the
screenshots show populated screens rather than empty states, then shoots each
page at desktop width.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8001"
OUT = "/tmp/opencode/shots"
CHROME = "/usr/bin/chromium"

os.makedirs(OUT, exist_ok=True)


def main() -> int:
    stamp = int(time.time())
    email = f"shots.{stamp}@example.com"
    password = "ScreenshotReview2026"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1500, "height": 1000})
        page = ctx.new_page()

        # Seed a populated account through the API so every screen has content.
        req = urllib.request.Request(
            f"{BASE}/auth/register", method="POST",
            data=json.dumps({
                "first_name": "Amara", "last_name": "Ochieng",
                "email": email, "password": password, "password_confirmation": password,
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        token = json.loads(urllib.request.urlopen(req).read())["access_token"]

        def call(method, path, body=None):
            data = json.dumps(body).encode() if body else None
            r = urllib.request.Request(BASE + path, method=method, data=data, headers={
                "Authorization": token, "Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(r).read()) if data else urllib.request.urlopen(r).read()

        call("PATCH", "/users/me/consent", {"treatment_processing": True})
        call("PATCH", "/users/me/health-profile", {
            "sex": "female", "blood_type": "O+", "allergies": "penicillin, latex",
            "medications": "amoxicillin 500mg", "conditions": "asthma",
            "emergency_contact_name": "Grace Ochieng", "emergency_contact_phone": "+254722334455",
        })
        call("POST", "/users/me/appointments", {
            "scheduled_at": "2026-11-12T09:30:00+00:00", "appointment_type": "consultation",
            "duration_minutes": 30, "location": "Nairobi National Hospital",
            "notes": "Review of persistent headaches",
        })
        call("POST", "/users/me/appointments", {
            "scheduled_at": "2026-12-03T14:00:00+00:00", "appointment_type": "follow_up",
            "duration_minutes": 30, "location": "Kenyatta National Hospital",
            "notes": "Asthma action-plan review",
        })
        call("POST", "/users/me/care/navigation", {
            "facility_name": "Nairobi National Hospital", "symptoms": ["headache", "fever"],
            "urgency": "routine", "reason": "Routed from AI consultation",
        })

        # Public pages first (no session in this context yet).
        page.goto(f"{BASE}/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.screenshot(path=f"{OUT}/01-landing.png", full_page=False)

        page.goto(f"{BASE}/login.html", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        page.screenshot(path=f"{OUT}/02-login.png")

        page.goto(f"{BASE}/register.html", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        page.screenshot(path=f"{OUT}/03-register.png")

        # Now sign in for the rest.
        page.goto(f"{BASE}/login.html", wait_until="domcontentloaded")
        page.evaluate("(t) => localStorage.setItem('dedan.session.token', t)", token)
        page.wait_for_timeout(500)

        shots = [
            ("04-dashboard", "index.html", "#dash-timeline", 3500),
            ("05-consultation", "live-discussion.html", "#message-input", 3000),
            ("06-history", "health-history.html", "#timeline", 3500),
            ("07-appointments", "appointments.html", "#booking-form", 3000),
            ("08-find-care", "find-hospitals.html", "#care-search-form", 2500),
            ("09-settings", "settings.html", "#set-phone", 3500),
        ]
        for name, page_name, selector, wait in shots:
            page.goto(f"{BASE}/{page_name}", wait_until="domcontentloaded")
            try:
                page.wait_for_selector(selector, timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(wait)
            # The icon font is a webfont; capture before it settles and every
            # ligature renders as its literal word ("delete", "event").
            try:
                page.wait_for_function(
                    "() => document.fonts.check('16px \"Material Symbols Outlined\"')",
                    timeout=15000,
                )
            except Exception:
                print(f"  note: icon font not confirmed on {page_name}")
            if page_name == "live-discussion.html":
                page.fill("#patient-age", "34")
                page.fill("#message-input", "I have had a persistent headache with a mild fever for two days")
                page.click("#send-btn")
                page.wait_for_selector("#analysis-panel .font-semibold", timeout=40000)
                page.wait_for_timeout(2000)
            if page_name == "find-hospitals.html":
                page.fill("#search-symptoms", "headache, fever")
                page.click("#care-search-form button[type=submit]")
                page.wait_for_selector("#results article", timeout=25000)
                page.wait_for_timeout(1800)
            page.screenshot(path=f"{OUT}/{name}.png")
            print("captured", name)

        browser.close()

    print("\nscreenshots in", OUT)
    for f in sorted(os.listdir(OUT)):
        print(f"  {f}  {os.path.getsize(os.path.join(OUT, f)) // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
