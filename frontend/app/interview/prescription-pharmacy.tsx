"use client";

import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { type TranslationKey, useI18n } from "../lib/i18n";
import { type Dispensing, rows, text } from "./history-data";

/**
 * The record's medicines by their index in the hospital's list
 * (`item_index`, kept when the platform drops an empty item). Records stored
 * before that carry none: their position is their index.
 */
function byIndex(items: Record<string, unknown>[]): Map<number, Record<string, unknown>> {
  const out = new Map<number, Record<string, unknown>>();
  items.forEach((medicine, position) => {
    const index = medicine.item_index;
    out.set(typeof index === "number" && Number.isInteger(index) && index >= 0 ? index : position, medicine);
  });
  return out;
}

/**
 * A hospital prescription at the pharmacy (docs/pharmacy.md section 3): the
 * QR to scan, the 6-digit code (shown with the patient's phone number),
 * until when it works, what has been given of each medicine, and where.
 * The QR is drawn here in the browser; it only carries the signed link.
 */
export function PrescriptionPharmacy({ rx, details }: { rx: Dispensing; details: Record<string, unknown> }) {
  const { t, locale } = useI18n();
  const [qr, setQr] = useState<string | null>(null);
  const medicines = byIndex(rows(details.items));

  useEffect(() => {
    let cancelled = false;
    if (!rx.qr_url) return;
    QRCode.toDataURL(rx.qr_url, { errorCorrectionLevel: "M", margin: 2, width: 512 })
      .then((url) => {
        if (!cancelled) setQr(url);
      })
      .catch(() => {
        if (!cancelled) setQr(null);
      });
    return () => {
      cancelled = true;
    };
  }, [rx.qr_url]);

  const usable = rx.status === "open";
  const day = new Date(rx.expires_at).toLocaleDateString(locale, { dateStyle: "medium" });
  const when = (iso: string) =>
    new Date(iso).toLocaleString(locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const amount = (n: number | null) => (n === null ? "" : n.toLocaleString(locale));

  const itemStatus = (item: Dispensing["items"][number]) => {
    if (item.status === "given") return t("rx.item.given");
    if (item.status === "partly_given") {
      return item.quantity_total !== null && item.given_total !== null
        ? t("rx.item.partly", { given: amount(item.given_total), total: amount(item.quantity_total) })
        : item.given_total !== null
          ? t("rx.item.partlyNoTotal", { given: amount(item.given_total) })
          : t("rx.item.partlyNoCount");
    }
    return t("rx.item.notGiven");
  };

  const STATUS_STYLE: Record<Dispensing["status"], string> = {
    open: "text-black bg-gray-50 border-gray-200",
    completed: "text-slate-700 bg-slate-100 border-slate-200",
    expired: "text-amber-800 bg-amber-50 border-amber-200",
    retracted: "text-red-800 bg-red-50 border-red-200",
  };

  return (
    <section aria-label={t("rx.title")} className="rounded-2xl border border-gray-200 bg-gray-50/40 p-3 sm:p-4 space-y-3" data-purpose="rx-pharmacy" data-status={rx.status}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-bold text-slate-900">{t("rx.title")}</h3>
        <span className={`text-[11px] font-semibold rounded-full px-2 py-0.5 border ${STATUS_STYLE[rx.status]}`} data-purpose="rx-status">
          {t(`rx.status.${rx.status}` as TranslationKey)}
        </span>
      </div>

      {usable && (
        <div className="flex flex-col sm:flex-row sm:items-center gap-4">
          {rx.qr_url && (
            <div className="mx-auto sm:mx-0 w-full max-w-[280px] aspect-square rounded-xl bg-white border border-slate-200 p-2 flex items-center justify-center">
              {qr ? (
                // eslint-disable-next-line @next/next/no-img-element -- a data URL drawn in the browser
                <img alt={t("rx.qrAlt")} className="w-full h-full [image-rendering:pixelated]" data-purpose="rx-qr" src={qr} />
              ) : (
                <span className="text-xs text-slate-400">{t("common.loading")}</span>
              )}
            </div>
          )}
          <div className="space-y-2 min-w-0">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{t("rx.code")}</p>
              <p className="text-3xl font-bold tracking-[0.2em] tabular-nums text-slate-900" data-purpose="rx-code">{rx.code}</p>
            </div>
            <p className="text-xs text-slate-600">{t("rx.howTo")}</p>
            <p className="text-xs font-semibold text-slate-700" data-purpose="rx-expiry">{t("rx.validUntil", { date: day })}</p>
          </div>
        </div>
      )}
      {!usable && (
        <p className="text-xs text-slate-600" data-purpose="rx-expiry">
          {rx.status === "expired" ? t("rx.expiredOn", { date: day }) : rx.status === "completed" ? t("rx.completedNote") : t("rx.retractedNote")}
        </p>
      )}

      {rx.items.length > 0 && (
        <ul className="space-y-1.5" data-purpose="rx-items">
          {rx.items.map((item) => {
            const medicine = medicines.get(item.item_index) ?? {};
            return (
              <li className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 rounded-xl bg-white border border-slate-200 px-3 py-2" data-purpose="rx-item" data-status={item.status} key={item.item_index}>
                <span className="min-w-0 text-sm font-medium text-slate-800 break-words">
                  {[text(medicine.drug), text(medicine.dose)].filter(Boolean).join(" ") || t("rx.item.unnamed", { n: item.item_index + 1 })}
                  {item.quantity_text && <span className="block text-[11px] font-normal text-slate-500">{t("history.rx.quantity", { quantity: item.quantity_text })}</span>}
                </span>
                <span className={`text-xs font-semibold ${item.status === "given" ? "text-black" : item.status === "partly_given" ? "text-amber-700" : "text-slate-500"}`} data-purpose="rx-item-status">
                  {itemStatus(item)}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1">{t("rx.dispenses")}</p>
        {rx.dispenses.length === 0 ? (
          <p className="text-xs text-slate-500" data-purpose="rx-no-dispenses">{t("rx.noDispenses")}</p>
        ) : (
          <>
            <ul className="space-y-1" data-purpose="rx-dispenses">
              {rx.dispenses.map((d, i) => (
                <li className="text-sm text-slate-800 break-words" data-purpose="rx-dispense" key={`${d.at}-${i}`}>
                  {t("rx.dispensedAt", { pharmacy: d.pharmacy_name, when: when(d.at) })}
                </li>
              ))}
            </ul>
            <p className="text-[11px] text-slate-400 mt-1">{t("rx.namesAsTyped")}</p>
          </>
        )}
      </div>
    </section>
  );
}
