import { NextRequest, NextResponse } from "next/server";
import { verifyOtp } from "@/app/lib/otp-store";
import { normalizeEthiopianPhone } from "@/app/lib/phone";

export async function POST(request: NextRequest) {
  let body: { phone?: string; code?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid request body." }, { status: 400 });
  }

  const msisdn = normalizeEthiopianPhone(body.phone ?? "");
  const code = (body.code ?? "").replace(/\s/g, "");

  if (!msisdn || !code) {
    return NextResponse.json(
      { ok: false, error: "Phone number and code are required." },
      { status: 400 },
    );
  }

  const result = verifyOtp(msisdn, code);
  if (!result.ok) {
    return NextResponse.json({ ok: false, error: result.reason }, { status: 400 });
  }

  return NextResponse.json({ ok: true });
}
