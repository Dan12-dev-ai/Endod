import { NextRequest, NextResponse } from "next/server";
import { callBackend, failure, str } from "@/app/lib/server/backend";

// Chapa calls this when a payment finishes (public). It carries only the
// transaction reference: the backend then asks Chapa itself whether the
// payment went through, so a forged call cannot add money.

const TX_REF = /^[A-Za-z0-9_-]{1,64}$/;

async function settle(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const txRef = str(params.get("trx_ref") ?? params.get("tx_ref"));
  if (!TX_REF.test(txRef)) return NextResponse.json({ ok: false, error: "Missing reference." }, { status: 400 });
  const result = await callBackend(request, "/payments/chapa/callback", {
    search: `?trx_ref=${encodeURIComponent(txRef)}`,
  });
  if (result.status >= 400) return failure(result, "The payment could not be checked.");
  return NextResponse.json({ ok: true, status: str(result.data.status) });
}

export const GET = settle;
export const POST = settle;
