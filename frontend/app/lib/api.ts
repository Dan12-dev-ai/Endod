// Browser-side calls to the patient's own data (/users/me/...).
//
// Requests go to the Next.js proxy route (/api/backend/...), which adds the
// session token. A 401 means the session ended, so the user is sent to log in.

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly details?: unknown) {
    super(message);
  }
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

export async function api<T = Record<string, unknown>>(
  path: string,
  options: { method?: Method; body?: unknown; query?: Record<string, string | number | boolean | undefined | null> } = {},
): Promise<T> {
  const url = new URL(`/api/backend/${path.replace(/^\/+/, "")}`, window.location.origin);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Unable to reach the server. Please check your connection.", 0);
  }

  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    redirectToLogin();
    throw new ApiError("Please sign in again.", 401);
  }
  if (!response.ok) {
    const message = typeof data?.error === "string" ? data.error : "Something went wrong. Please try again.";
    throw new ApiError(message, response.status, data?.details);
  }
  return data as T;
}

// Both use a full page load on purpose: it drops every piece of the patient's
// data held in memory by the previous session.
export function redirectToLogin(): void {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`/login?next=${next}`);
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign("/login");
}

/** Password rule enforced by the backend: 10+ characters, upper and lower case. */
export function passwordProblem(password: string): string | null {
  if (password.length < 10) return "Password must be at least 10 characters.";
  if (!/[a-z]/.test(password) || !/[A-Z]/.test(password)) {
    return "Password must include both upper and lower case letters.";
  }
  return null;
}

/** A safe in-app path from ?next=, or the fallback. */
export function safeNext(next: string | null, fallback: string): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : fallback;
}
