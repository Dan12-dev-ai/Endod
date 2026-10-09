#!/usr/bin/env python3
"""Fail if a page uses a Tailwind class the built stylesheet does not define.

Why this exists
---------------
The portal originally loaded `https://cdn.tailwindcss.com`, which compiles
Tailwind in the browser and happily accepts class names the build-time Tailwind
CLI silently ignores. Two concrete cases bit during the move to a local build:

  * `from-teal/18` -- the CLI only accepts opacity values from Tailwind's scale
    (multiples of five); anything else is dropped without a warning, so the
    ambient gradient glows simply did not render.
  * defining a flat `teal` colour replaced Tailwind's built-in `teal-50..950`
    object, which broke `bg-teal-600` used by the consultation page.

Both fail *visually and quietly*. This turns them into build failures.

The check is deliberately approximate: it looks for each candidate class as a
selector in the output CSS. It is a safety net for dropped utilities, not a
validator, so it only reports classes that look like Tailwind utilities and are
provably absent.

Exit 0 when every page's classes are present, 1 otherwise.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "web-portal"
CSS = ROOT / "assets" / "tailwind.css"

# Prefixes that indicate a Tailwind utility rather than a component class of ours.
UTILITY_PREFIX = re.compile(
    r"^(?:sm|md|lg|xl|2xl|hover|focus|active|disabled|group-hover|peer|"
    r"dark|first|last|odd|even|print|motion-safe|motion-reduce|"
    r"divide|placeholder|file|caret|accent|marker|selection|backdrop)-"
)

# Our own component classes; these are not Tailwind utilities.
# Classes this project defines itself, so they are never Tailwind utilities.
# `nav-item` and `font-display` are component classes set by the pages' own
# inline styles and the settings nav script.
LOCAL = re.compile(
    r"^(?:sr-only|material-symbols-outlined|no-scrollbar|min-h-screen|"
    r"text-balance|text-pretty|tab-numeric|nav-item|font-display)$"
)

# A class token is a candidate if it looks like `prefix-value` where value has
# digits, a slash with an opacity, or a negative sign -- i.e. Tailwind's grammar.
CANDIDATE = re.compile(r"^[a-z0-9-]+(?:/[0-9]{1,3})?$")


def class_attribute_pattern() -> re.Pattern[str]:
    return re.compile(r'class="([^"]+)"')


def collect_classes() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    sources = sorted(ROOT.glob("*.html")) + sorted((ROOT / "assets").glob("*.js"))
    for source in sources:
        text = source.read_text(encoding="utf-8", errors="replace")
        tokens: set[str] = set()
        for group in class_attribute_pattern().findall(text):
            tokens.update(group.split())
        # Single-quoted class names inside the JS builders.
        for group in re.findall(r"class:\s*'([^']+)'", text):
            tokens.update(group.split())
        for group in re.findall(r'class=\\?"([^"\\]+)\\?"', text):
            tokens.update(group.split())
        found[source.name] = {t for t in tokens if t}
    return found


def candidates(tokens: set[str]) -> set[str]:
    """Filter to things that look like Tailwind utilities."""
    out: set[str] = set()
    for token in tokens:
        if LOCAL.match(token):
            continue
        # Strip responsive/state prefixes before judging the base utility.
        bare = token
        parts = token.split("-")
        # Drop leading variant segments, keeping the last 1-2 for inspection.
        if any(p in {
            "sm", "md", "lg", "xl", "2xl", "hover", "focus", "focus-within",
            "active", "disabled", "group", "group-hover", "peer", "dark",
            "first", "last", "odd", "even", "print", "backdrop",
        } for p in parts[:1]):
            bare = "-".join(parts[1:])
        if not CANDIDATE.match(token.replace("[", "").replace("]", "")):
            continue
        if "-" not in bare:
            continue
        out.add(token)
    return out


def main() -> int:
    if not CSS.exists():
        print(f"check-styles: {CSS} not found — run `npm run build` in web-portal/build")
        return 1

    css = CSS.read_text(encoding="utf-8", errors="replace").replace("\\", "")
    per_file = collect_classes()

    failures = 0
    for name, tokens in per_file.items():
        missing = set()
        for token in candidates(tokens):
            base = token
            # `md:flex` -> `flex`; `hover:bg-accent` -> `bg-accent`
            if ":" in base:
                base = base.split(":", 1)[1]
            if base.startswith("peer-checked:") or ":" in base:
                base = base.split(":", 1)[-1]
            if f".{base}" in css:
                continue
            missing.add(token)
        if missing:
            failures += 1
            print(f"FAIL  {name}")
            for token in sorted(missing)[:25]:
                print(f"        not in built CSS: {token}")
            if len(missing) > 25:
                print(f"        ... and {len(missing) - 25} more")

    print()
    if failures:
        print(f"check-styles: {failures} file(s) reference classes the build dropped")
        return 1
    print("check-styles: every referenced utility is present in the build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
