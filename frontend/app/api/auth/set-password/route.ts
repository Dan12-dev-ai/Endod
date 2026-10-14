import { NextRequest, NextResponse } from "next/server";
import {
  MAX_PASSWORD_LENGTH,
  MIN_PASSWORD_LENGTH,
  setUserPassword,
} from "@/app/lib/user-store";
import { normalizeEthiopianPhone } from "@/app/lib/phone";

export async function POST(request: NextRequest) {
  let body: { phone?: string; password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid request body." }, { status: 400 });
  }

  const msisdn = normalizeEthiopianPhone(body.phone ?? "");
  if (!msisdn) {
    return NextResponse.json(
      { ok: false, error: "Please enter a valid phone number." },
      { status: 400 },
    );
  }

  const password = body.password ?? "";
  if (password.length < MIN_PASSWORD_LENGTH) {
    return NextResponse.json(
      { ok: false, error: `Password must be at least ${MIN_PASSWORD_LENGTH} characters.` },
      { status: 400 },
    );
  }
  if (password.length > MAX_PASSWORD_LENGTH) {
    return NextResponse.json(
      { ok: false, error: `Password must be at most ${MAX_PASSWORD_LENGTH} characters.` },
      { status: 400 },
    );
  }

  setUserPassword(msisdn, password);
  return NextResponse.json({ ok: true });
}