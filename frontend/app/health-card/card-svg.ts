/**
 * The Digital Health Card as self-contained HTML, for printing / saving as PDF.
 * Shows the same fields as the screen (card-view.tsx) and the image download.
 */

/** The card's printed labels, supplied already translated by the caller. */
export type HealthCardLabels = {
  brand: string;
  digitalId: string;
  phone: string;
  bloodGroup: string;
  allergies: string;
  emergency: string;
  issued: string;
  expires: string;
  scanToVerify: string;
};

export type HealthCardData = {
  fullName: string;
  userId: string;
  phone: string;
  blood: string;
  allergies: string;
  emergency: string;
  emergencyPhone: string;
  issuedDate: string;
  expiryDate: string;
  qrSvg: string; // raw svg string from qrMatrixToSvg
  labels: HealthCardLabels;
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

function field(label: string, value: string, colour?: string): string {
  return `<div style="min-width:0"><span style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:#94a3a8">${escapeXml(label)}</span><div style="font-size:14px;font-weight:600;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap${colour ? `;color:${colour}` : ""}">${escapeXml(value)}</div></div>`;
}

export function buildHealthCardHtml(d: HealthCardData): string {
  const qrPaths = extractPaths(d.qrSvg);
  const qrViewBox = extractViewBox(d.qrSvg);

  // HTML version for print/PDF — uses inline styles and Google Fonts
  return `<div style="width:640px;background:linear-gradient(135deg,#1e3a2e 0%,#000000 100%);border-radius:24px;padding:32px;position:relative;font-family:'Plus Jakarta Sans',Arial,sans-serif;color:#fff;box-sizing:border-box;overflow:hidden">
    <svg style="position:absolute;top:0;left:0;width:100%;height:100%;opacity:3%" viewBox="0 0 400 400" fill="none">
      <circle cx="200" cy="200" r="50" stroke="#ffffff" stroke-width="0.5"/>
      <circle cx="200" cy="200" r="120" stroke="#ffffff" stroke-width="0.3"/>
    </svg>
    <div style="margin-bottom:28px"><span style="font-size:26px;font-weight:800;letter-spacing:-0.5px">${escapeXml(d.labels.brand)}</span></div>
    <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#94e0c0;margin-bottom:12px">${escapeXml(d.labels.digitalId)}</div>
    <div style="margin-bottom:4px"><span style="font-family:'Newsreader',serif;font-size:32px;font-weight:700">${escapeXml(d.fullName)}</span></div>
    <div style="margin-bottom:24px"><span style="font-size:16px;font-weight:600;color:#94e0c0">${escapeXml(d.userId)}</span></div>
    <div style="display:flex;gap:24px;align-items:flex-start">
      <div style="flex-shrink:0;text-align:center">
        <svg width="132" height="132" viewBox="${qrViewBox}" style="background:#fff;border-radius:12px;padding:8px">${qrPaths}</svg>
        <div style="font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#94a3a8;margin-top:6px">${escapeXml(d.labels.scanToVerify)}</div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px 20px;flex:1;min-width:0">
        ${field(d.labels.phone, d.phone)}
        ${field(d.labels.bloodGroup, d.blood, d.blood !== "—" ? "#fca5a5" : undefined)}
        <div style="grid-column:1 / span 2;min-width:0"><span style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:#94a3a8">${escapeXml(d.labels.allergies)}</span><div style="font-size:14px;font-weight:600;margin-top:4px;line-height:1.35;overflow-wrap:anywhere">${escapeXml(d.allergies)}</div></div>
        <div style="min-width:0"><span style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:#94a3a8">${escapeXml(d.labels.emergency)}</span><div style="font-size:14px;font-weight:600;margin-top:4px;overflow-wrap:anywhere">${escapeXml(d.emergency)}</div>${d.emergencyPhone ? `<div style="font-size:13px;font-weight:600;margin-top:2px;opacity:0.85;white-space:nowrap">${escapeXml(d.emergencyPhone)}</div>` : ""}</div>
        ${field(d.labels.expires, d.expiryDate, "#6ee7b7")}
      </div>
    </div>
  </div>`;
}
