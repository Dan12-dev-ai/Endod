import { NextRequest, NextResponse } from "next/server";
import { clearSessionCookie, clientAddress, SESSION_COOKIE } from "@/app/lib/server/backend";

// A file of one of the signed-in patient's records (a lab report, an X-ray),
// streamed from the backend. The JSON proxy (/api/backend) cannot carry
// binary data, so this route does, and only this:
//
// - only GET /users/me/history/records/<32 hex>/files/<32 hex> on the backend,
//   with the patient's own session (the backend checks the file is theirs);
// - only the four file types records may have, never anything else;
// - nothing cached, no type sniffing, and an image opened on its own can run nothing.

const ID = /^[0-9a-f]{32}$/;
const ALLOWED_TYPES = new Set(["application/pdf", "image/jpeg", "image/png", "image/webp"]);
const TIMEOUT_MS = 60_000;

function backendBase(): string {
  return (process.env.DEDAN_API_URL ?? "http://localhost:8001").replace(/\/+$/, "");
}

function notFound() {
  return NextResponse.json({ error: "File not found." }, { status: 404 });
}

export async function GET(request: NextRequest, ctx: RouteContext<"/api/records/files/[recordId]/[fileId]">) {
  const { recordId, fileId } = await ctx.params;
  if (!ID.test(recordId) || !ID.test(fileId)) return notFound();
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: "Authentication required." }, { status: 401 });
  const download = request.nextUrl.searchParams.get("download") === "1";

  const headers: Record<string, string> = { Authorization: `Bearer ${token}`, Accept: [...ALLOWED_TYPES].join(", ") };
  const address = clientAddress(request);
  if (address) headers["X-Forwarded-For"] = address;

  let upstream: Response;
  try {
    upstream = await fetch(
      `${backendBase()}/users/me/history/records/${recordId}/files/${fileId}${download ? "?download=true" : ""}`,
      { headers, cache: "no-store", signal: AbortSignal.timeout(TIMEOUT_MS) },
    );
  } catch {
    return NextResponse.json({ error: "The service is unavailable right now. Please try again shortly." }, { status: 503 });
  }
  if (upstream.status === 401) {
    const response = NextResponse.json({ error: "Authentication required." }, { status: 401 });
    clearSessionCookie(response);
    return response;
  }
  const type = (upstream.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (!upstream.ok || !upstream.body || !ALLOWED_TYPES.has(type)) {
    await upstream.body?.cancel().catch(() => undefined);
    return notFound();
  }

  const out = new Headers({
    "Content-Type": type,
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
  });
  const length = upstream.headers.get("content-length");
  if (length && /^\d+$/.test(length)) out.set("Content-Length", length);
  const disposition = upstream.headers.get("content-disposition");
  // The backend builds this header (a safe ASCII name plus filename*); only its form is checked here.
  if (disposition && /^(inline|attachment); filename="[A-Za-z0-9._ -]{1,120}"; filename\*=UTF-8''[A-Za-z0-9%._~-]{1,1200}$/.test(disposition)) {
    out.set("Content-Disposition", disposition);
  } else {
    out.set("Content-Disposition", download ? "attachment" : "inline");
  }
  if (type.startsWith("image/")) {
    out.set("Content-Security-Policy", "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox");
  }
  return new NextResponse(upstream.body, { status: 200, headers: out });
}
