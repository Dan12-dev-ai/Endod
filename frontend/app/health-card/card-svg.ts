/**
 * SVG health-card generator.
 * Given user data, returns a self-contained pure-SVG string.
 *
 * Uses inline attributes (no <style>, no <foreignObject>) so the SVG
 * renders reliably in <img> tags and when converted to PNG via canvas.drawImage.
 */

export type HealthCardData = {
  fullName: string;
  userId: string;
  phone: string;
  issuedDate: string;
  expiryDate: string;
  qrSvg: string; // raw svg string from qrMatrixToSvg
};

export function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Extract the inner content of the QR <svg> (the <rect> elements). */
function extractPaths(svgRaw: string): string {
  const match = svgRaw.match(/<svg[^>]*>([\s\S]*?)<\/svg>/);
  return match ? match[1] : "";
}

/** Extract the viewBox value of the QR <svg>. */
function extractViewBox(svgRaw: string): string {
  const match = svgRaw.match(/viewBox="([^"]*)"/);
  return match ? match[1] : "0 0 37 37";
}

/** Extract the square side length (in user units) from a viewBox string. */
function viewBoxSize(viewBox: string): number {
  const parts = viewBox.trim().split(/\s+/).map(Number);
  return parts.length === 4 && Number.isFinite(parts[2]) ? parts[2] : 37;
}

export function buildHealthCardSvg(d: HealthCardData): string {
  const qrPaths = extractPaths(d.qrSvg);
  const qrViewBox = extractViewBox(d.qrSvg);

  // Pure SVG with inline attributes — no <style>, no <foreignObject>,
  // no <filter>, no currentColor. This ensures reliable rendering
  // when loaded as an <img> and drawn to <canvas> for PNG export.
  return `<svg xmlns="http://www.w3.org/2000/svg" width="720" height="480" viewBox="0 0 720 480">
  <defs>
    <linearGradient id="g1" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1e3a2e"/>
      <stop offset="100%" stop-color="#1e5852"/>
    </linearGradient>
  </defs>

  <!-- Card background -->
  <rect x="40" y="40" width="640" height="400" rx="24" fill="url(#g1)"/>

  <!-- Subtle pattern overlay -->
  <g transform="translate(40,40) scale(6.4,4)" opacity="3%" fill="none">
    <circle cx="31.25" cy="31.25" r="7.8125" stroke="#ffffff" stroke-width="0.03125"/>
    <circle cx="31.25" cy="31.25" r="18.75" stroke="#ffffff" stroke-width="0.015625"/>
  </g>

  <!-- Brand -->
  <text x="80" y="120" font-family="Arial, sans-serif" font-size="26" font-weight="800" letter-spacing="-0.5px" fill="#ffffff">Endod</text>

  <!-- "Digital Health ID" label -->
  <text x="80" y="152" font-family="Arial, sans-serif" font-size="11" font-weight="600" text-anchor="start" fill="#94e0c0">Digital Health ID</text>

  <!-- Full name -->
  <text x="80" y="200" font-family="Georgia, serif" font-size="32" font-weight="700" fill="#ffffff">${escapeXml(d.fullName)}</text>

  <!-- User ID -->
  <text x="80" y="240" font-family="Arial, sans-serif" font-size="16" font-weight="600" fill="#94e0c0">${escapeXml(d.userId)}</text>

  <!-- QR code -->
  <g transform="translate(80,268)">
    <svg x="0" y="0" width="132" height="132" viewBox="${qrViewBox}" preserveAspectRatio="xMidYMid meet" fill="#000000">
      <rect x="0" y="0" width="${viewBoxSize(qrViewBox)}" height="${viewBoxSize(qrViewBox)}" fill="#ffffff"/>
      ${qrPaths}
    </svg>
    <text x="66" y="155" font-family="Arial, sans-serif" font-size="9" font-weight="600" text-anchor="middle" fill="#94a3a8">Scan to verify</text>
  </g>

  <!-- Info grid -->
  <!-- Phone -->
  <text x="244" y="300" font-family="Arial, sans-serif" font-size="10" font-weight="600" text-transform="uppercase" fill="#94a3a8">Phone</text>
  <text x="244" y="328" font-family="Arial, sans-serif" font-size="15" font-weight="600" fill="#ffffff">${escapeXml(d.phone)}</text>
  <!-- Patient ID -->
  <text x="494" y="300" font-family="Arial, sans-serif" font-size="10" font-weight="600" text-transform="uppercase" fill="#94a3a8">Patient ID</text>
  <text x="494" y="328" font-family="Arial, sans-serif" font-size="15" font-weight="600" fill="#ffffff">${escapeXml(d.userId)}</text>
  <!-- Issued -->
  <text x="244" y="366" font-family="Arial, sans-serif" font-size="10" font-weight="600" text-transform="uppercase" fill="#94a3a8">Issued</text>
  <text x="244" y="394" font-family="Arial, sans-serif" font-size="13" font-weight="500" fill="#ffffff" opacity="0.9">${escapeXml(d.issuedDate)}</text>
  <!-- Expires -->
  <text x="494" y="366" font-family="Arial, sans-serif" font-size="10" font-weight="600" text-transform="uppercase" fill="#94a3a8">Expires</text>
  <text x="494" y="394" font-family="Arial, sans-serif" font-size="13" font-weight="600" fill="#6ee7b7">${escapeXml(d.expiryDate)}</text>

  <!-- Footer -->
  <line x1="80" y1="384" x2="680" y2="384" stroke="#ffffff" stroke-width="1" opacity="0.1"/>
  <text x="80" y="416" font-family="Arial, sans-serif" font-size="11" fill="#94a3a8">Issued ${escapeXml(d.issuedDate)}</text>

  <!-- Footer badge -->
  <g transform="translate(540,400)">
    <rect x="0" y="0" width="140" height="32" rx="20" fill="#ffffff" opacity="0.1" stroke="#94e0c0" stroke-width="1"/>
    <text x="70" y="20" font-family="Arial, sans-serif" font-size="11" font-weight="600" text-anchor="middle" fill="#6ee7b7">Expires: ${escapeXml(d.expiryDate)}</text>
  </g>
</svg>`;
}

