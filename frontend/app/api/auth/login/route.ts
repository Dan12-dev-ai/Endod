import { NextRequest, NextResponse } from "next/server";
import {
  badRequest, callBackend, failure, forbiddenOrigin, isSameOrigin, readJson, setSessionCookie, str,
} from "@/app/lib/server/backend";

// Password sign-in (backend: POST /auth/login). The identifier can be a
// verified phone number, an email address or a DEDAN ID.
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return forbiddenOrigin();
  const body = await readJson(request);
  if (!body) return badRequest();
  const identifier = str(body.identifier ?? body.phone).trim();
  const password = str(body.password);
  if (!identifier) return badRequest("Please enter your phone number.");
  if (!password) return badRequest("Please enter your password.");

  const result = await callBackend(request, "/auth/login", { method: "POST", body: { identifier, password } });
  const token = str(result.data.access_token);
  if (result.status >= 400 || !token) return failure(result, "Unable to sign in. Please try again.");

  const response = NextResponse.json({ ok: true });
  setSessionCookie(response, token, Number(result.data.expires_in));
  return response;
}
