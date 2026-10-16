import { NextRequest, NextResponse } from "next/server";
import { clearSessionCookie, forbiddenOrigin, isSameOrigin } from "@/app/lib/server/backend";

export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return forbiddenOrigin();
  const response = NextResponse.json({ ok: true });
  clearSessionCookie(response);
  return response;
}
