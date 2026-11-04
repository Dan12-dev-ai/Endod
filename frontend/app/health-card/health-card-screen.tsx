"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import QRCode from "qrcode";
import type { HealthCardLabels } from "./card-svg";
import { ApiError } from "../lib/api";
import HealthCardView from "./card-view";
import { fitAllergies, loadHealthCard, medicalLines, type HealthCardInfo } from "./health-card-data";
import { useI18n } from "../lib/i18n";
import { createPortal } from "react-dom";
import { Bone, HealthCardBones, Skeleton } from "../components/skeleton";


/**
 * The patient's Digital Health ID with its downloads. Used by the /health-card
 * page and, `embedded`, inside the mobile shell (/interview/mobile-card), where
 * the shell provides the page landmark, header and way back.
 */
export default function HealthCardScreen({ embedded = false }: { embedded?: boolean }) {
  const router = useRouter();
  const { t } = useI18n();
  const cardRef = useRef<HTMLDivElement>(null);

  // The card comes from the signed-in patient's profile.
  const [card, setCard] = useState<HealthCardInfo | null>(null);
  const [loadError, setLoadError] = useState("");
  const [isDownloading, setIsDownloading] = useState(false);
  const [qrOpen, setQrOpen] = useState(false);

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

  // The full-screen QR closes with Escape too.
  useEffect(() => {
    if (!qrOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setQrOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [qrOpen]);

  // A page of its own needs the <main> landmark; inside the mobile shell the
  // shell's <main> already is one.
  const Root = embedded ? "div" : "main";
  const rootClass = embedded
    ? "w-full flex items-center justify-center py-4 px-1 bg-white text-brand-primary font-sans antialiased"
    : "w-full min-h-screen flex items-center justify-center py-6 px-2 sm:py-12 sm:px-8 bg-white text-brand-primary font-sans antialiased";
  const mounted = card !== null;

  // Show a loading state during SSR / before mount to avoid hydration mismatch
  if (!mounted) {
    return (
      <Root className={rootClass}>
        <div className="w-full max-w-[720px] text-center">
          {loadError ? (
            <p className="text-sm text-[#B42318]" role="alert">{loadError}</p>
          ) : (
          <Skeleton className="bg-white rounded-[32px] border border-[#F4F7F7] p-6 sm:p-10 space-y-8" label={t("common.loading")}>
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
      </Root>
    );
  }

  const { fullName, userId, expiryDate, qrData } = card;
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


  const renderCardCanvas = async () => {
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
    grad.addColorStop(1, "#000000");
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
    // Drawn 1:1 at a whole number of pixels per module (scaling a QR code by
    // a fraction makes some modules wider than others, which scanners
    // misread), as large as fits the 132 px white box while leaving at
    // least 3 modules of white around it: the box is the quiet zone.
    const modules = QRCode.create(qrData, { errorCorrectionLevel: "M" }).modules.size;
    const scale = Math.max(1, Math.floor(132 / (modules + 6)));
    const qrCanvas = await QRCode.toCanvas(qrData, {
    scale,
    margin: 0,
    color: { dark: "#000000", light: "#ffffff" },
    errorCorrectionLevel: "M",
    });
    const qrSide = modules * scale;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(80, 268, 132, 132);
    ctx.drawImage(qrCanvas, 80 + Math.floor((132 - qrSide) / 2), 268 + Math.floor((132 - qrSide) / 2));

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

    // Details beside the QR code: phone | blood group; allergies across the
    // width; emergency contact (name, then phone) | expiry.
    const fitText = (text: string, maxWidth: number) => {
    if (ctx.measureText(text).width <= maxWidth) return text;
    let cut = text;
    while (cut.length > 1 && ctx.measureText(`${cut}…`).width > maxWidth) cut = cut.slice(0, -1);
    return `${cut}…`;
    };
    const label = (text: string, x: number, y: number) => {
    ctx.fillStyle = "#94a3a8";
    ctx.font = "bold 10px Arial";
    ctx.fillText(fitText(text.toUpperCase(), 200), x, y);
    };
    const value = (text: string, x: number, y: number, colour = "#ffffff", width = 200) => {
    ctx.fillStyle = colour;
    ctx.font = "bold 15px Arial";
    ctx.fillText(fitText(text, width), x, y);
    };
    label(labels.phone, 244, 276);
    value(phoneDisplay, 244, 296);
    label(labels.bloodGroup, 470, 276);
    value(lines.blood, 470, 296, card.medical?.bloodType ? "#fca5a5" : "#ffffff");

    label(labels.allergies, 244, 324);
    ctx.fillStyle = "#ffffff";
    let allergySize = 15;
    const allergyWidth = 426;
    const allergyFits = (text: string) => ctx.measureText(text).width <= allergyWidth;
    ctx.font = `bold ${allergySize}px Arial`;
    while (allergySize > 11 && !allergyFits(lines.allergies)) {
    allergySize -= 1;
    ctx.font = `bold ${allergySize}px Arial`;
    }
    ctx.fillText(fitAllergies(card.medical?.allergies ?? [], allergyFits), 244, 344);

    label(labels.emergency, 244, 372);
    value(lines.emergency, 244, 392);
    if (lines.emergencyPhone) {
    ctx.fillStyle = "rgba(255,255,255,0.8)";
    ctx.font = "bold 13px Arial";
    ctx.fillText(lines.emergencyPhone, 244, 410);
    }
    label(labels.expires, 470, 372);
    value(expiryDate, 470, 392, "#6ee7b7");


    return canvas;
  };


  const downloadAsPdf = async () => {
    setIsDownloading(true);
    try {
      const canvas = await renderCardCanvas();
      const imgData = canvas.toDataURL("image/png");
      // Loaded on demand: most visits never download a PDF.
      const { default: jsPDF } = await import("jspdf");
      const pdf = new jsPDF({ orientation: "landscape", unit: "px", format: [720, 480] });
      pdf.addImage(imgData, "PNG", 0, 0, 720, 480);
      pdf.save(`${userId}.pdf`);
    } catch (e) {
      console.error(e);
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
      const canvas = await renderCardCanvas();      // Trigger download
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
    <Root className={rootClass}>
      <div className="w-full max-w-[720px]">
        {/* ===== Digital Health Card ===== */}
        <div
          ref={cardRef}
          className="bg-white rounded-[32px] shadow-xl shadow-[#18242B]/10 border border-[#F4F7F7] p-3 sm:p-10 mb-8"
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
                className="flex-1 flex items-center justify-center gap-2 bg-app-green hover:bg-[#135a55] text-white font-medium py-3 px-4 rounded-full text-sm transition-all focus:outline-hidden disabled:opacity-60 disabled:cursor-not-allowed"
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
                className="flex-1 flex items-center justify-center gap-2 bg-app-green hover:bg-[#135a55] text-white font-medium py-3 px-4 rounded-full text-sm transition-all focus:outline-hidden disabled:opacity-60 disabled:cursor-not-allowed"
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
              className="text-lg text-brand-accent hover:underline font-semibold underline inline-flex items-center gap-1"
              data-purpose="show-qr"
              onClick={() => setQrOpen(true)}
              type="button"
            >
              {t("home.showQr")}
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>

          {!embedded && (
            <div className="mt-4 text-center">
              <button
                className="text-sm text-brand-accent hover:underline font-semibold"
                data-purpose="continue-to-app"
                onClick={() => router.push("/interview")}
                type="button"
              >
                {t("healthCard.continue")}
              </button>
            </div>
          )}
        </div>

        <p className="text-center text-[11px] text-brand-muted">
          {t("healthCard.footer")}
        </p>
      </div>
      {qrOpen && card?.qrSvg && createPortal(
        <div className="fixed inset-0 z-[100] bg-white flex flex-col items-center justify-center p-6" onClick={() => setQrOpen(false)} role="dialog" aria-modal="true" aria-label={t("healthCard.scanToVerify")}>
          <div className="w-full max-w-sm flex flex-col items-center text-center" onClick={(e) => e.stopPropagation()}>
            <p className="text-sm font-semibold text-[#25343D] uppercase tracking-wider">{t("healthCard.scanToVerify")}</p>
            <div className="w-full aspect-square max-w-[min(80vw,360px)] my-6" role="img" aria-label={t("healthCard.scanToVerify")} dangerouslySetInnerHTML={{ __html: card.qrSvg }} />
            <p className="text-2xl font-bold text-[#18242B]">{card.fullName}</p>
            <p className="text-base font-semibold text-app-green mt-1">{card.userId}</p>
            <button type="button" autoFocus onClick={() => setQrOpen(false)} className="mt-8 px-8 py-3 rounded-full border border-[#DCE4E6] text-[#25343D] font-semibold hover:bg-[#F4F7F7]">{t("common.close")}</button>
          </div>
        </div>,
        document.body
      )}
    </Root>
  );
}
