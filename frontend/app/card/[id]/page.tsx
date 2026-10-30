"use client";

// Where a Digital Health Card's QR code leads: /card/<DEDAN ID>?s=<signature>.
// Shows whether the card is genuine and, if so, only what is printed on it
// (name, ID, issue date), so a hospital desk can match it to the person.

import { useEffect, useState } from "react";
import { useI18n } from "@/app/lib/i18n";

type Holder = { dedan_user_id: string; full_name: string; issued_at: string };
type Result = { state: "checking" } | { state: "valid"; holder: Holder } | { state: "invalid" } | { state: "error" };

export default function CardCheckPage() {
  const { t } = useI18n();
  const [result, setResult] = useState<Result>({ state: "checking" });

  useEffect(() => {
    let cancelled = false;
    // Both read from the address here, after the page has rendered: the
    // page itself stays static, so it can be prerendered.
    const id = decodeURIComponent(window.location.pathname.split("/")[2] ?? "");
    const signature = new URLSearchParams(window.location.search).get("s") ?? "";
    const query = new URLSearchParams({ id, s: signature });
    fetch(`/api/cards/verify?${query}`, { cache: "no-store" })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (cancelled) return;
        if (response.ok && data?.ok) setResult({ state: "valid", holder: data as Holder });
        else setResult({ state: response.status === 404 ? "invalid" : "error" });
      })
      .catch(() => {
        if (!cancelled) setResult({ state: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="w-full min-h-screen flex items-center justify-center py-8 px-4 bg-[#DDE9E6] text-brand-primary font-sans antialiased">
      <div className="w-full max-w-[440px] bg-white dark:bg-gray-800 rounded-[28px] shadow-xl shadow-teal-950/5 border border-slate-100 p-8">
        <p className="text-2xl font-extrabold tracking-tight text-brand-heading mb-1">{t("common.endod")}</p>
        <h1 className="text-sm font-medium text-brand-muted mb-6">{t("cardVerify.title")}</h1>

        {result.state === "checking" && (
          <p className="text-sm text-brand-muted" role="status">{t("cardVerify.checking")}</p>
        )}

        {result.state === "valid" && (
          <div data-purpose="card-valid">
            <div className="flex items-center gap-3 mb-5">
              <span className="w-10 h-10 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
              <p className="text-lg font-bold text-emerald-800">{t("cardVerify.valid")}</p>
            </div>
            <dl className="space-y-3 text-sm">
              {[
                [t("cardVerify.name"), result.holder.full_name || "—"],
                [t("cardVerify.id"), result.holder.dedan_user_id],
                [t("cardVerify.issued"), result.holder.issued_at
                  ? new Date(result.holder.issued_at).toLocaleDateString("en-ET", { year: "numeric", month: "short", day: "numeric" })
                  : "—"],
              ].map(([label, value]) => (
                <div className="flex justify-between gap-4 border-b border-slate-100 pb-2" key={label}>
                  <dt className="text-brand-muted">{label}</dt>
                  <dd className="font-semibold text-brand-heading text-right">{value}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-5 text-xs text-brand-muted leading-relaxed">{t("cardVerify.validHint")}</p>
          </div>
        )}

        {result.state === "invalid" && (
          <div data-purpose="card-invalid" role="alert">
            <p className="text-lg font-bold text-red-700 mb-2">{t("cardVerify.invalid")}</p>
            <p className="text-sm text-brand-muted leading-relaxed">{t("cardVerify.invalidHint")}</p>
          </div>
        )}

        {result.state === "error" && (
          <p className="text-sm text-red-600" role="alert">{t("cardVerify.error")}</p>
        )}
      </div>
    </main>
  );
}
