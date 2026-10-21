"use client";

// "Download my records": every record on one plain page, to print or save as
// PDF from the browser's print dialog. Nothing is sent anywhere; the page
// reads the same API as the History screen.

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Bone, Skeleton } from "../../components/skeleton";
import { RecordDetails } from "../../interview/history-view";
import { CATEGORY_LABEL, type HistoryResponse } from "../../interview/history-data";

type Profile = { dedan_user_id: string; first_name?: string | null; middle_name?: string | null; last_name?: string | null };

export default function PrintRecordsPage() {
  const { t, locale } = useI18n();
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([api<HistoryResponse>("users/me/history"), api<Profile>("users/me")])
      .then(([history, me]) => {
        if (cancelled) return;
        setData(history);
        setProfile(me);
      })
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : t("history.error.load")));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  }, []);

  const name = profile ? [profile.first_name, profile.middle_name, profile.last_name].filter(Boolean).join(" ") || profile.dedan_user_id : "";

  return (
    <main className="min-h-screen bg-white text-slate-900 px-4 py-6 sm:px-10 print:p-0" data-purpose="print-records">
      <div className="max-w-3xl mx-auto">
        <div className="flex flex-wrap items-center justify-between gap-3 print:hidden mb-6">
          <Link href="/interview" className="text-sm font-semibold text-emerald-700 hover:underline">← {t("print.back")}</Link>
          <button
            className="px-4 py-2 rounded-xl bg-slate-900 text-white text-sm font-semibold disabled:opacity-50"
            data-purpose="print-button"
            disabled={!data}
            onClick={() => window.print()}
            type="button"
          >
            {t("print.print")}
          </button>
        </div>
        <header className="border-b-2 border-slate-900 pb-3 mb-4">
          <p className="text-xs font-bold tracking-widest uppercase text-emerald-700">Endod Health</p>
          <h1 className="text-2xl font-bold">{t("print.title")}</h1>
          {profile && (
            <p className="text-sm text-slate-600 mt-1" data-purpose="print-patient">
              {t("print.prepared", { date: new Date().toLocaleDateString(locale, { dateStyle: "long" }), name, id: profile.dedan_user_id })}
            </p>
          )}
        </header>
        {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
        {!data && !error && (
          <Skeleton className="space-y-4" label={t("common.loading")}>
            {[0, 1, 2].map((i) => (
              <div className="space-y-2" key={i}>
                <Bone className="h-4 w-1/2 rounded" />
                <Bone className="h-3 w-5/6 rounded" />
              </div>
            ))}
          </Skeleton>
        )}
        {data && !data.items.length && <p className="text-sm text-slate-500">{t("print.empty")}</p>}
        {data && data.items.length > 0 && (
          <ol className="space-y-4">
            {data.items.map((item) => (
              <li className="break-inside-avoid border-b border-slate-200 pb-4" data-purpose="print-item" key={item.id}>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  {[t(CATEGORY_LABEL[item.category]), new Date(item.occurred_at).toLocaleDateString(locale, { dateStyle: "medium" }),
                    item.verified ? t("records.verified") : t("records.selfReported")].join(" · ")}
                </p>
                <h2 className="text-base font-bold">{item.title}</h2>
                <p className="text-xs text-slate-600 mb-2">{[item.hospital_name, item.recorded_by].filter(Boolean).join(" · ")}</p>
                <RecordDetails item={item} />
                {item.files.length > 0 && (
                  <p className="text-xs text-slate-500 mt-2">
                    {t("history.files")}: {item.files.map((f) => f.filename).join(", ")}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </main>
  );
}
