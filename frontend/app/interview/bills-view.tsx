"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n, type TranslationKey } from "../lib/i18n";
import { RowBones } from "../components/skeleton";

type BillItem = { category: string; name: string; code?: string; amount: number; quantity: number };

type Bill = {
  id: string;
  hospital_name: string | null;
  items: BillItem[];
  subtotal: number;
  service_fee: number;
  total: number;
  currency: string;
  status: "open" | "paid" | "voided";
  paid_at: string | null;
  created_at: string;
};

type Bills = { items: Bill[]; open_total: number; currency: string };

/** Santim as birr with two decimals. */
function birr(santim: number): string {
  return (santim / 100).toFixed(2);
}

const STATUS: Record<Bill["status"], { key: TranslationKey; className: string }> = {
  open: { key: "bills.status.open", className: "bg-amber-50 text-amber-700 border-amber-200" },
  paid: { key: "bills.status.paid", className: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  voided: { key: "bills.status.voided", className: "bg-slate-100 text-slate-500 border-slate-200" },
};

/** The patient's bills from partner hospitals (GET /users/me/bills): paid at the hospital, Endod's fee included. */
export default function BillsView() {
  const { t, locale } = useI18n();
  const [bills, setBills] = useState<Bills | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api<Bills>("users/me/bills")
      .then((value) => {
        if (!cancelled) setBills(value);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : t("bills.error.load"));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on open
  }, []);

  return (
    <div data-purpose="bills-view" className="flex-1 min-h-0 overflow-y-auto">
      <div className="w-full space-y-6 pb-6">
        <div className="pb-6 border-b border-slate-200/80">
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">{t("bills.title")}</h1>
          <p className="text-sm text-slate-500 mt-1">{t("bills.subtitle")}</p>
          {bills && bills.open_total > 0 && (
            <p data-purpose="bills-open-total" className="mt-3 inline-flex px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200 text-sm font-semibold text-amber-800">
              {t("bills.openTotal", { amount: birr(bills.open_total) })}
            </p>
          )}
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        {!bills && !error && <RowBones />}
        {bills && bills.items.length === 0 && (
          <p data-purpose="bills-empty" className="text-sm text-slate-500">{t("bills.empty")}</p>
        )}

        {bills?.items.map((bill) => {
          const status = STATUS[bill.status] ?? STATUS.open;
          return (
            <section key={bill.id} data-purpose={`bill-${bill.id}`} className="bg-white rounded-2xl border border-slate-200 p-4 sm:p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-sm font-bold text-slate-900">{bill.hospital_name ?? t("bills.title")}</h2>
                  <p className="text-xs text-slate-400 mt-0.5">{new Date(bill.created_at).toLocaleDateString(locale)}</p>
                </div>
                <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium border ${status.className}`}>
                  {t(status.key)}
                </span>
              </div>
              <ul className="mt-3 divide-y divide-slate-100 text-sm">
                {bill.items.map((item, index) => (
                  <li key={index} className="flex justify-between py-1.5 text-slate-700">
                    <span>{item.name}{item.quantity > 1 ? ` × ${item.quantity}` : ""}</span>
                    <span className="tabular-nums">ETB {birr(item.amount * item.quantity)}</span>
                  </li>
                ))}
              </ul>
              <dl className="mt-3 pt-3 border-t border-slate-200 text-sm space-y-1">
                <div className="flex justify-between text-slate-600"><dt>{t("bills.subtotal")}</dt><dd className="tabular-nums">ETB {birr(bill.subtotal)}</dd></div>
                <div className="flex justify-between text-slate-600"><dt>{t("bills.fee")}</dt><dd className="tabular-nums" data-purpose="bill-fee">ETB {birr(bill.service_fee)}</dd></div>
                <div className="flex justify-between font-bold text-slate-900"><dt>{t("bills.total")}</dt><dd className="tabular-nums" data-purpose="bill-total">ETB {birr(bill.total)}</dd></div>
              </dl>
              {bill.status === "open" && (
                <p className="mt-3 text-xs text-slate-500">{t("bills.payAtHospital", { amount: birr(bill.total) })}</p>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
