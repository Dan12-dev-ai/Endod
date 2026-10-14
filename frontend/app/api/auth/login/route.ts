import { NextRequest, NextResponse } from "next/server";
import { hasUser, verifyUserPassword } from "@/app/lib/user-store";
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
  if (!password) {
    return NextResponse.json(
      { ok: false, error: "Please enter your password." },
      { status: 400 },
    );
  }

  if (!hasUser(msisdn)) {
    return NextResponse.json(
      { ok: false, error: "No account found for this number. Please sign up first." },
      { status: 404 },
    );
  }

  if (!verifyUserPassword(msisdn, password)) {
    return NextResponse.json(
      { ok: false, error: "Incorrect phone number or password." },
      { status: 401 },
    );
  }

  return NextResponse.json({ ok: true });
}