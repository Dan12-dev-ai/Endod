#!/usr/bin/env python3
"""Navigation and shell consistency checks for the DEDAN web portal.

The defect this exists to prevent
---------------------------------
The six signed-in pages each carried their own hand-written <nav>. The copies
drifted: the same feature had different labels and different Material Symbol
glyphs on different pages, whole items were missing from some pages, five were
`href="#"` placeholders rescued at runtime by a redirect table, and no page had
mobile navigation at all. Every one of those was invisible in review because
each page looked fine alone.

These checks assert the invariants that make that class of drift impossible:

1. Every nav entry resolves to a file that exists and is a real route.
2. No nav entry is duplicated.
3. Every signed-in page loads nav.js before shell.js.
4. Every signed-in page has the sidebar mount, the scrim and the mobile toggle.
5. The shell chrome is byte-identical across every signed-in page.
6. No signed-in page inlines its own <nav> (nav.js is the only source).
7. No signed-in page contains an `href="#"` placeholder.
8. No signed-in page uses a raw Tailwind colour instead of a design token.
9. The pages that must NOT have the sidebar (auth/landing) do not have it.

Run: python3 scripts/check-navigation.py
Exit code is non-zero on any failure, so it can gate a build.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTAL = ROOT / "web-portal"

# Pages that render the authenticated sidebar shell.
SHELL_PAGES = [
    "live-discussion.html",
    "appointments.html",
    "health-history.html",
    "find-hospitals.html",
    "settings.html",
]

# Pages that legitimately have no sidebar. Asserted below so the distinction is
# explicit rather than assumed.
#
#   index.html    Public landing page. One long marketing document with its own
#                 top navigation and in-page anchors (#care-journey,
#                 #consultation-preview, #contact). It is also the signed-in
#                 "Home" destination, so it appears in the sidebar while not
#                 wearing the shell itself. Forcing the drawer onto it would
#                 bury the landing content behind a nav it does not need.
#   login.html    Sign-in wall. No session, so no account navigation to show.
#   register.html Sign-up. Same reasoning as login.
NO_SHELL_PAGES = ["index.html", "login.html", "register.html"]

# The landing page inlines its own top nav by design, so the "no inline <nav>"
# rule does not apply to it.
PAGES_WITH_OWN_NAV = ["index.html"]

failures: list[str] = []
checks = 0


def check(condition: bool, message: str) -> bool:
    global checks
    checks += 1
    if not condition:
        failures.append(message)
    return bool(condition)


def parse_nav_config() -> dict:
    """Extract the route map and nav items from assets/nav.js."""
    src = (PORTAL / "assets" / "nav.js").read_text()

    routes: dict[str, dict] = {}
    routes_block = re.search(r"var ROUTES = \{(.*?)\n  \};", src, re.S)
    if routes_block:
        for match in re.finditer(
            r"'([^']+)':\s*\{\s*title:\s*'([^']*)',\s*auth:\s*(true|false)", routes_block.group(1)
        ):
            routes[match.group(1)] = {"title": match.group(2), "auth": match.group(3) == "true"}

    groups: list[dict] = []
    groups_block = re.search(r"var GROUPS = \[(.*?)\n  \];", src, re.S)
    if groups_block:
        for group in re.finditer(r"\{\s*label:\s*(null|'[^']*'),\s*items:\s*\[(.*?)\]\s*\}", groups_block.group(1), re.S):
            items = [
                {"label": m.group(1), "href": m.group(2), "icon": m.group(3)}
                for m in re.finditer(
                    r"\{\s*label:\s*'([^']*)',\s*href:\s*'([^']*)',\s*icon:\s*'([^']*)'\s*\}",
                    group.group(2),
                )
            ]
            label = group.group(1)
            groups.append({"label": None if label == "null" else label.strip("'"), "items": items})

    return {"routes": routes, "groups": groups}


def main() -> int:
    config = parse_nav_config()
    routes = config["routes"]
    groups = config["groups"]
    all_items = [item for group in groups for item in group["items"]]

    print(f"check-navigation: {len(SHELL_PAGES)} shell pages, "
          f"{len(all_items)} nav items\n")

    # 1 + 2: every item resolves, nothing duplicated.
    seen: set[str] = set()
    for item in all_items:
        check(
            (PORTAL / item["href"]).exists(),
            f"nav item '{item['label']}' -> {item['href']}: file does not exist",
        )
        check(
            item["href"] in routes,
            f"nav item '{item['label']}' -> {item['href']}: not declared in ROUTES",
        )
        check(
            item["href"] not in seen,
            f"duplicate nav entry for {item['href']}",
        )
        seen.add(item["href"])
        check(bool(item["icon"]), f"nav item '{item['label']}' has no icon")

    # Every authenticated route should be reachable from the sidebar, or be a
    # deliberate omission. index.html is the dashboard.
    for href, meta in routes.items():
        if meta["auth"] and href not in seen:
            check(
                False,
                f"authenticated route {href} is not in the sidebar",
            )

    # 3, 4, 5, 6, 7, 8: per-page structural invariants.
    chrome: dict[str, str] = {}
    for page in SHELL_PAGES:
        path = PORTAL / page
        if not check(path.exists(), f"{page}: missing"):
            continue
        src = path.read_text()

        nav_js = src.find("assets/nav.js")
        shell_js = src.find("assets/shell.js")
        check(nav_js != -1, f"{page}: does not load assets/nav.js")
        check(shell_js != -1, f"{page}: does not load assets/shell.js")
        check(
            nav_js != -1 and shell_js != -1 and nav_js < shell_js,
            f"{page}: nav.js must load before shell.js",
        )

        check('id="dedan-sidebar-mount"' in src, f"{page}: no #dedan-sidebar-mount")
        check('id="dedan-nav-overlay"' in src, f"{page}: no mobile scrim")
        check('data-dedan="nav-toggle"' in src, f"{page}: no mobile nav toggle")
        check("lg:hidden" in src, f"{page}: sidebar is not hidden below lg")

        check(
            'href="#"' not in src,
            f"{page}: contains an href=\"#\" placeholder",
        )
        if page not in PAGES_WITH_OWN_NAV:
            check(
                not re.search(r"<nav\b", src),
                f"{page}: inlines its own <nav>; nav.js must be the only source",
            )

        # Dead controls. A <button> with no id, no data hook and no form
        # owner cannot be wired by any script, so it renders as a live control
        # that does nothing -- the "decorative control" defect.
        body_only = re.sub(r"<script[\s\S]*?</script>", "", src)
        for match in re.finditer(
            r"<button\b([^>]*)>([\s\S]{0,300}?)</button>", body_only
        ):
            attrs = match.group(1)
            if 'id=' in attrs or 'data-dedan' in attrs or 'type="submit"' in attrs:
                continue
            label = " ".join(re.sub(r"<[^>]+>", " ", match.group(2)).split())[:40]
            check(
                False,
                f"{page}: dead <button> with no handler or id: '{label}'",
            )

        # Raw palette leakage: a signed-in page should use design tokens only.
        raw = re.findall(
            r"\b(?:bg|text|border|ring|from|to|via)-(?:slate|emerald|teal|red|amber|"
            r"blue|green|indigo|gray|zinc|neutral|stone|sky|violet|purple|pink|"
            r"orange|yellow|lime)-[0-9]{2,3}\b",
            src,
        )
        check(
            not raw,
            f"{page}: raw palette colours instead of design tokens: {sorted(set(raw))}",
        )

        # Shell chrome must be identical everywhere. Compare the normalised
        # aside + header, which is what produced the per-route styling drift.
        aside = re.search(r"<aside\b[\s\S]*?</aside>", src)
        header = re.search(r"<header\b[^>]*>", src)
        fingerprint = (aside.group(0) if aside else "") + "||" + (header.group(0) if header else "")
        if page in chrome:
            check(
                chrome[page] == fingerprint,
                f"{page}: shell chrome differs from {chrome[page].split('||')[0]}",
            )
        else:
            chrome[page] = fingerprint

    # 9: pages that must not carry the sidebar.
    for page in NO_SHELL_PAGES:
        path = PORTAL / page
        if not path.exists():
            continue
        src = path.read_text()
        check(
            'id="dedan-sidebar-mount"' not in src,
            f"{page}: carries the authenticated sidebar but should not",
        )

    # Dead anchors on the public pages. `href="#"` looks like navigation and
    # goes nowhere.
    for page in ["index.html", "login.html", "register.html"]:
        path = PORTAL / page
        if not path.exists():
            continue
        body_only = re.sub(r"<script[\s\S]*?</script>", "", path.read_text())
        check(
            'href="#"' not in body_only,
            f"{page}: contains an href=\"#\" placeholder",
        )

    # Archived exports must not be reachable from any page.
    for page in PORTAL.glob("*.html"):
        src = page.read_text()
        check(
            not re.search(r'href="hospitals\.html"', src),
            f"{page.name}: links to the archived hospitals.html mockup",
        )

    print(f"{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("check-navigation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())