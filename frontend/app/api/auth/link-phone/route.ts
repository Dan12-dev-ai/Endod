import { NextRequest, NextResponse } from "next/server";
import {
  callBackend, clearVerificationCookie, failure, forbiddenOrigin, isSameOrigin, SESSION_COOKIE,
  VERIFICATION_COOKIE,
} from "@/app/lib/server/backend";

// Links the number just confirmed by code (verify-otp) to the signed-in
// account (backend: POST /users/me/phone), so it can be used to sign in.
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return forbiddenOrigin();
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ ok: false, error: "Authentication required." }, { status: 401 });
  const verificationToken = request.cookies.get(VERIFICATION_COOKIE)?.value;
  if (!verificationToken) {
    return NextResponse.json(
      { ok: false, error: "Your verification has expired. Please request a new code." },
      { status: 401 },
    );
  }

  const result = await callBackend(request, "/users/me/phone", {
    method: "POST",
    token,
    body: { verification_token: verificationToken },
  });
  // The verification is single use either way.
  const response = result.status >= 400
    ? failure(result, "Unable to link this number.")
    : NextResponse.json({ ok: true, profile: result.data });
  clearVerificationCookie(response);
  return response;
}
