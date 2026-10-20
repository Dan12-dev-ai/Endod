import { connection, NextResponse } from "next/server";

// Settings the browser needs, read from the server's environment at request
// time (so a key can be added to the deployment without rebuilding the app).
// The Google Maps key is a browser key: Google restricts it to Endod's own
// web addresses, which is what makes it safe to hand to the page.

export async function GET() {
  // Not prerendered at build time: the key is read on each request.
  await connection();
  return NextResponse.json(
    { googleMapsKey: process.env.GOOGLE_MAPS_BROWSER_KEY || null },
    { headers: { "Cache-Control": "private, max-age=300" } },
  );
}
