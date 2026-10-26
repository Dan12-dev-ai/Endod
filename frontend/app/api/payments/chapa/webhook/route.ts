import { NextRequest, NextResponse } from "next/server";
import { callBackend, str } from "@/app/lib/server/backend";

// Chapa's webhook (public), passed to the backend byte for byte with its
// signature headers: the backend checks the signature and then verifies the
// payment with Chapa before confirming any booking.

const MAX_BODY_BYTES = 64_000;

/** The body as text, or null once it passes `limit` bytes (stops reading there). */
async function readLimited(request: NextRequest, limit: number): Promise<string | null> {
  if (Number(request.headers.get("content-length") ?? 0) > limit) return null;
  const reader = request.body?.getReader();
  if (!reader) return "";
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  return Buffer.concat(chunks).toString("utf8");
}

export async function POST(request: NextRequest) {
  const raw = await readLimited(request, MAX_BODY_BYTES);
  if (raw === null) return NextResponse.json({ ok: false }, { status: 413 });
  const headers: Record<string, string> = {};
  for (const name of ["chapa-signature", "x-chapa-signature"]) {
    const value = request.headers.get(name);
    if (value) headers[name] = value.slice(0, 200);
  }
  const result = await callBackend(request, "/payments/chapa/webhook", {
    method: "POST", rawBody: raw, extraHeaders: headers,
  });
  // A public URL: the reason stays in the backend's log.
  if (result.status >= 400) return NextResponse.json({ ok: false }, { status: result.status >= 500 ? 502 : 400 });
  return NextResponse.json({ ok: true, status: str(result.data.status) });
}
