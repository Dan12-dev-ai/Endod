"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Bone, Skeleton } from "../components/skeleton";
import { FollowUpCards, QueueCard } from "./care-cards";
import {
  type BookingPreset, CATEGORY_LABEL, type HistoryResponse,
  type Share, TABS,
} from "./history-data";
import { AddVisitModal, ShareModal, SharesList } from "./history-modals";
import { MedicalRecordDetailView } from "./medical-record-detail-view";

/** While a record file is still arriving, the page asks again this often... */
const ARRIVING_POLL_MS = 10_000;
/** ...for at most this long. */
const ARRIVING_POLL_FOR_MS = 5 * 60_000;

type Props = {
  highlightTarget: string | null;
  onToast: (title: string, message: string) => void;
  /** Opens Settings, where consent is managed. */
  onOpenSettings: () => void;
  /** "Book now" on a follow-up. */
  onBook: (preset: BookingPreset) => void;
  /** When set, show the detail view for this record. */
  recordId?: string;
  onBack?: () => void;
  onSelectRecord?: (id: string) => void;
};

/**
 * Everything about the patient in one place: records from partner hospitals
 * (verified) and visits they added, by category, searchable and filterable
 * by date, with files to preview or download; follow-ups to book; sharing
 * with a hospital; and a printable copy.
 */
