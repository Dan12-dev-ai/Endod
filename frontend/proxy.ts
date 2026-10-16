import { NextRequest, NextResponse } from "next/server";

// Optimistic sign-in check for the app's private pages: no session cookie
// means straight to the login page. The backend still checks the token on
// every call, so this is a convenience, not the security boundary.

const SESSION_COOKIE = "dedan_session";

export function proxy(request: NextRequest) {
  if (request.cookies.get(SESSION_COOKIE)?.value) return NextResponse.next();
  const login = new URL("/login", request.url);
  login.searchParams.set("next", request.nextUrl.pathname);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/interview/:path*", "/onboarding/:path*", "/health-card/:path*"],
};
