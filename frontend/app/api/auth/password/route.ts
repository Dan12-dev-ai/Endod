import { NextRequest, NextResponse } from "next/server";
import {
  badRequest, callBackend, failure, forbiddenOrigin, isSameOrigin, readJson, SESSION_COOKIE,
  setSessionCookie, str,
} from "@/app/lib/server/backend";

// Change password (backend: POST /auth/password). Every older token stops
// working, so the cookie is replaced with the new one.
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return forbiddenOrigin();
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ ok: false, error: "Authentication required." }, { status: 401 });
  const body = await readJson(request);
  if (!body) return badRequest();

  const result = await callBackend(request, "/auth/password", {
    method: "POST",
    token,
    body: {
      current_password: str(body.currentPassword),
      new_password: str(body.newPassword),
      new_password_confirmation: str(body.newPasswordConfirmation ?? body.newPassword),
    },
  });
  const newToken = str(result.data.access_token);
  if (result.status >= 400 || !newToken) return failure(result, "Unable to change your password.");

  const response = NextResponse.json({ ok: true });
  setSessionCookie(response, newToken, Number(result.data.expires_in));
  return response;
}
