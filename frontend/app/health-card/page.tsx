"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import QRCode from "qrcode";
import { buildHealthCardHtml, type HealthCardData, type HealthCardLabels } from "./card-svg";
import { ApiError } from "../lib/api";
import { loadHealthCard, type HealthCardInfo } from "./health-card-data";
import { useI18n } from "../lib/i18n";


// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function HealthCardPage() {
  const router = useRouter();
  const { t } = useI18n();
  const cardRef = useRef<HTMLDivElement>(null);

  // The card comes from the signed-in patient's profile.
  const [card, setCard] = useState<HealthCardInfo | null>(null);
  const [loadError, setLoadError] = useState("");
  const [isDownloading, setIsDownloading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadHealthCard()
      .then((info) => {
        if (!cancelled) setCard(info);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(error instanceof ApiError ? error.message : t("healthCard.loadError"));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once on mount
  }, []);
  const mounted = card !== null;

  // Show a loading state during SSR / before mount to avoid hydration mismatch
  if (!mounted) {
    return (
      <main className="w-full min-h-screen flex items-center justify-center py-6 px-2 sm:py-12 sm:px-8 bg-[#DDE9E6] text-brand-primary font-sans antialiased">
        <div className="w-full max-w-[720px] text-center">
          {loadError ? (
            <p className="text-sm text-red-600" role="alert">{loadError}</p>
          ) : (
          <div className="animate-pulse">
            <div className="h-4 bg-slate-200 rounded w-32 mx-auto mb-4"></div>
            <div className="h-3 bg-slate-200 rounded w-48 mx-auto"></div>
          </div>
          )}
        </div>
      </main>
    );
  }

  const { fullName, userId, issuedDate, expiryDate, qrData, qrSvg } = card;
  const phoneDisplay = card.phone;

  // The printed labels travel with the generated card, so a download in
  // Amharic prints Amharic.
  const labels: HealthCardLabels = {
    brand: t("common.endod"),
    digitalId: t("healthCard.digitalId"),
    phone: t("healthCard.phone"),
    patientId: t("healthCard.patientId"),
    issued: t("healthCard.issued"),
    expires: t("healthCard.expires"),
    scanToVerify: t("healthCard.scanToVerify"),
  };

  const cardData: HealthCardData = {
    fullName,
    userId,
    phone: phoneDisplay,
    issuedDate,
    expiryDate,
    qrSvg,
    labels,
  };

  const cardHtml = buildHealthCardHtml(cardData);

  const downloadAsPdf = () => {
    setIsDownloading(true);
    try {
      const printWindow = window.open("", "_blank", "width=720,height=480");
      if (!printWindow) return;
      printWindow.document.write(`
        <!DOCTYPE html>
        <html lang="${document.documentElement.lang || "en"}">
        <head>
          <meta charset="utf-8" />
          <style>
            @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Newsreader:wght@400;500;600;700&family=Noto+Sans+Ethiopic:wght@400;500;600;700&display=swap');
            body { margin: 0; padding: 0; background: #dde9e6; font-family: 'Plus Jakarta Sans', Arial, sans-serif; }
            .page { width: 720px; height: 480px; margin: 0 auto; padding: 40px; box-sizing: border-box; }
          </style>
        </head>
        <body>
          <div class="page">${cardHtml}</div>
          <script>
            window.onload = function() {
              window.print();
              setTimeout(function() { window.close(); }, 1000);
            };
          </script>
        </body>
        </html>
      `);
      printWindow.document.close();
    } catch {
      alert(t("healthCard.printError"));
    } finally {
      setIsDownloading(false);
    }
  };

    // ---------------------------------------------------------------------------
  // Image download — renders the health card directly on canvas using
  // the qrcode library's toCanvas for the QR portion.  This avoids the
  // unreliable SVG-as-image-in-canvas path (gradients / <foreignObject>
  // taint the canvas in Chrome).
  // ---------------------------------------------------------------------------

  const downloadAsImage = async () => {
    setIsDownloading(true);
    try {
      // Create a canvas and draw the card manually using Canvas 2D API.
      // We use the qrcode library's toCanvas for the QR portion to guarantee
      // a scannable code, then draw all other elements with fillText/rect.
      const canvas = document.createElement("canvas");
      canvas.width = 720;
      canvas.height = 480;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Canvas unavailable");

      // White background
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Gradient card background with rounded corners
      const grad = ctx.createLinearGradient(40, 40, 680, 440);
      grad.addColorStop(0, "#1e3a2e");
      grad.addColorStop(1, "#1e5852");
      ctx.fillStyle = grad;
      ctx.beginPath();
      const radius = 24;
      ctx.moveTo(40 + radius, 40);
      ctx.lineTo(680 - radius, 40);
      ctx.arcTo(680, 40, 680, 80, radius);
      ctx.lineTo(680, 440 - radius);
      ctx.arcTo(680, 440, 680 - radius, 440, radius);
      ctx.lineTo(40 + radius, 440);
      ctx.arcTo(40, 440, 40, 440 - radius, radius);
      ctx.lineTo(40, 40 + radius);
      ctx.arcTo(40, 40, 40 + radius, 40, radius);
      ctx.fill();

      // Render QR code via qrcode library
      const qrCanvas = await QRCode.toCanvas(qrData, {
        width: 120,
        margin: 0,
        color: { dark: "#000000", light: "#ffffff" },
        errorCorrectionLevel: "M",
      });
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(80, 268, 132, 132);
      ctx.drawImage(qrCanvas, 80, 268, 132, 132);

      // Brand
      ctx.fillStyle = "#94e0c0";
      ctx.font = "bold 11px Arial";
      ctx.fillText(labels.digitalId.toUpperCase(), 80, 152);

      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 26px Arial";
      ctx.fillText(labels.brand, 80, 120);

      ctx.fillStyle = "#6ee7b7";
      ctx.font = "bold 16px Arial";
      ctx.fillText(userId, 80, 240);

      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 32px Georgia";
      ctx.fillText(fullName, 80, 200);

      // Info grid labels
      ctx.fillStyle = "#94a3a8";
      ctx.font = "bold 10px Arial";
      ctx.fillText(labels.phone.toUpperCase(), 244, 300);
      ctx.fillText(labels.patientId.toUpperCase(), 494, 300);
      ctx.fillText(labels.issued.toUpperCase(), 244, 366);
      ctx.fillText(labels.expires.toUpperCase(), 494, 366);

      // Field values
      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 15px Arial";
      ctx.fillText(phoneDisplay, 244, 328);
      ctx.fillText(userId, 494, 328);
      ctx.fillText(issuedDate, 244, 394);
      ctx.fillStyle = "#6ee7b7";
      ctx.fillText(expiryDate, 494, 394);

      // Footer
      ctx.strokeStyle = "rgba(255,255,255,0.1)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(80, 384);
      ctx.lineTo(680, 384);
      ctx.stroke();
      ctx.fillStyle = "#94a3a8";
      ctx.font = "11px Arial";
      ctx.fillText(`${labels.issued} ${issuedDate}`, 80, 416);

      // Trigger download
      const link = document.createElement("a");
      link.href = canvas.toDataURL("image/png");
      link.download = `${userId}.png`;
      link.click();
    } catch (e) {
      console.error("Image download error:", e);
      alert(t("healthCard.imageError"));
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <main className="w-full min-h-screen flex items-center justify-center py-6 px-2 sm:py-12 sm:px-8 bg-[#DDE9E6] text-brand-primary font-sans antialiased">
      <div className="w-full max-w-[720px]">
        {/* ===== Digital Health Card ===== */}
        <div
          ref={cardRef}
          className="bg-white rounded-[32px] shadow-xl shadow-teal-950/10 border border-slate-100 p-3 sm:p-10 mb-8"
          data-purpose="health-card-wrapper"
        >
          {/* ===== Card Preview (Mastercard-style, fixed aspect ratio) ===== */}
          <div
            className="relative w-full rounded-2xl mb-8 overflow-hidden bg-gradient-to-br from-[#1e3a2e] via-[#1e4d43] to-[#1e5852] text-white shadow-lg"
            data-purpose="health-card-preview"
            style={{ aspectRatio: "1.586 / 1", containerType: "inline-size" }}
          >
            {/* Subtle diagonal sheen */}
            <div
              className="absolute inset-0 pointer-events-none"
              style={{ background: "linear-gradient(115deg, rgba(255,255,255,0.10) 0%, rgba(255,255,255,0) 42%, rgba(0,0,0,0.14) 100%)" }}
            />
            {/* Decorative concentric rings (top-right) */}
            <div className="absolute -top-16 -right-16 w-56 h-56 opacity-[0.06] pointer-events-none">
              <svg className="w-full h-full" viewBox="0 0 200 200" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="100" cy="100" r="40" stroke="currentColor" strokeWidth="0.5" />
                <circle cx="100" cy="100" r="70" stroke="currentColor" strokeWidth="0.5" />
                <circle cx="100" cy="100" r="98" stroke="currentColor" strokeWidth="0.5" />
              </svg>
            </div>

            {/* Inner padding scales with card width via clamp */}
            <div
              className="relative h-full flex flex-col justify-between"
              style={{ padding: "clamp(14px, 4.5cqi, 28px)" }}
            >
              {/* Top row: brand + card type */}
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <span
                    className="block font-extrabold tracking-tight leading-none"
                    style={{ fontSize: "clamp(16px, 5cqi, 30px)" }}
                  >
                    {t("common.endod")}
                  </span>
                  <span
                    className="block font-semibold text-[#94e0c0] uppercase tracking-[0.18em] mt-1 truncate"
                    style={{ fontSize: "clamp(7px, 1.8cqi, 11px)" }}
                  >
                    {t("healthCard.digitalId")}
                  </span>
                </div>
                {/* Contactless tap icon */}
                <svg
                  className="shrink-0 text-white/85"
                  style={{ width: "clamp(18px, 5cqi, 28px)", height: "clamp(18px, 5cqi, 28px)" }}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.8}
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path d="M8.5 8.5a5 5 0 0 1 0 7" strokeLinecap="round" />
                  <path d="M12 6a8 8 0 0 1 0 12" strokeLinecap="round" />
                  <path d="M15.5 3.5a11 11 0 0 1 0 17" strokeLinecap="round" />
                </svg>
              </div>

              {/* Middle row: chip + name + ID */}
              <div className="flex items-center gap-3 sm:gap-4 min-w-0">
                {/* EMV-style chip */}
                <div
                  className="shrink-0 rounded-md bg-gradient-to-br from-[#e8c96a] via-[#d4af37] to-[#b8962e] flex items-center justify-center shadow-sm"
                  style={{ width: "clamp(30px, 9cqi, 52px)", height: "clamp(23px, 7cqi, 40px)" }}
                  aria-hidden="true"
                >
                  <svg viewBox="0 0 40 32" className="w-full h-full" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="1" y="1" width="38" height="30" rx="5" stroke="rgba(120,90,20,0.55)" strokeWidth="1" />
                    <path d="M1 11h12M27 11h12M1 21h12M27 21h12M13 1v10M13 21v10M27 1v10M27 21v10" stroke="rgba(120,90,20,0.45)" strokeWidth="1" />
                  </svg>
                </div>
                <div className="min-w-0 flex-1">
                  <p
                    className="font-bold font-serif text-white truncate"
                    style={{ fontSize: "clamp(14px, 4.5cqi, 28px)" }}
                    data-purpose="full-name"
                  >
                    {fullName}
                  </p>
                  <p
                    className="font-semibold text-[#94e0c0] truncate mt-0.5"
                    style={{ fontSize: "clamp(9px, 2.4cqi, 14px)" }}
                    data-purpose="user-id"
                  >
                    {userId}
                  </p>
                </div>
              </div>

              {/* Bottom row: info fields + QR + Mastercard circles */}
              <div className="flex items-end justify-between gap-3">
                {/* Info grid */}
                <div
                  className="grid grid-cols-2 gap-x-4 gap-y-1 flex-1 min-w-0"
                  style={{ fontSize: "clamp(7px, 1.9cqi, 11px)" }}
                >
                  <div className="min-w-0">
                    <span className="block font-semibold text-[#94a3a8] uppercase tracking-wider">{t("healthCard.phone")}</span>
                    <p className="font-semibold text-white truncate" data-purpose="phone-value">{phoneDisplay}</p>
                  </div>
                  <div className="min-w-0">
                    <span className="block font-semibold text-[#94a3a8] uppercase tracking-wider">{t("healthCard.patientId")}</span>
                    <p className="font-semibold text-white truncate" data-purpose="id-value">{userId}</p>
                  </div>
                  <div className="min-w-0">
                    <span className="block font-semibold text-[#94a3a8] uppercase tracking-wider">{t("healthCard.issued")}</span>
                    <p className="font-medium text-white/85 truncate" data-purpose="issue-date">{issuedDate}</p>
                  </div>
                  <div className="min-w-0">
                    <span className="block font-semibold text-[#94a3a8] uppercase tracking-wider">{t("healthCard.expires")}</span>
                    <p className="font-semibold text-[#6ee7b7] truncate" data-purpose="expiry-date">{expiryDate}</p>
                  </div>
                </div>

                {/* QR code */}
                <div
                  className="shrink-0 bg-white rounded-lg flex items-center justify-center"
                  style={{ padding: "clamp(5px, 1.5cqi, 10px)" }}
                  data-purpose="qr-code"
                >
                  <div
                    style={{ width: "clamp(76px, 20cqi, 128px)", height: "clamp(76px, 20cqi, 128px)" }}
                    dangerouslySetInnerHTML={{ __html: qrSvg }}
                  />
                </div>

                {/* Mastercard-style interlocking circles */}
                <div className="shrink-0 flex items-center" aria-hidden="true">
                  <div
                    className="rounded-full bg-[#eb001b] mix-blend-screen opacity-90"
                    style={{ width: "clamp(22px, 7cqi, 46px)", height: "clamp(22px, 7cqi, 46px)" }}
                  />
                  <div
                    className="rounded-full bg-[#f79e1b] mix-blend-screen opacity-90 -ml-[35%]"
                    style={{ width: "clamp(22px, 7cqi, 46px)", height: "clamp(22px, 7cqi, 46px)" }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* ===== Download Options ===== */}
          <div data-purpose="download-options">
            <h3 className="font-serif text-xl font-medium text-brand-heading mb-4 text-center">
              {t("healthCard.downloadTitle")}
            </h3>
            <p className="text-sm text-brand-muted text-center mb-6">
              {t("healthCard.downloadBody")}
            </p>
            <div className="flex flex-col sm:flex-row gap-3">
              <button
                className="flex-1 flex items-center justify-center gap-2 bg-[#E5ECEB] hover:bg-[#D5E3E0] text-brand-heading font-medium py-3 px-4 rounded-full text-sm transition-all focus:outline-hidden disabled:opacity-60 disabled:cursor-not-allowed"
                data-purpose="download-pdf"
                disabled={isDownloading}
                onClick={downloadAsPdf}
                type="button"
              >
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.5}
                  viewBox="0 0 24 24"
                >
                  <path
                    d="M3 17v2a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2M5 10l7 7 7-7M10 15V3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                {isDownloading ? t("healthCard.preparing") : t("healthCard.downloadPdf")}
              </button>
              <button
                className="flex-1 flex items-center justify-center gap-2 bg-[#E5ECEB] hover:bg-[#D5E3E0] text-brand-heading font-medium py-3 px-4 rounded-full text-sm transition-all focus:outline-hidden disabled:opacity-60 disabled:cursor-not-allowed"
                data-purpose="download-image"
                disabled={isDownloading}
                onClick={downloadAsImage}
                type="button"
              >
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.5}
                  viewBox="0 0 24 24"
                >
                  <path
                    d="M3 17v2a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2M5 10l7 7 7-7M10 15V3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                {isDownloading ? t("healthCard.preparing") : t("healthCard.downloadImage")}
              </button>
            </div>
          </div>

          {/* ===== Continue to App ===== */}
          <div className="mt-8 text-center">
            <button
              className="text-sm text-brand-accent hover:underline font-semibold"
              data-purpose="continue-to-app"
              onClick={() => router.push("/interview")}
              type="button"
            >
              {t("healthCard.continue")}
            </button>
          </div>
        </div>

        <p className="text-center text-[11px] text-brand-muted">
          {t("healthCard.footer")}
        </p>
      </div>
    </main>
  );
}