export default function HistoryView({ highlightTarget, onToast, onOpenSettings, onBook, recordId, onBack, onSelectRecord }: Props) {
  const { t, locale } = useI18n();
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loadError, setLoadError] = useState("");
  const [tab, setTab] = useState("all");
  const [adding, setAdding] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [shares, setShares] = useState<Share[] | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api<HistoryResponse>("users/me/history"));
      setLoadError("");
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : t("history.error.load"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is stable per language
  }, []);

  const loadShares = useCallback(async () => {
    try {
      setShares((await api<{ shares: Share[] }>("users/me/shares")).shares);
    } catch {
      setShares([]);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
    void loadShares();
  }, [load, loadShares]);

  const items = useMemo(() => data?.items ?? [], [data]);

  // A file still arriving shows up by itself: ask again every 10 s while any
  // is, for at most 5 minutes, and only while the page is visible.
  const arriving = useMemo(() => items.some((i) => i.files?.some((f) => f.state === "arriving")), [items]);
  useEffect(() => {
    if (!arriving) return;
    const until = Date.now() + ARRIVING_POLL_FOR_MS;
    let timer: ReturnType<typeof setInterval> | null = null;
    const stop = () => {
      if (timer !== null) clearInterval(timer);
      timer = null;
    };
    const tick = () => {
      if (Date.now() > until) stop();
      else void load();
    };
    const start = () => {
      if (timer === null && Date.now() <= until) timer = setInterval(tick, ARRIVING_POLL_MS);
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        if (Date.now() <= until) void load();
        start();
      } else {
        stop();
      }
    };
    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [arriving, load]);

  const shown = useMemo(() => {
    const matches = TABS.find((t) => t.id === tab)?.matches ?? (() => true);
    return items.filter(matches);
  }, [items, tab]);
  const summary = data?.summary;

  const formatDate = (iso: string) => new Date(iso).toLocaleDateString(locale, { dateStyle: "medium" });

  if (recordId) {
    return (
      <div className="flex-1 min-h-0 overflow-y-auto" data-purpose="medical-record-view">
        <MedicalRecordDetailView recordId={recordId} onBack={onBack} />
      </div>
    );
  }

  return (
    <div data-purpose="medical-record-view" className="flex-1 min-h-0 overflow-y-auto">
      <div className="w-full space-y-5 pb-6">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 dark:text-gray-100">{t("history.title")}</h1>
            </div>
          <div className="flex flex-nowrap gap-2 overflow-x-auto sm:flex-wrap sm:items-center self-start pb-1 -mb-1">
            <button type="button" data-purpose="add-record" onClick={() => setAdding(true)} className="shrink-0 px-3.5 py-2 rounded-full text-xs font-semibold bg-black hover:bg-gray-800 text-white shadow-sm">
              {t("records.addVisit")}
            </button>
            <button type="button" data-purpose="share-records" onClick={() => setSharing(true)} disabled={!items.length} className="shrink-0 px-3.5 py-2 rounded-full text-xs font-semibold border border-black text-black bg-white dark:bg-gray-800 hover:bg-gray-50 disabled:opacity-50">
              {t("history.share")}
            </button>
            <Link data-purpose="download-records" href="/history/print" target="_blank" rel="noopener" className="shrink-0 px-3.5 py-2 rounded-full text-xs font-semibold border border-slate-200 text-slate-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-slate-50 dark:hover:bg-gray-700">
              {t("history.download")}
            </Link>
          </div>
        </div>

        <QueueCard />
        <FollowUpCards onBook={onBook} highlight={highlightTarget} />

        {/* Summary */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { id: "stat-total", label: t("history.stat.total"), value: summary?.total },
            { id: "stat-verified", label: t("history.stat.verified"), value: summary?.verified },
            { id: "stat-hospitals", label: t("history.stat.hospitals"), value: summary?.hospitals },
            { id: "stat-self", label: t("history.stat.selfReported"), value: summary?.self_reported },
          ].map((stat) => (
            <div key={stat.id} data-purpose={stat.id} className="bg-white dark:bg-gray-800 rounded-2xl border border-slate-200 card-shadow p-3.5">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{stat.label}</p>
              {data ? (
                <p className="text-xl font-bold text-slate-900 dark:text-gray-100 leading-tight tabular-nums">{stat.value ?? 0}</p>
              ) : loadError ? (
                <p className="text-xl font-bold text-slate-300 leading-tight">—</p>
              ) : (
                <Bone className="h-6 w-12 rounded mt-0.5" />
              )}
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl border border-slate-200 card-shadow p-3 sm:p-4 mt-2">
          <div role="tablist" aria-label={t("history.categories")} className="flex gap-2.5 overflow-x-auto -mx-1 px-1 pb-1">
            {TABS.map((item) => (
              <button
                aria-selected={tab === item.id}
                className={`whitespace-nowrap px-4 py-2 rounded-full text-sm font-semibold border transition ${tab === item.id ? "bg-slate-900 text-white border-slate-900" : "bg-white dark:bg-gray-800 text-slate-600 border-slate-200 hover:bg-slate-50"}`}
                data-purpose={`history-tab-${item.id}`}
                key={item.id}
                onClick={() => setTab(item.id)}
                role="tab"
                type="button"
              >
                {t(item.labelKey)}
              </button>
            ))}
          </div>
        </div>

        {loadError && (
          <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">{loadError}</p>
        )}

        {/* Records */}
        {!data && !loadError ? (
          <Skeleton className="space-y-3" label={t("common.loading")}>
            {[0, 1, 2].map((i) => (
              <div className="bg-white dark:bg-gray-800 rounded-2xl border border-slate-200 p-4 space-y-2.5" key={i}>
                <Bone className="h-3 w-24 rounded" />
                <Bone className="h-4 w-2/3 rounded" />
                <Bone className="h-3 w-1/2 rounded" />
              </div>
            ))}
          </Skeleton>
        ) : data && !items.length ? (
          <p data-purpose="history-empty" className="bg-white dark:bg-gray-800 rounded-2xl border border-dashed border-slate-300 px-5 py-8 text-sm text-slate-500 text-center">{t("history.empty")}</p>
        ) : data && !shown.length ? (
          <p data-purpose="history-no-match" className="bg-white dark:bg-gray-800 rounded-2xl border border-dashed border-slate-300 px-5 py-8 text-sm text-slate-500 text-center">{t("history.noMatch")}</p>
        ) : (
          <ul className="space-y-3" data-purpose="history-list">
            {shown.map((item) => {
              const target = `record-${item.id}`;
              return (
                <li
                  className={`bg-white dark:bg-gray-800 rounded-2xl border card-shadow overflow-hidden ${highlightTarget === target ? "border-emerald-400 ring-2 ring-emerald-200" : "border-slate-200"}`}
                  data-category={item.category}
                  data-purpose="history-item"
                  data-record={item.id}
                  key={item.id}
                >
                  <div className="w-full text-left p-4 flex items-start gap-3 hover:bg-slate-50/60 dark:hover:bg-gray-700/60" role="button" tabIndex={0} onClick={() => onSelectRecord?.(item.id)}>
                    <span className={`mt-0.5 flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center text-[11px] font-bold ${item.kind === "hospital" ? "bg-emerald-50 text-emerald-700 border border-emerald-100" : "bg-slate-100 text-slate-500 border border-slate-200"}`} aria-hidden>
                      {t(CATEGORY_LABEL[item.category]).slice(0, 2)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{t(CATEGORY_LABEL[item.category])}</span>
                        <span data-purpose="record-source" className={`text-[10px] font-semibold rounded px-1.5 py-0.5 border ${item.verified ? "text-emerald-700 bg-emerald-50 border-emerald-200" : "text-slate-500 bg-slate-50 border-slate-200"}`}>
                          {item.verified ? t("records.verified") : t("records.selfReported")}
                        </span>
                      </span>
                      <span className="block text-sm sm:text-base font-semibold text-slate-900 dark:text-gray-100 mt-0.5 break-words">{item.title}</span>
                      <span className="block text-xs text-slate-500 mt-0.5">
                        {[formatDate(item.occurred_at), item.hospital_name, item.recorded_by].filter(Boolean).join(" · ")}
                      </span>
                      {item.files.length > 0 && (
                        <span className="block text-[11px] text-emerald-700 mt-1">{t(item.files.length === 1 ? "history.filesOne" : "history.filesOther", { count: item.files.length })}</span>
                      )}
                    </span>
                    <button aria-expanded={false} className="mt-1 flex-shrink-0 rounded-lg border border-slate-200 px-2 py-1 text-[11px] font-semibold text-slate-600 dark:text-gray-300 hover:bg-slate-50 dark:hover:bg-gray-700" data-purpose="record-open" onClick={(e) => { e.preventDefault(); e.stopPropagation(); onSelectRecord?.(item.id); }} type="button">
                      Open
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        <SharesList shares={shares} onChanged={loadShares} onToast={onToast} />
      </div>

      {adding && (
        <AddVisitModal
          onClose={() => setAdding(false)}
          onOpenSettings={onOpenSettings}
          onSaved={async () => {
            setAdding(false);
            onToast(t("records.toast.addedTitle"), t("records.toast.added"));
            await load();
          }}
        />
      )}
      {sharing && (
        <ShareModal
          items={items}
          onClose={() => setSharing(false)}
          onShared={async (share) => {
            setSharing(false);
            onToast(t("share.toastTitle"), t("share.toast", { hospital: share.hospital_name }));
            await loadShares();
          }}
        />
      )}
    </div>
  );
}

export { RecordDetails, FileRow, FilePreview } from "./record-parts";
