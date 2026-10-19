"use client";

// The Digital Health Card as it appears on screen: on the /health-card page
// and first on the dashboard's Overview. Sizes scale with the card's own
// width (container query units), so it reads the same on a phone and a laptop.

import { useI18n } from "../lib/i18n";
import { medicalLines, type HealthCardInfo } from "./health-card-data";

export default function HealthCardView({ card }: { card: HealthCardInfo }) {
  const { t } = useI18n();
  const lines = medicalLines(card.medical);
  // Allergies get the full width and up to two lines: an allergy cut off
  // the card could read as absent.
  const fields: { label: string; value: string; sub?: string; purpose: string; accent?: boolean; wide?: boolean }[] = [
    { label: t("healthCard.phone"), value: card.phone, purpose: "phone-value" },
    { label: t("healthCard.bloodGroup"), value: lines.blood, purpose: "blood-value", accent: Boolean(card.medical?.bloodType) },
    { label: t("healthCard.allergies"), value: lines.allergies, purpose: "allergies-value", wide: true },
    { label: t("healthCard.emergency"), value: lines.emergency, sub: lines.emergencyPhone, purpose: "emergency-value" },
    { label: t("healthCard.expires"), value: card.expiryDate, purpose: "expiry-date" },
  ];

  return (
    <div
      className="relative w-full rounded-2xl overflow-hidden bg-gradient-to-br from-[#1e3a2e] via-[#1e4d43] to-[#1e5852] text-white shadow-lg"
      data-purpose="health-card-preview"
      style={{ aspectRatio: "1.586 / 1", containerType: "inline-size" }}
    >
      {/* Subtle diagonal sheen */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{ background: "linear-gradient(115deg, rgba(255,255,255,0.10) 0%, rgba(255,255,255,0) 42%, rgba(0,0,0,0.14) 100%)" }}
      />
      {/* Decorative concentric rings (top-right) */}
      <div className="absolute -top-16 -right-16 w-56 h-56 opacity-[0.06] pointer-events-none" aria-hidden="true">
        <svg className="w-full h-full" viewBox="0 0 200 200" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="100" cy="100" r="40" stroke="currentColor" strokeWidth="0.5" />
          <circle cx="100" cy="100" r="70" stroke="currentColor" strokeWidth="0.5" />
          <circle cx="100" cy="100" r="98" stroke="currentColor" strokeWidth="0.5" />
        </svg>
      </div>

      <div className="relative h-full flex flex-col justify-between" style={{ padding: "clamp(12px, 4.2cqi, 28px)" }}>
        {/* Top row: brand, name and ID */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <span className="block font-extrabold tracking-tight leading-none" style={{ fontSize: "clamp(15px, 4.6cqi, 30px)" }}>
              {t("common.endod")}
            </span>
            <span
              className="block font-semibold text-[#94e0c0] uppercase tracking-[0.18em] mt-1 truncate"
              style={{ fontSize: "clamp(6px, 1.7cqi, 11px)" }}
            >
              {t("healthCard.digitalId")}
            </span>
            <p className="font-bold font-serif text-white truncate" style={{ fontSize: "clamp(14px, 4.6cqi, 28px)", marginTop: "clamp(6px, 3cqi, 20px)" }} data-purpose="full-name">
              {card.fullName}
            </p>
            <p className="font-semibold text-[#94e0c0] truncate" style={{ fontSize: "clamp(9px, 2.6cqi, 15px)" }} data-purpose="user-id">
              {card.userId}
            </p>
          </div>
          {/* Contactless tap icon */}
          <svg
            className="shrink-0 text-white/85"
            style={{ width: "clamp(16px, 4.5cqi, 28px)", height: "clamp(16px, 4.5cqi, 28px)" }}
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

        {/* Bottom row: details on the left, the QR code on the right */}
        <div className="flex items-end justify-between gap-3">
          <dl className="grid grid-cols-2 flex-1 min-w-0" style={{ fontSize: "clamp(7px, 1.9cqi, 12px)", columnGap: "clamp(8px, 3cqi, 20px)", rowGap: "clamp(3px, 1.2cqi, 8px)" }}>
            {fields.map((field) => (
              <div className={`min-w-0 ${field.wide ? "col-span-2" : ""}`} key={field.purpose}>
                <dt className="font-semibold text-[#94a3a8] uppercase tracking-wider truncate">{field.label}</dt>
                <dd
                  className={`font-semibold ${field.wide ? "line-clamp-2 break-words" : "truncate"} ${field.accent ? "text-[#fca5a5]" : "text-white"}`}
                  data-purpose={field.purpose}
                  title={field.wide ? field.value : undefined}
                >
                  {field.value}
                  {field.sub && <span className="block font-medium text-white/75 truncate">{field.sub}</span>}
                </dd>
              </div>
            ))}
          </dl>

          {card.qrSvg && (
            <div
              className="shrink-0 bg-white rounded-lg flex items-center justify-center"
              style={{ padding: "clamp(4px, 1.4cqi, 10px)" }}
              data-purpose="qr-code"
            >
              <div
                aria-label={t("healthCard.scanToVerify")}
                role="img"
                style={{ width: "clamp(64px, 24cqi, 150px)", height: "clamp(64px, 24cqi, 150px)" }}
                dangerouslySetInnerHTML={{ __html: card.qrSvg }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
