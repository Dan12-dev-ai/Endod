import { NextRequest, NextResponse } from "next/server";
import { callBackend, failure, str } from "@/app/lib/server/backend";

// Chapa's webhook (public), passed to the backend byte for byte with its
// signature headers: the backend checks the signature and then verifies the
// payment with Chapa before crediting anything.

const MAX_BODY_BYTES = 64_000;

export async function POST(request: NextRequest) {
  const raw = await request.text();
  if (raw.length > MAX_BODY_BYTES) return NextResponse.json({ ok: false }, { status: 413 });
  const headers: Record<string, string> = {};
  for (const name of ["chapa-signature", "x-chapa-signature"]) {
    const value = request.headers.get(name);
    if (value) headers[name] = value.slice(0, 200);
  }
  const result = await callBackend(request, "/payments/chapa/webhook", {
    method: "POST", rawBody: raw, extraHeaders: headers,
  });
  if (result.status >= 400) return failure(result, "Not accepted.");
  return NextResponse.json({ ok: true, status: str(result.data.status) });
}
