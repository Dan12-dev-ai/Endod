import { NextRequest, NextResponse } from "next/server";
import {
  badRequest, callBackend, failure, forbiddenOrigin, isSameOrigin, readJson, setVerificationCookie, str,
} from "@/app/lib/server/backend";

// Checks the SMS code (backend: POST /auth/phone/verify). The single-use
// verification token is kept in an httpOnly cookie for the set-password step.
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return forbiddenOrigin();
  const body = await readJson(request);
  if (!body) return badRequest();
  const phone = str(body.phone).trim();
  const code = str(body.code).replace(/\s/g, "");
  if (!phone || !code) return badRequest("Phone number and code are required.");

  const result = await callBackend(request, "/auth/phone/verify", { method: "POST", body: { phone, code } });
  const token = str(result.data.verification_token);
  if (result.status >= 400 || !token) return failure(result, "That code did not work. Please try again.");

  const response = NextResponse.json({ ok: true, accountExists: Boolean(result.data.account_exists) });
  setVerificationCookie(response, token, Number(result.data.expires_in) || 900);
  return response;
}
