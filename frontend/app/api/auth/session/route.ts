import { NextRequest, NextResponse } from "next/server";
import { callBackend, clearSessionCookie, failure, SESSION_COOKIE } from "@/app/lib/server/backend";

// The signed-in patient's profile, or 401 (backend: GET /auth/session).
export async function GET(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ ok: false, error: "Authentication required." }, { status: 401 });

  const result = await callBackend(request, "/auth/session", { token });
  if (result.status >= 400) {
    const response = failure(result, "Unable to load your session.");
    if ([401, 403, 404].includes(result.status)) clearSessionCookie(response);
    return response;
  }
  return NextResponse.json({ ok: true, profile: result.data.profile ?? null });
}
