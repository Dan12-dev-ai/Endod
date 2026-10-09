#!/usr/bin/env python3
"""Validate the static HTML portal in web-portal/.

The portal is plain HTML served as-is (Tailwind via CDN, inline JS), so there is
no bundler and no TypeScript to type-check. What can actually break it is
malformed markup, a dangling internal link, a broken inline script, or an unsafe
DOM sink. This checks exactly those, using the standard library only.

Exit 0 when every page passes, 1 otherwise.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

# Patterns that would be a real defect in a clinical portal.
UNSAFE = {
    "innerHTML assignment": r"\.innerHTML\s*=",
    "eval()": r"\beval\s*\(",
    "document.write()": r"document\.write\s*\(",
    "javascript: URL": r'href\s*=\s*[\'"]javascript:',
    "insecure http:// asset": r'(?:src|href)\s*=\s*[\'"]http://',
    "srcdoc assignment": r"srcdoc\s*=",
    "new Function()": r"new\s+Function\s*\(",
}

PORTAL = "web-portal"


class Balance(HTMLParser):
    """Track tag nesting; report the first mismatch and any unclosed tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"stray </{tag}> at line {self.getpos()[0]}")
            return
        open_tag, line = self.stack[-1]
        if open_tag != tag:
            self.errors.append(
                f"line {self.getpos()[0]}: expected </{open_tag}> "
                f"(opened line {line}) but found </{tag}>"
            )
            return
        self.stack.pop()


def check_js(html: str) -> list[str]:
    """Syntax-check every inline <script> with node, when node is available."""
    if not _have("node"):
        return []
    problems: list[str] = []
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    for index, block in enumerate(blocks):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write(block)
            path = handle.name
        try:
            result = subprocess.run(
                ["node", "--check", path], capture_output=True, text=True
            )
            if result.returncode:
                detail = result.stderr.strip().splitlines()[:1]
                problems.append(f"inline script #{index + 1}: {detail or 'syntax error'}")
        finally:
            os.unlink(path)
    return problems


def _have(program: str) -> bool:
    from shutil import which

    return which(program) is not None


def main() -> int:
    if not os.path.isdir(PORTAL):
        print(f"check-portal: no {PORTAL}/ directory", file=sys.stderr)
        return 1

    pages = sorted(glob.glob(os.path.join(PORTAL, "*.html")))
    if not pages:
        print(f"check-portal: no HTML pages in {PORTAL}/", file=sys.stderr)
        return 1

    names = {os.path.basename(page) for page in pages}
    failures = 0

    for page in pages:
        name = os.path.basename(page)
        with open(page, encoding="utf-8", errors="replace") as handle:
            html = handle.read()
        problems: list[str] = []

        parser = Balance()
        parser.feed(html)
        problems += parser.errors
        problems += [f"unclosed <{tag}> (line {line})" for tag, line in parser.stack]

        if not re.search(r"<title>\s*\S", html):
            problems.append("missing <title>")

        for label, pattern in UNSAFE.items():
            if re.search(pattern, html, re.I):
                problems.append(f"unsafe pattern: {label}")

        dangling = sorted(
            {
                href
                for href in re.findall(r'href="([^"]+)"', html)
                if not href.startswith(("#", "http", "mailto:", "tel:", ""))
                and href not in names
            }
        )
        problems += [f"dangling link: {href}" for href in dangling]

        problems += check_js(html)

        if problems:
            failures += 1
            print(f"FAIL  {name}")
            for problem in problems:
                print(f"        {problem}")
        else:
            print(f"ok    {name}")

    print()
    if failures:
        print(f"check-portal: {failures}/{len(pages)} page(s) failed")
        return 1
    print(f"check-portal: {len(pages)} page(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
