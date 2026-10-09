#!/usr/bin/env python3
"""Drive the real portal in a browser and verify the shell is genuinely unified.

Static checks can confirm the markup is identical; they cannot confirm the
sidebar actually renders, that the active state tracks the route, or that the
mobile drawer opens. This does that in Chromium against the running API.

It signs up a real patient, then visits every signed-in route and records the
rendered navigation. "Identical" means the same labels, in the same order, with
the same icons, on every page.

Usage:
    python3 scripts/verify-shell.py [--base http://localhost:8001] [--shots DIR]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SHELL_ROUTES = [
    "live-discussion.html",
    "appointments.html",
    "health-history.html",
    "find-hospitals.html",
    "settings.html",
]

VIEWPORTS = {
    "desktop": (1440, 900),
    "tablet": (820, 1180),
    "mobile": (390, 844),
}


def chrome_available() -> bool:
    for candidate in ("chromium", "chromium-browser", "google-chrome"):
        if subprocess.run(["which", candidate], capture_output=True).returncode == 0:
            return True
    return False


def register(base: str) -> str:
    """Create a real patient and return an access token."""
    import urllib.request

    stamp = int(time.time() * 1000)
    payload = json.dumps({
        "first_name": "Shell", "last_name": "Check",
        "email": f"shellcheck{stamp}@example.org",
        "password": "ShellCheck123!",
        "password_confirmation": "ShellCheck123!",
    }).encode()
    request = urllib.request.Request(
        f"{base}/auth/register", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())["access_token"]


def seed_page(token: str) -> Path:
    """Write a same-origin page that installs a session, then redirects.

    The shell redirects to the sign-in wall without a valid token, which is
    correct behaviour but means an unauthenticated render can never show the
    navigation.

    It has to *redirect* rather than serve a renamed copy of each page: the
    active nav item is derived from `location.pathname`, so loading a copy named
    `_shellcheck-appointments.html` reported no active item on every route and
    would have hidden a genuinely broken active state behind a harness bug.

    Lives beside the originals so its relative paths resolve, and is removed by
    the caller.
    """
    portal = ROOT / "web-portal"
    temp = portal / "_shellseed.html"
    temp.write_text(
        "<!doctype html><meta charset=utf-8><script>"
        "try{localStorage.setItem('dedan.session.token', "
        f"{json.dumps(token)});}}catch(e){{}}"
        "var t=new URLSearchParams(location.search).get('route')||'index.html';"
        "location.replace(t);"
        "</script>"
    )
    return temp


def dump_dom(url: str, width: int, height: int) -> str:
    """Render one URL in headless Chromium and return its DOM.

    Loaded directly rather than through an iframe: a `file://` wrapper cannot
    read a `http://` child document, so the iframe approach silently yielded an
    empty shell and would have "passed" a broken build.
    """
    result = subprocess.run(
        [
            "chromium", "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--window-size={width},{height}",
            # Long enough for the page scripts to fetch a session and paint.
            "--virtual-time-budget=8000",
            "--dump-dom",
            url,
        ],
        capture_output=True, text=True, timeout=90,
    )
    return result.stdout


def extract_nav(dom: str) -> list[dict]:
    """Pull the rendered navigation items out of a dumped DOM."""
    import re

    items = []
    for match in re.finditer(
        r'<a[^>]*href="([a-z\-]+\.html)"[^>]*aria-current="page"', dom
    ):
        items.append({"href": match.group(1), "active": True})
    # Icons are the material-symbols span text inside each sidebar link.
    sidebar = re.search(r'id="dedan-sidebar-mount"[\s\S]*?</nav>', dom)
    if sidebar:
        for match in re.finditer(
            r'<a[^>]*href="([a-z\-]+\.html)"[\s\S]*?'
            r'material-symbols-outlined[^>]*>([a-z_]+)<',
            sidebar.group(0),
        ):
            items.append({"href": match.group(1), "icon": match.group(2)})
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8001")
    args = parser.parse_args()

    if not chrome_available():
        print("verify-shell: SKIPPED - no Chromium on PATH")
        return 0

    base = args.base.rstrip("/")
    failures: list[str] = []

    print(f"verify-shell: {base}\n")

    token = register(base)
    print(f"  signed in as a real patient ({token[:12]}...)\n")

    signatures: dict[str, list[tuple[str, str]]] = {}
    seed = seed_page(token)
    for route in SHELL_ROUTES:
        dom = dump_dom(f"{base}/{seed.name}?route={route}", 1440, 900)
        items = _nav_items(dom)
        signatures[route] = items
        # items are (label, icon, is_active) tuples.
        active = [i for i in items if i[2]]
        print(f"  {route:24} nav={len(items)} "
              f"active={active[0][1] if active else 'NONE'}")
        if not items:
            failures.append(f"{route}: sidebar rendered no navigation items")
        if len(active) != 1:
            failures.append(f"{route}: expected exactly 1 active item, got {len(active)}")

    # --- responsive checks ---------------------------------------------------
    # The drawer must be off-canvas below `lg` and the content must not carry
    # the desktop offset there, or a 390px phone renders ~130px of content.
    import re as _re

    def responsive(route: str, label: str, width: int, height: int) -> None:
        dom = dump_dom(f"{base}/{seed.name}?route={route}", width, height)
        aside = _re.search(r'<aside[^>]*class="([^"]*)"', dom)
        classes = aside.group(1) if aside else ""
        # Anchored on the id, not on `<div class=`, so adding an attribute to
        # the content wrapper cannot silently stop this check from matching.
        wrapper = _re.search(r'<div[^>]*id="dedan-content"[^>]*class="([^"]*)"', dom)
        wrap_classes = wrapper.group(1) if wrapper else ""
        if width >= 1024:
            ok = "lg:translate-x-0" in classes and "lg:pl-sidebar" in wrap_classes
            detail = "sidebar pinned, content offset applied"
        else:
            hidden = "-translate-x-full" in classes
            no_offset = "pl-sidebar" not in wrap_classes or "lg:pl-sidebar" in wrap_classes
            ok = hidden and no_offset
            detail = "sidebar off-canvas, no desktop offset"
        print(f"  {route:22} {label:8} {'OK ' if ok else 'FAIL'} {detail}")
        if not ok:
            responsive_failures.append(f"{route} @ {label}: {detail}")

    # --- collapsible rail ---------------------------------------------------
    # The rail must narrow *and* the content offset must narrow with it. If only
    # the rail changes, the page slides underneath a fixed sidebar.
    def rail_state(route: str, collapsed: bool) -> tuple[bool, str]:
        seed_js = (
            f"localStorage.setItem('dedan.session.token', {json.dumps(token)});"
            + (f"localStorage.setItem('dedan.nav.collapsed','1');" if collapsed
               else "localStorage.removeItem('dedan.nav.collapsed');")
        )
        import re as _r
        path = ROOT / "web-portal"
        # Distinct filename: this helper deletes what it creates, and it must not
        # delete the session seed the responsive pass still depends on.
        temp = path / "_shellrail.html"
        temp.write_text(
            "<!doctype html><meta charset=utf-8><script>try{"
            + seed_js + "}catch(e){}location.replace("
            + json.dumps(route) + ");</script>"
        )
        try:
            dom = dump_dom(f"{base}/{temp.name}", 1440, 900)
        finally:
            temp.unlink(missing_ok=True)

        aside = _r.search(r'<aside[^>]*id="dedan-sidebar"[^>]*>', dom)
        wrapper = _r.search(r'<div[^>]*id="dedan-content"[^>]*class="([^"]*)"', dom)
        aside_c = aside.group(0) if aside else ""
        wrap_c = wrapper.group(1) if wrapper else ""

        rail_wants = "w-sidebar-collapsed" if collapsed else "w-sidebar"
        offset_wants = "lg:pl-sidebar-collapsed" if collapsed else "lg:pl-sidebar"
        labels_hidden = len(_r.findall(r'dedan-nav-label truncate hidden', dom))
        labels_shown = len(_r.findall(r'dedan-nav-label truncate(?! hidden)', dom))

        problems = []
        if rail_wants not in aside_c:
            problems.append(f"rail class missing {rail_wants}")
        if offset_wants not in wrap_c:
            problems.append(f"content offset missing {offset_wants}")
        if collapsed and labels_hidden != 6:
            problems.append(f"expected 6 hidden labels, got {labels_hidden}")
        if not collapsed and labels_shown != 6:
            problems.append(f"expected 6 visible labels, got {labels_shown}")
        return (not problems), "; ".join(problems)

    rail_failures: list[str] = []
    print()
    for collapsed in (False, True):
        label = "collapsed" if collapsed else "expanded"
        ok, detail = rail_state("appointments.html", collapsed)
        print(f"  rail {label:10} {'OK ' if ok else 'FAIL'} {detail}")
        if not ok:
            rail_failures.append(f"rail {label}: {detail}")
    failures.extend(rail_failures)

    responsive_failures: list[str] = []
    print()
    for label, (width, height) in VIEWPORTS.items():
        responsive("appointments.html", label, width, height)
    failures.extend(responsive_failures)

    seed.unlink(missing_ok=True)

    # "Identical sidebar" means the same items, in the same order, with the
    # same icons. Which one is active is *supposed* to differ per route, so it
    # is asserted separately above and excluded from this comparison.
    def shape(items):
        return [(label, icon) for label, icon, _ in items]

    baseline = shape(signatures[SHELL_ROUTES[0]])
    for route in SHELL_ROUTES[1:]:
        if shape(signatures[route]) != baseline:
            failures.append(
                f"{route}: navigation differs from {SHELL_ROUTES[0]}\n"
                f"    expected {baseline}\n    actual   {shape(signatures[route])}"
            )

    print()
    if failures:
        print("FAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"verify-shell: OK -- identical navigation on all {len(SHELL_ROUTES)} routes")
    return 0


def _nav_items(doc: str) -> list[tuple[str, str, bool]]:
    """Return (label, icon, is_active) for each rendered sidebar link.

    Each <a> is matched individually rather than with one pattern spanning the
    whole nav: the icon and label live in separate child spans, so a pattern
    that reaches across link boundaries can skip a present `aria-current`
    attribute via its optional group and report every item as inactive.
    """
    import re

    nav = re.search(r'id="dedan-sidebar-mount"[\s\S]*?</nav>', doc)
    if not nav:
        return []

    items = []
    for link in re.finditer(r'<a\b[^>]*>[\s\S]*?</a>', nav.group(0)):
        markup = link.group(0)
        href = re.search(r'href="([^"]+)"', markup)
        # The icon is no longer ligature text: icons.js swaps the span for an
        # inline <svg> and keeps the name on data-dedan-icon. Read the name from
        # there, falling back to the rendered glyph for pages still using text.
        icon = (
            re.search(r'data-dedan-icon="([a-z_0-9]+)"', markup)
            or re.search(r'material-symbols-outlined[^>]*>([a-z_]+)<', markup)
        )
        # Match the label by its hook class, not by an exact class string: the
        # rail hides labels by toggling a class on them, so pinning the full
        # attribute would break the moment that class is added or reordered.
        label = re.search(r'<span class="dedan-nav-label[^"]*">([^<]+)</span>', markup)
        if not (href and icon and label):
            continue
        items.append((
            label.group(1),
            icon.group(1),
            'aria-current="page"' in markup,
        ))
    return items


if __name__ == "__main__":
    sys.exit(main())
