import { NextRequest, NextResponse } from "next/server";
import {
  callBackend, clearSessionCookie, forbiddenOrigin, isSameOrigin, SESSION_COOKIE,
} from "@/app/lib/server/backend";

// Forwards the signed-in patient's own API calls (/users/me/...) to the
// backend with their session token. Nothing outside /users/me is reachable
// through here, and the token never reaches the browser.

const SEGMENT = /^[A-Za-z0-9_.:-]{1,128}$/;
const MAX_BODY_BYTES = 1_000_000;

async function forward(request: NextRequest, ctx: RouteContext<"/api/backend/[...path]">) {
  const { path } = await ctx.params;
  if (
    path.length < 2 || path[0] !== "users" || path[1] !== "me"
    || !path.every((segment) => SEGMENT.test(segment) && segment !== "." && segment !== "..")
  ) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  if (request.method !== "GET" && !isSameOrigin(request)) return forbiddenOrigin();

  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: "Authentication required." }, { status: 401 });

  let rawBody: string | undefined;
  if (request.method === "POST" || request.method === "PATCH") {
    rawBody = await request.text();
    if (rawBody.length > MAX_BODY_BYTES) {
      return NextResponse.json({ error: "Request body too large" }, { status: 413 });
    }
    if (!rawBody) rawBody = undefined;
  }

  const result = await callBackend(request, `/${path.map(encodeURIComponent).join("/")}`, {
    method: request.method,
    token,
    rawBody,
    search: request.nextUrl.search,
  });
  const response = NextResponse.json(result.raw, { status: result.status });
  if (result.status === 401) clearSessionCookie(response);
  return response;
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const DELETE = forward;
