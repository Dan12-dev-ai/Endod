import { NextRequest, NextResponse } from "next/server";
import { createOtp, OTP_TTL_MINUTES } from "@/app/lib/otp-store";
import { normalizeEthiopianPhone } from "@/app/lib/phone";

const SMS_SEND_URL = "https://smsethiopia.com/api/sms/send";

export async function POST(request: NextRequest) {
  let body: { phone?: string };
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

  const code = createOtp(msisdn);

  const text = `Endod Health verification code: ${code}. It expires in ${OTP_TTL_MINUTES} minutes. Do not share it with anyone.`;

  const apiKey = process.env.SMSETHIOPIA_API_KEY;
  if (!apiKey) {
    // No API key configured (e.g. local development). Log the code so the
    // flow can be exercised without sending a real SMS. In production, always
    // set SMSETHIOPIA_API_KEY so this branch is never taken.
    console.warn(
      `[send-otp] SMSETHIOPIA_API_KEY is not set. Dev code for ${msisdn}: ${code}`,
    );
    return NextResponse.json({ ok: true, dev: true, devCode: code });
  }

  try {
    const smsResponse = await fetch(SMS_SEND_URL, {
      method: "POST",
      headers: {
        KEY: apiKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ msisdn, text }),
    });

    if (!smsResponse.ok) {
      const detail = await smsResponse.text().catch(() => "");
      console.error("[send-otp] SMS Ethiopia error", smsResponse.status, detail);
      return NextResponse.json(
        { ok: false, error: "Failed to send the verification code. Please try again." },
        { status: 502 },
      );
    }
  } catch (error) {
    console.error("[send-otp] Network error sending SMS", error);
    return NextResponse.json(
      { ok: false, error: "Failed to send the verification code. Please try again." },
      { status: 502 },
    );
  }

  return NextResponse.json({ ok: true });
}
