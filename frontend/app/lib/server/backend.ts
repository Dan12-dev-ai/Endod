// Server-side access to the DEDAN backend (backend-v2).
//
// Only route handlers and proxy.ts import this. The browser never sees a
// backend token: the session lives in an httpOnly cookie, and every backend
// call goes through a Next.js route handler that adds the Authorization
// header.

import { NextRequest, NextResponse } from "next/server";

/** Session token (httpOnly). */
export const SESSION_COOKIE = "dedan_session";
/** Single-use phone verification token between "verify code" and "set password". */
export const VERIFICATION_COOKIE = "dedan_phone_verification";

const BACKEND_TIMEOUT_MS = 30_000;
const UNAVAILABLE = "The service is unavailable right now. Please try again shortly.";

/** `data` is the JSON object (an array is wrapped as `{ items }`); `raw` is the body as parsed. */
export type BackendResult = { status: number; data: Record<string, unknown>; raw: unknown };

function backendBase(): string {
  return (process.env.DEDAN_API_URL ?? "http://localhost:8001").replace(/\/+$/, "");
}

/**
 * The caller's address, passed on so the backend's rate limits are per person.
 *
 * The left end of X-Forwarded-For is whatever the client sent, so it is never
 * used: each proxy appends the address it saw, and the entry added by the
 * outermost proxy we run is TRUSTED_PROXY_HOPS from the right (default 1, a
 * load balancer or reverse proxy in front of this app; Next.js itself adds
 * the socket address when the header is missing). Deploy behind such a proxy:
 * when this app is reachable directly, a client can choose this value.
 */
export function clientAddress(request: NextRequest): string | null {
  const hops = Math.max(1, Number.parseInt(process.env.TRUSTED_PROXY_HOPS ?? "1", 10) || 1);
  const entries = (request.headers.get("x-forwarded-for") ?? "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
  const address = entries[entries.length - hops];
  return address && /^[0-9A-Fa-f:.]{2,45}$/.test(address) ? address : null;
}

export async function callBackend(
  request: NextRequest,
  path: string,
  options: { method?: string; body?: unknown; rawBody?: string; token?: string | null; search?: string } = {},
): Promise<BackendResult> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const body = options.rawBody ?? (options.body === undefined ? undefined : JSON.stringify(options.body));
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (options.token) headers.Authorization = `Bearer ${options.token}`;
  const address = clientAddress(request);
  if (address) headers["X-Forwarded-For"] = address;
  const correlation = request.headers.get("x-correlation-id");
  if (correlation) headers["X-Correlation-ID"] = correlation.slice(0, 64);

  let response: Response;
  try {
    response = await fetch(`${backendBase()}${path}${options.search ?? ""}`, {
      method: options.method ?? "GET",
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
  } catch (error) {
    console.error("[backend] request failed", path, error);
    const data = { error: UNAVAILABLE };
    return { status: 503, data, raw: data };
  }

  const text = await response.text();
  let data: Record<string, unknown> = {};
  let raw: unknown = data;
  if (text) {
    try {
      raw = JSON.parse(text);
      data = Array.isArray(raw) ? { items: raw } : (raw as Record<string, unknown>);
    } catch {
      data = { error: response.ok ? "Unexpected response from the service." : UNAVAILABLE };
      raw = data;
    }
  }
  return { status: response.status, data, raw };
}

/** The message to show for a failed backend call. */
export function errorMessage(data: Record<string, unknown>, fallback: string): string {
  const error = data.error ?? data.detail;
  return typeof error === "string" && error ? error : fallback;
}

/** `{ ok: false, error }` with the backend's status. */
export function failure(result: BackendResult, fallback: string): NextResponse {
  return NextResponse.json(
    { ok: false, error: errorMessage(result.data, fallback) },
    { status: result.status >= 400 ? result.status : 502 },
  );
}

const secureCookies = process.env.NODE_ENV === "production";

export function setSessionCookie(response: NextResponse, token: string, expiresIn: number): void {
  response.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: secureCookies,
    sameSite: "lax",
    path: "/",
    maxAge: Math.max(60, Math.floor(expiresIn || 43200)),
  });
}

export function clearSessionCookie(response: NextResponse): void {
  response.cookies.set(SESSION_COOKIE, "", { httpOnly: true, secure: secureCookies, sameSite: "lax", path: "/", maxAge: 0 });
}

export function setVerificationCookie(response: NextResponse, token: string, expiresIn: number): void {
  response.cookies.set(VERIFICATION_COOKIE, token, {
    httpOnly: true,
    secure: secureCookies,
    sameSite: "strict",
    path: "/api/auth",
    maxAge: Math.max(60, Math.floor(expiresIn || 900)),
  });
}

export function clearVerificationCookie(response: NextResponse): void {
  response.cookies.set(VERIFICATION_COOKIE, "", {
    httpOnly: true, secure: secureCookies, sameSite: "strict", path: "/api/auth", maxAge: 0,
  });
}

/**
 * Cross-site request check for state-changing calls.
 *
 * The session cookie is SameSite=Lax, which already keeps it off cross-site
 * POSTs; this also refuses any request whose Origin is another site.
 */
export function isSameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true; // Same-origin fetches from older browsers, server calls.
  try {
    const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export function forbiddenOrigin(): NextResponse {
  return NextResponse.json({ ok: false, error: "Request blocked." }, { status: 403 });
}

/** Parse a JSON request body, or null. */
export async function readJson(request: NextRequest): Promise<Record<string, unknown> | null> {
  try {
    const body = await request.json();
    return body && typeof body === "object" && !Array.isArray(body) ? body : null;
  } catch {
    return null;
  }
}

export function badRequest(message = "Invalid request body."): NextResponse {
  return NextResponse.json({ ok: false, error: message }, { status: 400 });
}

export function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}
