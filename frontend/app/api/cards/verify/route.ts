import { NextRequest, NextResponse } from "next/server";
import { callBackend, failure, str } from "@/app/lib/server/backend";

// Public: is this Digital Health Card genuine? (backend: GET /cards/{id}/verify)
// Anyone who scans a card's QR code lands here, signed in or not.
export async function GET(request: NextRequest) {
  const id = str(request.nextUrl.searchParams.get("id")).trim();
  const signature = str(request.nextUrl.searchParams.get("s")).trim();
  if (!/^[A-Za-z]{2}\d{6}$/.test(id) || !/^[A-Za-z0-9_-]{10,64}$/.test(signature)) {
    return NextResponse.json({ ok: false, error: "This card could not be verified." }, { status: 404 });
  }
  const result = await callBackend(request, `/cards/${encodeURIComponent(id)}/verify`, {
    search: `?s=${encodeURIComponent(signature)}`,
  });
  if (result.status >= 400) return failure(result, "This card could not be verified.");
  return NextResponse.json({
    ok: true,
    dedan_user_id: str(result.data.dedan_user_id),
    full_name: str(result.data.full_name),
    issued_at: str(result.data.issued_at),
  });
}
