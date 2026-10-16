import { NextRequest, NextResponse } from "next/server";
import {
  badRequest, callBackend, failure, forbiddenOrigin, isSameOrigin, readJson, str,
} from "@/app/lib/server/backend";

// Sends a verification code by SMS (backend: POST /auth/phone/request-code).
// The answer is the same whether or not an account exists for the number.
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return forbiddenOrigin();
  const body = await readJson(request);
  if (!body) return badRequest();
  const phone = str(body.phone).trim();
  if (!phone) return badRequest("Please enter your phone number.");

  const result = await callBackend(request, "/auth/phone/request-code", { method: "POST", body: { phone } });
  if (result.status >= 400) return failure(result, "Failed to send the verification code. Please try again.");
  return NextResponse.json({
    ok: true,
    expiresIn: result.data.expires_in ?? 300,
    resendAfter: result.data.resend_after ?? 60,
  });
}
