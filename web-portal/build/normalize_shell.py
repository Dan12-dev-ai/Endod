#!/usr/bin/env python3
"""Normalise the signed-in portal pages onto one shared application shell.

Replaces the six hand-written, drifted copies of the app chrome with an
identical skeleton whose contents are rendered at runtime by `shell.js` from the
single navigation config in `nav.js`.

What it changes per page
------------------------
1. `<aside>` -> one canonical responsive drawer (`w-64`, clinical surface token,
   off-canvas below `lg`) containing only the `#dedan-sidebar` mount point.
2. Scrim + hamburger toggle so the drawer is reachable on mobile.
3. Content offset `pl-64`/`pl-60` -> `lg:pl-64`, so the content is not pushed
   off-screen on a phone.
4. Header normalised to the sticky clinical treatment.
5. `assets/nav.js` loaded before `assets/shell.js`.

Idempotent: a page already carrying the canonical aside is skipped.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PAGES = [
    "appointments.html",
    "find-hospitals.html",
    "health-history.html",
    "hospitals.html",
    "live-discussion.html",
    "settings.html",
]

# One shell, verbatim, on every signed-in page.
CANONICAL_ASIDE = (
    '<aside id="dedan-sidebar" aria-label="Main navigation"\n'
    '       class="dedan-sidebar fixed left-0 top-0 z-50 h-screen w-64 -translate-x-full\n'
    '              lg:translate-x-0 bg-surface-container-low flex flex-col\n'
    '              justify-between py-space-md shadow-lg transition-transform\n'
    '              duration-300">\n'
    '      <div id="dedan-sidebar-mount" class="flex flex-col min-h-0 flex-1"></div>\n'
    '    </aside>\n'
    '    <div id="dedan-nav-overlay" aria-hidden="true"\n'
    '         class="hidden fixed inset-0 z-40 bg-primary/60 lg:hidden"></div>'
)

CANONICAL_HEADER = (
    '<header class="sticky top-0 z-30 h-16 bg-surface-container-low\n'
    '               border-b border-outline-variant/30 px-space-md lg:px-space-xl\n'
    '               flex items-center gap-space-sm shadow-panel">'
)

TOGGLE_BUTTON = (
    '<button type="button" data-dedan="nav-toggle"\n'
    '                    aria-expanded="false" aria-controls="dedan-sidebar"\n'
    '                    aria-label="Open navigation"\n'
    '                    class="lg:hidden -ml-1 p-2 rounded-lg text-on-surface-variant\n'
    '                           hover:bg-surface-container focus-visible:outline-none\n'
    '                           focus-visible:ring-2 focus-visible:ring-secondary">\n'
    '          <span class="material-symbols-outlined text-[22px]" aria-hidden="true">menu</span>\n'
    '        </button>'
)


def patch(path: Path) -> str:
    src = path.read_text()
    original = src

    if 'id="dedan-sidebar"' in src:
        return "already canonical"

    # 1. Sidebar + scrim.
    src, n = re.subn(
        r"<aside\b[^>]*>.*?</aside>",
        CANONICAL_ASIDE.strip(),
        src,
        count=1,
        flags=re.S,
    )
    if n != 1:
        return "FAIL: no <aside> found"

    # 2. Content offset becomes responsive. The 15rem copy (live-discussion) and
    #    the 16rem copy both collapse to nothing below `lg`.
    src, n_offset = re.subn(
        r'class="(.*?)\bpl-6[04]\b(.*?)"',
        lambda m: f'class="{m.group(1).rstrip()} lg:pl-64 {" ".join(m.group(2).split())}"'.rstrip(),
        src,
        count=1,
    )

    # 3. Header: normalise the two competing treatments to the sticky one.
    src, n_header = re.subn(r"<header\b[^>]*>", CANONICAL_HEADER, src, count=1)

    # 4. Hamburger, first child of the header.
    src, n_toggle = re.subn(
        r"(<header\b[^>]*>)",
        lambda m: m.group(1) + "\n        " + TOGGLE_BUTTON,
        src,
        count=1,
    )

    # 5. Navigation config must load before the shell that consumes it.
    if "assets/nav.js" not in src:
        src, n_nav = re.subn(
            r'(<script src="assets/shell\.js"></script>)',
            '<script src="assets/nav.js"></script>\n\\1',
            src,
            count=1,
        )
    else:
        n_nav = 1

    # The mount point the shell renders into.
    src = src.replace('id="dedan-sidebar-mount"', 'id="dedan-sidebar-mount"')

    if src == original:
        return "FAIL: no changes applied"

    path.write_text(src)
    return (
        f"ok (aside=1 offset={n_offset} header={n_header} "
        f"toggle={n_toggle} nav={n_nav})"
    )


def main() -> int:
    failures = 0
    for name in PAGES:
        path = Path(name)
        if not path.exists():
            print(f"{name:24} MISSING")
            failures += 1
            continue
        result = patch(path)
        print(f"{name:24} {result}")
        if result.startswith("FAIL"):
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())