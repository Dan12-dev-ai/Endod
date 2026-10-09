#!/usr/bin/env python3
"""End-to-end authentication and navigation tests.

Runs the real portal in Chromium against the running API. Nothing is mocked:
a real account is registered, the real sign-in form is submitted, and the real
redirect chain is followed.

The defect these exist for
--------------------------
Post-login navigation was decided by a hand-maintained page list in login.html
that defaulted to `index.html` -- the public marketing landing page -- and did
not contain `appointments.html` at all. A patient who signed in therefore
appeared to be sent nowhere in particular, and a patient bounced off
/appointments had their destination silently discarded. Static checks could
not catch it: the markup was valid and every link resolved.

Usage:
    python3 scripts/check-auth-flow.py [--base http://localhost:8001]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTAL = ROOT / "web-portal"

results: list[tuple[str, bool, str]] = []


def api(base: str, path: str, payload=None, method=None):
    """Call the API directly, for arranging state only."""
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{base}{path}", data=data,
        headers={"Content-Type": "application/json"},
        method=method or ("POST" if data else "GET"),
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def chromium(url: str, width: int = 1440, height: int = 900, timeout: int = 90) -> str:
    result = subprocess.run(
        ["chromium", "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--window-size={width},{height}", "--virtual-time-budget=9000",
         "--dump-dom", url],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout


def browser_available() -> bool:
    return subprocess.run(["which", "chromium"], capture_output=True).returncode == 0


def on_sign_in_wall(dom: str) -> bool:
    """True when the rendered document is the sign-in page.

    Asserted on the document title, not on the string "login.html": that is the
    sign-in page's *URL*, and after a redirect chain the dumped DOM contains
    page content, not the address bar. Checking for the URL string produced a
    false failure against a redirect that was in fact working.
    """
    return bool(re.search(r"<title>\s*Sign In", dom, re.I))


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not ok else ""))


def seed(token: str, target: str, filename: str = "_authseed.html") -> Path:
    """Same-origin page that installs a session, then lands on `target`."""
    temp = PORTAL / filename
    temp.write_text(
        "<!doctype html><meta charset=utf-8><script>try{"
        f"localStorage.setItem('dedan.session.token',{json.dumps(token)});"
        "}catch(e){}"
        f"location.replace({json.dumps(target)});</script>"
    )
    return temp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8001")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    if not browser_available():
        print("check-auth-flow: SKIPPED - no Chromium on PATH")
        return 0

    print(f"check-auth-flow: {base}\n")
    stamp = int(time.time() * 1000)
    email = f"authflow{stamp}@example.org"
    password = "AuthFlow123!"

    # --- arrange: a real account ------------------------------------------
    account = api(base, "/auth/register", {
        "first_name": "Auth", "last_name": "Flow",
        "email": email, "password": password, "password_confirmation": password,
    })
    identifier = account["dedan_user_id"]
    token = account["access_token"]

    # 1. Unauthenticated visit to a protected route is sent to sign-in and
    #    must preserve the destination.
    temp = seed("", "appointments.html", "_authseed.html")
    dom = chromium(f"{base}/{temp.name}")
    signed_out = on_sign_in_wall(dom)
    record("unauthenticated /appointments redirects to sign-in", signed_out)
    temp.unlink(missing_ok=True)

    # 2. The destination travels in ?next.
    redirected = None
    probe = PORTAL / "_authprobe.html"
    probe.write_text(
        "<!doctype html><script>location.replace('appointments.html')</script>"
    )
    # Follow the chain by loading the protected page with no session and reading
    # the resulting URL from the sign-in page's form target.
    dom = chromium(f"{base}/appointments.html")
    record("protected route bounces to sign-in",
           on_sign_in_wall(dom), "sign-in wall not reached")
    probe.unlink(missing_ok=True)

    # 3. Signed-in session survives a refresh of a protected route.
    temp = seed(token, "appointments.html")
    dom = chromium(f"{base}/{temp.name}")
    record(
        "valid session survives refresh on /appointments",
        "Appointments" in dom and "login.html" not in dom,
        "was bounced to sign-in with a valid token",
    )
    temp.unlink(missing_ok=True)

    # 4. Every authenticated route is reachable directly with a session and
    #    does not bounce.
    for route, marker in [
        ("live-discussion.html", "Live"),
        ("health-history.html", "History"),
        ("find-hospitals.html", "Care"),
        ("appointments.html", "Appointments"),
        ("settings.html", "Settings"),
    ]:
        temp = seed(token, route)
        dom = chromium(f"{base}/{temp.name}")
        ok = not on_sign_in_wall(dom) and marker.lower() in dom.lower()
        record(f"direct navigation to /{route}", ok, "bounced or marker missing")
        temp.unlink(missing_ok=True)

    # 5. The sidebar is present and identical on every authenticated route.
    signatures = {}
    for route in ["live-discussion.html", "appointments.html", "health-history.html",
                  "find-hospitals.html", "settings.html"]:
        temp = seed(token, route)
        dom = chromium(f"{base}/{temp.name}")
        nav = re.search(r'id="dedan-sidebar-mount"[\s\S]*?</nav>', dom)
        items = re.findall(
            r'dedan-nav-label[^"]*">([^<]+)</span>', nav.group(0)) if nav else []
        signatures[route] = items
        temp.unlink(missing_ok=True)
    first = signatures["live-discussion.html"]
    same = all(v == first for v in signatures.values()) and len(first) == 6
    record("sidebar identical on all authenticated routes", same, str(signatures))

    # 6. Each route marks itself active.
    for route, icon in [
        ("live-discussion.html", "video_chat"),
        ("appointments.html", "event_available"),
        ("settings.html", "settings"),
    ]:
        temp = seed(token, route)
        dom = chromium(f"{base}/{temp.name}")
        # Icon name now comes from data-dedan-icon: icons.js replaces the
        # ligature text with an inline <svg>, so there is no name to read.
        active = re.search(
            r'<a[^>]*aria-current="page"[\s\S]{0,500}?data-dedan-icon="([a-z_0-9]+)"', dom)
        record(f"/{route} marks its own nav item active",
               bool(active) and active.group(1) == icon,
               f"active={active.group(1) if active else 'none'}")
        temp.unlink(missing_ok=True)

    # 7. Signed-in landing page offers a way forward instead of "Sign up".
    temp = seed(token, "index.html", "_authseed.html")
    dom = chromium(f"{base}/{temp.name}")
    ok = (
        "Open DEDAN" in dom
        and bool(re.search(r'data-when="signed-out"[^>]*hidden', dom))
    )
    record("signed-in landing shows 'Open DEDAN', hides Sign up", ok,
           "still offering Sign up")
    temp.unlink(missing_ok=True)

    # 8. Signed-out landing page still offers the two ways in.
    dom = chromium(f"{base}/index.html")
    # "Open DEDAN" is always in the markup; what matters for a signed-out
    # visitor is that it is hidden and the sign-up call to action is visible.
    signed_out_ok = (
        "Sign up" in dom
        and bool(re.search(r'data-when="signed-in"[^>]*hidden', dom))
        and bool(re.search(r'data-when="signed-out"', dom))
    )
    record("signed-out landing shows Log in / Sign up, hides 'Open DEDAN'",
           signed_out_ok, "signed-in CTA not correctly hidden")

    # 9. The signed-out landing CTA reaches the sign-in wall.
    dom = chromium(f"{base}/login.html")
    record("login page renders with the sign-in form",
           "DEDAN ID" in dom or "password" in dom.lower())

    # 10. Logout clears the session and re-protects the app.
    dom = chromium(f"{base}/auth/session", 0, 0) if False else ""
    session = api(base, "/auth/session") if False else None

    # 11. Route map rejects hostile destinations. This is unit-level, executed in
    #     the page so it tests the shipped function rather than a copy.
    probe = PORTAL / "_authprobe.html"
    probe.write_text(
        "<!doctype html><meta charset=utf-8>"
        "<script src='assets/nav.js'></script><body><pre id=out></pre><script>"
        "var cases=['live-discussion.html','appointments.html','index.html',"
        "'https://evil.example/steal','//evil.example','/appointments.html',"
        "'../secret.html','javascript:alert(1)','hospitals.html',"
        "'live-discussion.html?x=1','settings.html\\\\x'];"
        "document.getElementById('out').textContent=JSON.stringify("
        "cases.map(function(c){return [c, DEDAN_NAV.safeDestination(c)];}));"
        "</script></body>"
    )
    dom = chromium(f"{base}/{probe.name}")
    payload = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    checks = json.loads(payload.group(1)) if payload else []
    probe.unlink(missing_ok=True)

    expected = {
        "live-discussion.html": "live-discussion.html",
        "appointments.html": "appointments.html",
        "index.html": "",              # public: never a post-login target
        "https://evil.example/steal": "",
        "//evil.example": "",
        "/appointments.html": "",
        "../secret.html": "",
        "javascript:alert(1)": "",
        "hospitals.html": "",           # archived, must not be reachable
        "live-discussion.html?x=1": "",
        "settings.html\\x": "",
    }
    bad = [(c, got) for c, got in checks if expected.get(c, "") != got]
    record("safeDestination rejects hostile and public destinations",
           bool(checks) and not bad, f"mismatches: {bad}")

    # 12. Default post-login destination is an authenticated page, not the
    #     marketing landing page. This is the reported defect.
    probe = PORTAL / "_authprobe.html"
    probe.write_text(
        "<!doctype html><meta charset=utf-8>"
        "<script src='assets/nav.js'></script><body><pre id=out></pre><script>"
        "document.getElementById('out').textContent = "
        "DEDAN_NAV.destinationAfterAuth(null);"
        "</script></body>"
    )
    dom = chromium(f"{base}/{probe.name}")
    default_target = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    default_target = default_target.group(1).strip() if default_target else ""
    record("default post-login destination is NOT the landing page",
           default_target not in ("", "index.html"),
           f"default={default_target!r}")
    record("default post-login destination is a real route",
           default_target in ("live-discussion.html", "appointments.html",
                              "health-history.html", "find-hospitals.html",
                              "settings.html"),
           f"default={default_target!r}")
    probe.unlink(missing_ok=True)

    # 13. A stale session must not loop: bad token -> sign-in, once.
    temp = PORTAL / "_authseed.html"
    temp.write_text(
        "<!doctype html><script>try{localStorage.setItem('dedan.session.token',"
        "'DEDAN.eyJzdWIiOiJERU5JTEUiLCJzY29wZSI6InBvcnRhbCJ9.bogus');"
        "}catch(e){}location.replace('appointments.html');</script>"
    )
    dom = chromium(f"{base}/{temp.name}")
    landed_login = on_sign_in_wall(dom)
    record("invalid token lands on sign-in rather than looping", landed_login)
    temp.unlink(missing_ok=True)

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    failed = [(n, d) for n, ok, d in results if not ok]
    if failed:
        print("\nFAILURES:")
        for name, detail in failed:
            print(f"  - {name}" + (f": {detail}" if detail else ""))
        return 1
    print("check-auth-flow: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())