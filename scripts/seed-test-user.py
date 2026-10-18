#!/usr/bin/env python3
"""Seed one fully-onboarded test user for testing the frontend.

The web app's patient journey is:

    signup -> verify OTP -> set password -> onboarding -> interview

This script skips the SMS step (there is no SMS provider configured in
development) and writes the same rows the onboarding screens would, so the
resulting account is indistinguishable from one that came through the UI:

    * identity.create_user      -- account + DEDAN ID + preferences + health profile
    * credentials.set_credential -- password (PBKDF2, per-user salt)
    * identity.update_profile    -- names, city, timezone
    * identity.update_preferences -- onboarding goals
    * identity.update_consent    -- treatment_processing (required before health)
    * identity.update_health_profile -- sex + age_range

Usage (from the repo root):

    DEDAN_DATABASE_URL=sqlite:///./dedan_platform.db \\
    ../.venv/bin/python scripts/seed-test-user.py

Prints the email, password and DEDAN ID on success.
"""

from __future__ import annotations

import os
import sys

# backend-v2 is a package on sys.path only when the app imports it; add it so
# this script can run from anywhere.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend-v2"))

# Default to the same database the backend uses (backend-v2/.env ships
# DEDAN_DATABASE_URL=sqlite:///./dedan_platform.db, relative to backend-v2),
# so `make seed` writes to the same file `make run-backend` reads.
os.environ.setdefault(
    "DEDAN_DATABASE_URL",
    f"sqlite:///{os.path.join(ROOT, 'backend-v2', 'dedan_platform.db')}",
)

from dedan_platform import identity, credentials  # noqa: E402
from dedan_platform.db import create_all  # noqa: E402

EMAIL = os.getenv("SEED_EMAIL", "demo@example.com")
PASSWORD = os.getenv("SEED_PASSWORD", "DemoPass123")
FIRST_NAME = os.getenv("SEED_FIRST_NAME", "Abebe")
LAST_NAME = os.getenv("SEED_LAST_NAME", "Kebede")
PHONE = os.getenv("SEED_PHONE", "+251911234567")  # verified Ethiopian mobile
TIMEZONE = os.getenv("SEED_TIMEZONE", "Africa/Addis_Ababa")
SEX = os.getenv("SEED_SEX", "male")
AGE_RANGE = os.getenv("SEED_AGE_RANGE", "21-40")
GOALS = [g.strip() for g in os.getenv("SEED_GOALS", "symptoms,appointments").split(",") if g.strip()]


def main() -> int:
    create_all()

    try:
        created = identity.create_user(
            display_name=f"{FIRST_NAME} {LAST_NAME}",
            email=EMAIL,
            phone=PHONE,
            phone_verified=True,  # so the number can sign in
            first_name=FIRST_NAME,
            last_name=LAST_NAME,
            locale="en",
            timezone_name=TIMEZONE,
            country_code="ET",
        )
    except identity.EmailInUse:
        # Idempotent: the demo account already exists. Reuse it.
        existing = identity.find_user_by_email(EMAIL)
        if existing is None:
            print(f"email {EMAIL} reported in use but no user found", file=sys.stderr)
            return 1
        user_id = existing.id
        print(f"demo account already exists; reusing {user_id}")
    else:
        user_id = created["internal_user_id"]
        credentials.set_credential(user_id, PASSWORD)
        print(f"created account {user_id} (DEDAN ID {created['dedan_user_id']})")

    # Onboarding steps -- the same calls PATCH /users/me, /preferences,
    # /consent and /health-profile make.
    identity.update_profile(
        user_id,
        {
            "display_name": f"{FIRST_NAME} {LAST_NAME}",
            "first_name": FIRST_NAME,
            "last_name": LAST_NAME,
            "city": "Addis Ababa",
            "timezone": TIMEZONE,
        },
    )
    identity.update_preferences(user_id, {"onboarding_goals": GOALS})
    identity.update_consent(user_id, {"treatment_processing": True})
    identity.update_health_profile(user_id, {"sex": SEX, "age_range": AGE_RANGE})

    payload = identity.get_profile_payload(user_id)
    # update_health_profile with no changes returns the stored health profile,
    # which is the same shape GET /users/me/health-profile returns.
    health = identity.update_health_profile(user_id, {})
    print(f"email:            {payload['email']}")
    print(f"password:         {PASSWORD}")
    print(f"DEDAN ID:         {payload['dedan_user_id']}")
    print(f"phone:            {payload['phone']} (verified: {payload['phone_verified']})")
    print(f"sex:              {health['sex']}")
    print(f"age_range:        {health['age_range']}")
    print(f"onboarding_goals: {payload['preferences']['onboarding_goals']}")
    print(f"consent:          {payload['consent']['treatment_processing']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())