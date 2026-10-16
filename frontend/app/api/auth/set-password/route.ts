import { NextRequest, NextResponse } from "next/server";
import {
  badRequest, callBackend, clearVerificationCookie, failure, forbiddenOrigin, isSameOrigin, readJson,
  setSessionCookie, str, VERIFICATION_COOKIE,
} from "@/app/lib/server/backend";

// Creates the account, or resets its password, after a verified code
// (backend: POST /auth/phone/complete), and signs the patient in.
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return forbiddenOrigin();
  const body = await readJson(request);
  if (!body) return badRequest();
  const verificationToken = request.cookies.get(VERIFICATION_COOKIE)?.value;
  if (!verificationToken) {
    return NextResponse.json(
      { ok: false, error: "Your verification has expired. Please request a new code." },
      { status: 401 },
    );
  }

  const payload: Record<string, string> = {
    verification_token: verificationToken,
    password: str(body.password),
    password_confirmation: str(body.passwordConfirmation ?? body.password),
  };
  for (const [from, to] of [["firstName", "first_name"], ["lastName", "last_name"]] as const) {
    const value = str(body[from]).trim();
    if (value) payload[to] = value;
  }

  const result = await callBackend(request, "/auth/phone/complete", { method: "POST", body: payload });
  const token = str(result.data.access_token);
  if (result.status >= 400 || !token) {
    const response = failure(result, "Unable to save your password. Please try again.");
    // A used or expired verification cannot be retried; a weak password can.
    if (result.status === 401) clearVerificationCookie(response);
    return response;
  }

  const response = NextResponse.json({ ok: true, created: Boolean(result.data.created) });
  setSessionCookie(response, token, Number(result.data.expires_in));
  clearVerificationCookie(response);
  return response;
}
