# Archived Stitch exports

Screens kept for reference. **Not served, not linked, not built.**

## hospitals.html

A Google Stitch export that presents a hospital detail page with fabricated
content: a named clinician ("Dr. Sarah Aris, MD") and facility ("St. Jude
Cardiovascular") presented as real, and 261 raw Tailwind colour utilities
instead of the product's design tokens.

Two things disqualified it:

1. **It was wired to the wrong script.** It loaded `assets/hospitals.js`, which
   is the *appointments* logic — its first API call is
   `GET /users/me/appointments`. The page had no hospital functionality at all.
2. **A real page already covers the feature.** `find-hospitals.html` is backed
   by `POST /users/me/care/facilities`, which ranks the real facility directory.
   `hospitals.html` was absent from the backend's `PORTAL_PAGES` allowlist, so it
   was never registered with the API tier either.

Keeping it reachable meant advertising a clinician who does not exist, so the
sidebar's "Hospitals" entry now resolves to `find-hospitals.html` and this file
ships nothing.
