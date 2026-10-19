"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import QRCode from "qrcode";
import { buildHealthCardHtml, type HealthCardData, type HealthCardLabels } from "./card-svg";
import { ApiError } from "../lib/api";
import HealthCardView from "./card-view";
import { loadHealthCard, medicalLines, type HealthCardInfo } from "./health-card-data";
import { useI18n } from "../lib/i18n";
import { Bone, HealthCardBones, Skeleton } from "../components/skeleton";


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
          <Skeleton className="bg-white rounded-[32px] border border-slate-100 p-6 sm:p-10 space-y-8" label={t("common.loading")}>
            <HealthCardBones />
            <div className="space-y-3 flex flex-col items-center">
              <Bone className="h-5 w-44 rounded" />
              <Bone className="h-3 w-64 rounded" />
            </div>
            <div className="flex gap-3">
              <Bone className="h-11 flex-1 rounded-full" />
              <Bone className="h-11 flex-1 rounded-full" />
            </div>
          </Skeleton>
          )}
        </div>
      </main>
    );
  }

  const { fullName, userId, issuedDate, expiryDate, qrData, qrSvg } = card;
  const phoneDisplay = card.phone;
  const lines = medicalLines(card.medical);

  // The printed labels travel with the generated card, so a download in
  // Amharic prints Amharic.
  const labels: HealthCardLabels = {
    brand: t("common.endod"),
    digitalId: t("healthCard.digitalId"),
    phone: t("healthCard.phone"),
    bloodGroup: t("healthCard.bloodGroup"),
    allergies: t("healthCard.allergies"),
    emergency: t("healthCard.emergency"),
    issued: t("healthCard.issued"),
    expires: t("healthCard.expires"),
    scanToVerify: t("healthCard.scanToVerify"),
  };

  const cardData: HealthCardData = {
    fullName,
    userId,
    phone: phoneDisplay,
    blood: lines.blood,
    allergies: lines.allergies,
    emergency: lines.emergencyPhone ? `${lines.emergency} · ${lines.emergencyPhone}` : lines.emergency,
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
      // A white margin of 4 modules (the QR "quiet zone") is part of the
      // code: without it, scanners cannot find the code on the dark card.
      const qrCanvas = await QRCode.toCanvas(qrData, {
        width: 264,
        margin: 4,
        color: { dark: "#000000", light: "#ffffff" },
        errorCorrectionLevel: "M",
      });
      ctx.imageSmoothingEnabled = false;
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

      // "Scan to verify" under the QR code
      ctx.fillStyle = "#94a3a8";
      ctx.font = "bold 10px Arial";
      ctx.textAlign = "center";
      ctx.fillText(labels.scanToVerify.toUpperCase(), 146, 420);
      ctx.textAlign = "left";

      // Details: two columns, three rows, beside the QR code
      const fitText = (text: string, maxWidth: number) => {
        if (ctx.measureText(text).width <= maxWidth) return text;
        let cut = text;
        while (cut.length > 1 && ctx.measureText(`${cut}…`).width > maxWidth) cut = cut.slice(0, -1);
        return `${cut}…`;
      };
      const grid: [string, string, string][] = [
        [labels.phone, phoneDisplay, "#ffffff"],
        [labels.bloodGroup, lines.blood, card.medical?.bloodType ? "#fca5a5" : "#ffffff"],
        [labels.allergies, lines.allergies, "#ffffff"],
        [labels.emergency, cardData.emergency, "#ffffff"],
        [labels.issued, issuedDate, "#ffffff"],
        [labels.expires, expiryDate, "#6ee7b7"],
      ];
      grid.forEach(([label, value, colour], i) => {
        const x = i % 2 === 0 ? 244 : 470;
        const y = 282 + Math.floor(i / 2) * 52;
        ctx.fillStyle = "#94a3a8";
        ctx.font = "bold 10px Arial";
        ctx.fillText(fitText(label.toUpperCase(), 200), x, y);
        ctx.fillStyle = colour;
        ctx.font = "bold 15px Arial";
        ctx.fillText(fitText(value, 200), x, y + 22);
      });

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
          <div className="mb-8">
            <HealthCardView card={card} />
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
