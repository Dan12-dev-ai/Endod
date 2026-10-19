import { NextRequest, NextResponse } from "next/server";
import { callBackend, clearSessionCookie, SESSION_COOKIE } from "@/app/lib/server/backend";

// Sends each visitor to the right place before a page renders:
//
// - signed out, on a private page          -> /login (and back afterwards)
// - signed in, on /login or /signup        -> the dashboard (or onboarding)
// - signed in, onboarding not finished     -> /onboarding
// - signed in, onboarding finished, on it  -> the dashboard
//
// The backend still checks the session on every API call, so this is about
// where people land, not the security boundary. A session the backend no
// longer accepts is cleared here, so a stale cookie can never bounce a
// visitor between /login and the dashboard.

const DASHBOARD = "/interview";
const ONBOARDING = "/onboarding";
/** Pages only for signed-out visitors. */
const AUTH_PAGES = ["/login", "/signup"];

type Session = "valid" | "invalid" | "unknown";

function under(pathname: string, roots: string[]): boolean {
  return roots.some((root) => pathname === root || pathname.startsWith(`${root}/`));
}

async function checkSession(request: NextRequest, token: string): Promise<{ session: Session; onboarded: boolean }> {
  const result = await callBackend(request, "/auth/session", { token, timeoutMs: 4000 });
  if ([401, 403, 404].includes(result.status)) return { session: "invalid", onboarded: false };
  if (result.status >= 400) return { session: "unknown", onboarded: false };
  const profile = result.data.profile as { onboarding_complete?: boolean } | null | undefined;
  return { session: "valid", onboarded: Boolean(profile?.onboarding_complete) };
}

/** A same-site path from ?next=, or null (never another site: no open redirect). */
function safeNext(request: NextRequest): string | null {
  const next = request.nextUrl.searchParams.get("next");
  if (!next || !next.startsWith("/")) return null;
  try {
    const url = new URL(next, request.url);
    return url.origin === request.nextUrl.origin ? url.pathname + url.search : null;
  } catch {
    return null;
  }
}

function redirect(request: NextRequest, pathname: string, next?: string): NextResponse {
  const url = new URL(pathname, request.url);
  if (next) url.searchParams.set("next", next);
  return NextResponse.redirect(url);
}

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  // Link prefetches are not visits: the real navigation is checked when it
  // happens, so a prefetch costs no backend call.
  if (request.headers.get("next-router-prefetch")) return NextResponse.next();
  // "Forgot password" works whether or not the patient is signed in.
  if (pathname === "/signup" && request.nextUrl.searchParams.get("reset") === "1") return NextResponse.next();
  const isAuthPage = under(pathname, AUTH_PAGES);
  const token = request.cookies.get(SESSION_COOKIE)?.value;

  if (!token) {
    return isAuthPage ? NextResponse.next() : redirect(request, "/login", pathname + search);
  }

  const { session, onboarded } = await checkSession(request, token);

  if (session === "unknown") {
    // The backend did not answer: let the page load and handle it, rather
    // than locking people out or guessing where they belong.
    return NextResponse.next();
  }

  if (session === "invalid") {
    const response = isAuthPage ? NextResponse.next() : redirect(request, "/login", pathname + search);
    clearSessionCookie(response);
    return response;
  }

  if (!onboarded) {
    if (under(pathname, [ONBOARDING])) return NextResponse.next();
    // Where they were heading, so onboarding can take them there after.
    // The dashboard is where onboarding ends anyway, so it needs no next=.
    const destination = isAuthPage ? safeNext(request) : pathname + search;
    return redirect(request, ONBOARDING, destination && destination !== DASHBOARD ? destination : undefined);
  }
  if (isAuthPage) return redirect(request, safeNext(request) ?? DASHBOARD);
  if (under(pathname, [ONBOARDING])) return redirect(request, safeNext(request) ?? DASHBOARD);
  return NextResponse.next();
}

export const config = {
  matcher: ["/interview/:path*", "/onboarding/:path*", "/health-card/:path*", "/login", "/signup"],
};
