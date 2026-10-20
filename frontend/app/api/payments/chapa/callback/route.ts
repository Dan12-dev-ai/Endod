import { NextRequest, NextResponse } from "next/server";
import { callBackend, failure, str } from "@/app/lib/server/backend";

// Chapa calls this when a payment finishes (public). It carries only the
// transaction reference: the backend then asks Chapa itself whether the
// payment went through, so a forged call cannot add money.

const TX_REF = /^[A-Za-z0-9_-]{1,64}$/;

/** The reference from the query, or a POST's small JSON or form body. */
async function reference(request: NextRequest): Promise<string> {
  const params = request.nextUrl.searchParams;
  const fromQuery = params.get("trx_ref") ?? params.get("tx_ref");
  if (fromQuery || request.method !== "POST") return str(fromQuery);
  if (Number(request.headers.get("content-length") ?? 0) > 8_000) return "";
  const raw = (await request.text()).slice(0, 8_000);
  try {
    const body = JSON.parse(raw) as Record<string, unknown>;
    return str(body.trx_ref ?? body.tx_ref);
  } catch {
    const form = new URLSearchParams(raw);
    return str(form.get("trx_ref") ?? form.get("tx_ref"));
  }
}

async function settle(request: NextRequest) {
  const txRef = await reference(request);
  if (!TX_REF.test(txRef)) return NextResponse.json({ ok: false, error: "Missing reference." }, { status: 400 });
  const result = await callBackend(request, "/payments/chapa/callback", {
    search: `?trx_ref=${encodeURIComponent(txRef)}`,
  });
  if (result.status >= 400) return failure(result, "The payment could not be checked.");
  return NextResponse.json({ ok: true, status: str(result.data.status) });
}

export const GET = settle;
export const POST = settle;
