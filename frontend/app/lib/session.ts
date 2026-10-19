"use client";

// Whether the visitor is signed in, for public pages (the landing page) that
// look different for a signed-in patient. Private pages do not need this:
// proxy.ts already sends signed-out visitors to /login.

import { useEffect, useState } from "react";

export type SessionProfile = {
  dedan_user_id: string;
  first_name?: string | null;
  last_name?: string | null;
  display_name?: string | null;
  onboarding_complete?: boolean;
};

export type SessionState =
  | { status: "loading" }
  | { status: "signed-out" }
  | { status: "signed-in"; profile: SessionProfile };

// One request per page load, however many components ask (the header and
// the hero both do). Signing out reloads the page; signing in navigates
// within the app, so it calls forgetSession() to have the next page ask again.
let pending: Promise<SessionState> | null = null;

export function forgetSession(): void {
  pending = null;
}

export function fetchSession(): Promise<SessionState> {
  pending ??= fetch("/api/auth/session", { cache: "no-store" })
    .then(async (response): Promise<SessionState> => {
      const data = await response.json().catch(() => ({}));
      return response.ok && data?.profile
        ? { status: "signed-in", profile: data.profile as SessionProfile }
        : { status: "signed-out" };
    })
    .catch((): SessionState => ({ status: "signed-out" }));
  return pending;
}

export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchSession().then((session) => {
      if (!cancelled) setState(session);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}

/** The name to show for the account: first name, else the display name, else the DEDAN ID. */
export function accountName(profile: SessionProfile): string {
  return profile.first_name?.trim() || profile.display_name?.trim() || profile.dedan_user_id;
}

/** Where "Get started" and the account menu lead a signed-in patient. */
export function homeFor(profile: SessionProfile): string {
  return profile.onboarding_complete ? "/interview" : "/onboarding";
}
