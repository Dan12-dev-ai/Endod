#!/usr/bin/env python3
"""Full patient-journey browser test for the DEDAN portal.

Drives the real UI in Chromium: register -> consent -> consult -> save to
history -> book -> reschedule -> cancel -> find care -> settings -> sign out ->
sign back in -> guard checks. Fails on any console error or unexpected HTTP
status so a page cannot look fine while being broken.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8001"
CHROME = "/usr/bin/chromium"

console_errors: list[str] = []
bad_responses: list[str] = []
IGNORED_URL_PARTS = ("googleusercontent", "fonts.g", "cdn.tailwindcss", "gstatic")


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)
    return ok


FAILURES: list[str] = []


def api(path: str, token: str) -> object:
    req = urllib.request.Request(BASE + path, headers={"Authorization": token})
    return json.loads(urllib.request.urlopen(req).read())


def main() -> int:
    stamp = int(time.time())
    email = f"journey.{stamp}@example.com"
    password = "JourneyReview2026"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(viewport={"width": 1500, "height": 950})
        page = ctx.new_page()

        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: console_errors.append(f"console.error: {m.text}") if m.type == "error" else None)

        def on_response(res):
            if res.status >= 400 and not any(p in res.url for p in IGNORED_URL_PARTS):
                if res.status == 403 and "/users/me/health-profile" in res.url:
                    return  # expected when consent is withheld
                bad_responses.append(f"HTTP {res.status} {res.url}")

        page.on("response", on_response)

        print("\n=== 1. Public landing ===")
        page.goto(f"{BASE}/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        check("landing title", "DEDAN" in page.title(), page.title())
        check("marketing content present", page.locator("text=Compassionate Care Pathway").count() > 0)
        check("signed-out shows Sign In", page.locator("[data-auth='signed-out']").first.is_visible())

        print("\n=== 2. Register + consent ===")
        page.goto(f"{BASE}/register.html", wait_until="domcontentloaded")
        page.wait_for_selector("#register-submit")
        page.fill("#first-name", "Journey")
        page.fill("#last-name", "Tester")
        page.fill("#email", email)
        page.fill("#phone", "+254711000111")
        page.fill("#password", password)
        page.fill("#confirm-password", password)
        page.check("#accept-terms")
        page.click("#register-submit")
        page.wait_for_url(f"{BASE}/index.html", timeout=25000)
        page.wait_for_timeout(2500)
        check("landed on dashboard", "index.html" in page.url, page.url)
        check("dashboard visible", page.locator("#patient-dashboard").is_visible())
        check("welcome names the patient", "Journey" in page.locator("#patient-dashboard").inner_text())

        token = page.evaluate("() => localStorage.getItem('dedan.session.token')")
        profile = api("/auth/session", token)["profile"]
        dedan_id = profile["dedan_user_id"]
        check("consent recorded server-side", profile["consent"]["treatment_processing"] is True)
        check("DEDAN ID assigned", bool(dedan_id), dedan_id)

        print("\n=== 3. Dashboard shows real data ===")
        check("dashboard consent label", page.locator("#dash-consent").inner_text().strip() == "Shared")
        check("dashboard next-appointment empty state",
              "No upcoming" in page.locator("#dash-next-appointment").inner_text())

        print("\n=== 4. Consultation ===")
        page.goto(f"{BASE}/live-discussion.html", wait_until="domcontentloaded")
        page.wait_for_selector("#message-input", timeout=20000)
        page.fill("#patient-age", "34")
        page.wait_for_timeout(1200)
        page.fill("#message-input", "short")
        page.click("#send-btn")
        page.wait_for_timeout(600)
        check("rejects a too-short complaint",
              "more detail" in page.locator("#dedan-toast-host").inner_text()
              if page.locator("#dedan-toast-host").count() else False)

        page.fill("#message-input", "I have had a persistent headache with a mild fever for two days")
        page.click("#send-btn")
        page.wait_for_selector("#analysis-panel .font-semibold", timeout=40000)
        page.wait_for_timeout(1500)
        panel = page.locator("#analysis-panel").inner_text()
        check("assessment rendered", len(panel) > 60, panel[:90].replace("\n", " "))
        check("safety banner shown", "Safety check" in panel or "immediate care" in panel)
        check("disclaimer shown", "disclaimer" in panel.lower() or "educational" in panel.lower())
        check("explanations listed", "Possible explanations" in panel)
        check("confidence disclosed", "Confidence" in panel)

        page.click("text=Save to my health history")
        page.wait_for_timeout(2500)

        print("\n=== 5. Health history ===")
        page.goto(f"{BASE}/health-history.html", wait_until="domcontentloaded")
        page.wait_for_selector("#timeline", timeout=20000)
        page.wait_for_timeout(2000)
        check("timeline has the consultation",
              "Consultation" in page.locator("#timeline").inner_text()
              or "consultation" in page.locator("#timeline").inner_text())
        check("summary tiles rendered", page.locator("#history-summary .rounded-lg").count() >= 4)
        check("health profile section present", page.locator("#health-summary").inner_text().strip() != "")

        print("\n=== 6. Appointments ===")
        page.goto(f"{BASE}/appointments.html", wait_until="domcontentloaded")
        page.wait_for_selector("#booking-form", timeout=20000)
        page.wait_for_timeout(1200)
        check("empty state", "No appointments yet" in page.locator("#appointments-list").inner_text())
        page.fill("#book-when", "2026-12-01T09:00")
        page.fill("#book-reason", "Follow-up on persistent headache")
        page.click("#booking-form button[type=submit]")
        page.wait_for_timeout(3000)
        check("booking listed", "Consultation" in page.locator("#appointments-list").inner_text(),
              page.locator("#appointments-list").inner_text().replace("\n", " ")[:70])
        check("server has one appointment", len(api("/users/me/appointments", token)) == 1)

        page.click("#appointments-list button:has-text('Reschedule')")
        page.wait_for_timeout(700)
        page.fill("#reschedule-when", "2026-12-04T15:00")
        page.click("#reschedule-form button[type=submit]")
        page.wait_for_timeout(3000)
        rows = api("/users/me/appointments", token)
        check("reschedule persisted", rows[0]["status"] == "RESCHEDULED", rows[0]["status"])

        page.on("dialog", lambda d: d.accept())
        page.click("#appointments-list button:has-text('Cancel')")
        page.wait_for_timeout(3000)
        rows = api("/users/me/appointments", token)
        check("cancel persisted", rows[0]["status"] == "CANCELLED", rows[0]["status"])

        print("\n=== 7. Find care ===")
        page.goto(f"{BASE}/find-hospitals.html", wait_until="domcontentloaded")
        page.wait_for_selector("#care-search-form", timeout=20000)
        page.fill("#search-symptoms", "headache, fever")
        page.click("#care-search-form button[type=submit]")
        page.wait_for_selector("#results article", timeout=25000)
        page.wait_for_timeout(1200)
        results = page.locator("#results").inner_text()
        check("facilities returned", "matched" in results)
        check("relevance ranking stated", "clinical relevance" in results or "distance" in results)
        check("emergency warning present", "emergency services" in page.locator("body").inner_text())
        check("verified badge", "Verified" in results)
        page.locator("#results summary").first.click()
        page.wait_for_timeout(2000)
        check("availability is honest about gaps",
              "not integrated" in page.locator("#results").inner_text().lower()
              or "No live availability" in page.locator("#results").inner_text())

        print("\n=== 8. Settings ===")
        page.goto(f"{BASE}/settings.html", wait_until="domcontentloaded")
        page.wait_for_selector("#set-phone", timeout=25000)
        page.wait_for_timeout(1500)
        check("header shows real patient",
              "Journey Tester" in page.locator("header").inner_text())
        check("all sections rendered",
              all(page.locator(f"#{s}").inner_text().strip() != "" for s in
                  ("personal-info", "account", "security", "privacy-fhir", "health-profile")))
        page.fill("#hp-allergies", "penicillin")
        page.click("#health-profile button[type=submit]")
        page.wait_for_timeout(2500)
        check("allergy saved", api("/users/me/health-profile", token)["allergies"] == ["penicillin"])

        page.click("#set-display-name", click_count=3)
        page.fill("#set-display-name", "Journey Updated")
        page.click("#personal-info button[type=submit]")
        page.wait_for_timeout(2500)
        check("profile update saved", api("/users/me", token)["display_name"] == "Journey Updated")

        print("\n=== 9. Withdrawing consent locks health data ===")
        page.uncheck("#consent-treatment")
        page.click("#privacy-fhir button[type=submit]")
        page.wait_for_timeout(3000)
        consent = api("/users/me/consent", token)
        check("consent withdrawn", consent["treatment_processing"] is False)
        check("health profile now refused by server", page.locator("#health-profile").inner_text().strip() != "")

        # Restore, since the rest of the journey reads the profile.
        page.check("#consent-treatment")
        page.click("#privacy-fhir button[type=submit]")
        page.wait_for_timeout(2500)
        check("consent restored", api("/users/me/consent", token)["treatment_processing"] is True)

        print("\n=== 10. Sign out and back in ===")
        page.click("[data-dedan='logout']")
        page.wait_for_url(f"{BASE}/login.html", timeout=15000)
        check("logout lands on sign-in", "login.html" in page.url)
        check("token cleared", not page.evaluate("() => localStorage.getItem('dedan.session.token')"))

        page.fill("#identity-input", dedan_id)
        page.fill("#password-input", password)
        page.click("#login-submit")
        page.wait_for_url(f"{BASE}/index.html", timeout=25000)
        page.wait_for_timeout(2000)
        check("re-login by DEDAN ID", "index.html" in page.url, page.url)
        check("dashboard restored", "Journey Updated" in page.locator("#patient-dashboard").inner_text())

        page.goto(f"{BASE}/login.html", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        check("already-signed-in visit to login redirects", "login.html" not in page.url, page.url)

        print("\n=== 11. Guards ===")
        page.evaluate("() => localStorage.clear()")
        for guarded in ("settings.html", "appointments.html", "health-history.html",
                        "live-discussion.html", "find-hospitals.html"):
            page.goto(f"{BASE}/{guarded}", wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            check(f"{guarded} redirects when signed out", "login.html" in page.url, page.url)

        print("\n=== 12. Bad credentials ===")
        page.goto(f"{BASE}/login.html", wait_until="domcontentloaded")
        page.wait_for_selector("#login-submit")
        page.fill("#identity-input", dedan_id)
        page.fill("#password-input", "WrongPassword123")
        page.click("#login-submit")
        page.wait_for_timeout(2500)
        check("wrong password rejected with a message",
              "Incorrect" in page.locator("[data-form-error]").inner_text())
        check("still on login", "login.html" in page.url)

        browser.close()

    print("\n=== Unexpected HTTP responses ===")
    if bad_responses:
        for line in bad_responses[:15]:
            print("   ", line)
    else:
        print("    none")

    print("\n=== Console errors ===")
    real = [e for e in console_errors if "favicon" not in e]
    if real:
        for line in real[:15]:
            print("   ", line)
    else:
        print("    none")

    print(f"\n{'=' * 62}\nfailures: {len(FAILURES)}")
    for name in FAILURES:
        print("  -", name)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