export function buildHealthCardHtml(d: HealthCardData): string {
  const qrPaths = extractPaths(d.qrSvg);
  const qrViewBox = extractViewBox(d.qrSvg);

  // HTML version for print/PDF — uses inline styles and Google Fonts
  return `<div style="width:640px;background:linear-gradient(135deg,#1e3a2e 0%,#1e5852 100%);border-radius:24px;padding:32px;position:relative;font-family:'Plus Jakarta Sans',Arial,sans-serif;color:#fff;box-sizing:border-box;overflow:hidden">
    <svg style="position:absolute;top:0;left:0;width:100%;height:100%;opacity:3%" viewBox="0 0 400 400" fill="none">
      <circle cx="200" cy="200" r="50" stroke="#ffffff" stroke-width="0.5"/>
      <circle cx="200" cy="200" r="120" stroke="#ffffff" stroke-width="0.3"/>
    </svg>
    <div style="margin-bottom:28px"><span style="font-size:26px;font-weight:800;letter-spacing:-0.5px">Endod</span></div>
    <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#94e0c0;margin-bottom:12px">Digital Health ID</div>
    <div style="margin-bottom:4px"><span style="font-family:'Newsreader',serif;font-size:32px;font-weight:700">${escapeXml(d.fullName)}</span></div>
    <div style="margin-bottom:24px"><span style="font-size:16px;font-weight:600;color:#94e0c0">${escapeXml(d.userId)}</span></div>
    <div style="display:flex;gap:24px;align-items:flex-start">
      <div style="flex-shrink:0;text-align:center">
        <svg width="132" height="132" viewBox="${qrViewBox}" style="background:#fff;border-radius:12px;padding:8px">${qrPaths}</svg>
        <div style="font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#94a3a8;margin-top:6px">Scan to verify</div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;flex:1">
        <div><span style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:#94a3a8">Phone</span><div style="font-size:15px;font-weight:600;margin-top:4px">${escapeXml(d.phone)}</div></div>
        <div><span style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:#94a3a8">Patient ID</span><div style="font-size:15px;font-weight:600;margin-top:4px">${escapeXml(d.userId)}</div></div>
        <div><span style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:#94a3a8">Issued</span><div style="font-size:13px;font-weight:500;margin-top:4px;opacity:0.9">${escapeXml(d.issuedDate)}</div></div>
        <div><span style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:#94a3a8">Expires</span><div style="font-size:13px;font-weight:600;margin-top:4px;color:#6ee7b7">${escapeXml(d.expiryDate)}</div></div>
      </div>
    </div>
    <div style="margin-top:24px;padding-top:16px;border-top:1px solid rgba(255,255,255,0.1);display:flex;justify-content:space-between;align-items:center;font-size:11px;color:#94a3a8">
      <span>Issued ${escapeXml(d.issuedDate)}</span>
      <span style="background:rgba(255,255,255,0.1);border:1px solid rgba(148,224,192,0.3);color:#6ee7b7;padding:5px 14px;border-radius:20px;font-weight:600">Expires: ${escapeXml(d.expiryDate)}</span>
    </div>
  </div>`;
}
