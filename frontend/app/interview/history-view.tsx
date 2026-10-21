"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n, type TranslationKey } from "../lib/i18n";
import { Bone, Skeleton } from "../components/skeleton";
import { FollowUpCards, QueueCard } from "./care-cards";
import {
  type BookingPreset, CATEGORY_LABEL, fileUrl, filterItems, formatSize, type HistoryItem, type HistoryResponse,
  type RecordFile, rows, type Share, TABS, text,
} from "./history-data";
import { AddVisitModal, ShareModal, SharesList } from "./history-modals";

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
};

/**
 * Everything about the patient in one place: records from partner hospitals
 * (verified) and visits they added, by category, searchable and filterable
 * by date, with files to preview or download; follow-ups to book; sharing
 * with a hospital; and a printable copy.
 */
export default function HistoryView({ highlightTarget, onToast, onOpenSettings, onBook }: Props) {
  const { t, locale } = useI18n();
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loadError, setLoadError] = useState("");
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [preview, setPreview] = useState<{ recordId: string; file: RecordFile } | null>(null);
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

  // A notification about a record opens it.
  useEffect(() => {
    if (!highlightTarget?.startsWith("record-")) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- follows the notification that was opened
    setOpen((current) => new Set(current).add(highlightTarget.slice("record-".length)));
  }, [highlightTarget]);

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

  const shown = useMemo(() => filterItems(items, tab, query, from, to), [items, tab, query, from, to]);
  const summary = data?.summary;
  const filtering = Boolean(query || from || to || tab !== "all");

  const toggle = (id: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const formatDate = (iso: string) => new Date(iso).toLocaleDateString(locale, { dateStyle: "medium" });

  return (
    <div data-purpose="medical-record-view" className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-5xl mx-auto space-y-5 pb-6">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">{t("history.title")}</h1>
            <p className="text-sm text-slate-500 mt-1">{t("history.subtitle")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 self-start">
            <button type="button" data-purpose="add-record" onClick={() => setAdding(true)} className="px-3.5 py-2 rounded-full text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm">
              {t("records.addVisit")}
            </button>
            <button type="button" data-purpose="share-records" onClick={() => setSharing(true)} disabled={!items.length} className="px-3.5 py-2 rounded-full text-xs font-semibold border border-emerald-300 text-emerald-800 bg-white hover:bg-emerald-50 disabled:opacity-50">
              {t("history.share")}
            </button>
            <Link data-purpose="download-records" href="/history/print" target="_blank" rel="noopener" className="px-3.5 py-2 rounded-full text-xs font-semibold border border-slate-200 text-slate-700 bg-white hover:bg-slate-50">
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
            <div key={stat.id} data-purpose={stat.id} className="bg-white rounded-2xl border border-slate-200 card-shadow p-3.5">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{stat.label}</p>
              {data ? (
                <p className="text-xl font-bold text-slate-900 leading-tight tabular-nums">{stat.value ?? 0}</p>
              ) : loadError ? (
                <p className="text-xl font-bold text-slate-300 leading-tight">—</p>
              ) : (
                <Bone className="h-6 w-12 rounded mt-0.5" />
              )}
            </div>
          ))}
        </div>

        {/* Tabs, search, dates */}
        <div className="bg-white rounded-2xl border border-slate-200 card-shadow p-3 sm:p-4 space-y-3">
          <div role="tablist" aria-label={t("history.categories")} className="flex gap-1.5 overflow-x-auto -mx-1 px-1 pb-1">
            {TABS.map((item) => (
              <button
                aria-selected={tab === item.id}
                className={`whitespace-nowrap px-3 py-1.5 rounded-full text-xs font-semibold border transition ${tab === item.id ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"}`}
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
          <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto_auto_auto] gap-2 items-end">
            <label className="block">
              <span className="sr-only">{t("history.search")}</span>
              <input data-purpose="history-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("history.searchPlaceholder")} className="w-full text-sm rounded-xl border border-slate-200 px-3 py-2" />
            </label>
            <label className="block">
              <span className="block text-[11px] font-semibold text-slate-500 mb-0.5">{t("history.from")}</span>
              <input data-purpose="history-from" type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} className="w-full text-sm rounded-xl border border-slate-200 px-3 py-1.5" />
            </label>
            <label className="block">
              <span className="block text-[11px] font-semibold text-slate-500 mb-0.5">{t("history.to")}</span>
              <input data-purpose="history-to" type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} className="w-full text-sm rounded-xl border border-slate-200 px-3 py-1.5" />
            </label>
            <button type="button" disabled={!filtering} onClick={() => { setTab("all"); setQuery(""); setFrom(""); setTo(""); }} className="px-3 py-2 rounded-xl text-xs font-semibold text-slate-600 border border-slate-200 hover:bg-slate-50 disabled:opacity-40">
              {t("history.clearFilters")}
            </button>
          </div>
        </div>

        {loadError && (
          <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">{loadError}</p>
        )}

        {/* Records */}
        {!data && !loadError ? (
          <Skeleton className="space-y-3" label={t("common.loading")}>
            {[0, 1, 2].map((i) => (
              <div className="bg-white rounded-2xl border border-slate-200 p-4 space-y-2.5" key={i}>
                <Bone className="h-3 w-24 rounded" />
                <Bone className="h-4 w-2/3 rounded" />
                <Bone className="h-3 w-1/2 rounded" />
              </div>
            ))}
          </Skeleton>
        ) : data && !items.length ? (
          <p data-purpose="history-empty" className="bg-white rounded-2xl border border-dashed border-slate-300 px-5 py-8 text-sm text-slate-500 text-center">{t("history.empty")}</p>
        ) : data && !shown.length ? (
          <p data-purpose="history-no-match" className="bg-white rounded-2xl border border-dashed border-slate-300 px-5 py-8 text-sm text-slate-500 text-center">{t("history.noMatch")}</p>
        ) : (
          <ul className="space-y-3" data-purpose="history-list">
            {shown.map((item) => {
              const expanded = open.has(item.id);
              const target = `record-${item.id}`;
              return (
                <li
                  className={`bg-white rounded-2xl border card-shadow overflow-hidden ${highlightTarget === target ? "border-emerald-400 ring-2 ring-emerald-200" : "border-slate-200"}`}
                  data-category={item.category}
                  data-purpose="history-item"
                  data-record={item.id}
                  key={item.id}
                >
                  <button aria-expanded={expanded} className="w-full text-left p-4 flex items-start gap-3 hover:bg-slate-50/60" onClick={() => toggle(item.id)} type="button">
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
                      <span className="block text-sm sm:text-base font-semibold text-slate-900 mt-0.5 break-words">{item.title}</span>
                      <span className="block text-xs text-slate-500 mt-0.5">
                        {[formatDate(item.occurred_at), item.hospital_name, item.recorded_by].filter(Boolean).join(" · ")}
                      </span>
                      {item.files.length > 0 && !expanded && (
                        <span className="block text-[11px] text-emerald-700 mt-1">{t(item.files.length === 1 ? "history.filesOne" : "history.filesOther", { count: item.files.length })}</span>
                      )}
                    </span>
                    <svg aria-hidden className={`w-4 h-4 mt-1 text-slate-400 flex-shrink-0 transition-transform ${expanded ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path d="M19 9l-7 7-7-7" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                  {expanded && (
                    <div className="px-4 pb-4 pt-1 border-t border-slate-100 space-y-3" data-purpose="history-details">
                      <RecordDetails item={item} />
                      {item.files.length > 0 && (
                        <div>
                          <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-1.5">{t("history.files")}</p>
                          <ul className="space-y-1.5">
                            {item.files.map((file) => (
                              <FileRow file={file} key={file.file_id} onPreview={() => setPreview({ recordId: item.id, file })} recordId={item.id} />
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <SharesList shares={shares} onChanged={loadShares} onToast={onToast} />
      </div>

      {preview && <FilePreview recordId={preview.recordId} file={preview.file} onClose={() => setPreview(null)} />}
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

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</dt>
      <dd className="text-sm text-slate-800 whitespace-pre-line break-words">{value}</dd>
    </div>
  );
}

const FLAG_STYLE: Record<string, string> = {
  low: "text-sky-800 bg-sky-50 border-sky-200",
  high: "text-amber-800 bg-amber-50 border-amber-200",
  critical: "text-red-800 bg-red-50 border-red-200",
  normal: "text-emerald-800 bg-emerald-50 border-emerald-200",
};

/** The structured part of a record, by category. */
export function RecordDetails({ item }: { item: HistoryItem }) {
  const { t } = useI18n();
  const d = item.details;
  if (item.kind === "self") {
    const medicines = rows(d.medications).map((m) => [text(m.name), text(m.dose)].filter(Boolean).join(" ")).filter(Boolean);
    const days = typeof d.follow_up_days === "number" ? d.follow_up_days : null;
    return (
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label={t("history.self.department")} value={text(d.department)} />
        <Field label={t("history.self.diagnosis")} value={text(d.diagnosis)} />
        <Field label={t("history.self.medicines")} value={medicines.join(", ") || null} />
        <Field label={t("history.self.followUpLabel")} value={days ? [t("records.days", { count: days }), text(d.follow_up_note)].filter(Boolean).join(" · ") : null} />
      </dl>
    );
  }
  switch (item.category) {
    case "diagnosis": {
      const status = text(d.status);
      return (
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label={t("history.diagnosis.condition")} value={text(d.condition)} />
          <Field label={t("history.diagnosis.code")} value={text(d.code)} />
          <Field label={t("history.diagnosis.status")} value={status ? t(`history.status.${status}` as TranslationKey) : null} />
          <Field label={t("history.notes")} value={text(d.notes)} />
        </dl>
      );
    }
    case "prescription": {
      const medicines = rows(d.items);
      return (
        <div className="space-y-2">
          {medicines.length > 0 && (
            <ul className="space-y-2" data-purpose="medicine-list">
              {medicines.map((m, i) => (
                <li className="rounded-xl border border-slate-200 px-3 py-2" key={i}>
                  <p className="text-sm font-semibold text-slate-900">{[text(m.drug), text(m.dose)].filter(Boolean).join(" ")}</p>
                  <p className="text-xs text-slate-600">
                    {[text(m.route), text(m.frequency), text(m.duration) ? t("history.rx.for", { duration: text(m.duration) ?? "" }) : null,
                      text(m.quantity) ? t("history.rx.quantity", { quantity: text(m.quantity) ?? "" }) : null].filter(Boolean).join(" · ")}
                  </p>
                  {text(m.notes) && <p className="text-xs text-slate-500 mt-0.5">{text(m.notes)}</p>}
                </li>
              ))}
            </ul>
          )}
          <dl><Field label={t("history.notes")} value={text(d.notes)} /></dl>
        </div>
      );
    }
    case "lab_result": {
      const results = rows(d.items);
      return (
        <div className="space-y-2">
          {text(d.specimen) && <p className="text-xs text-slate-500">{t("history.lab.specimen", { specimen: text(d.specimen) ?? "" })}</p>}
          {results.length > 0 && (
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-sm border-collapse min-w-[420px]" data-purpose="lab-table">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-slate-400 border-b border-slate-200">
                    <th className="py-1.5 px-1 font-semibold">{t("history.lab.test")}</th>
                    <th className="py-1.5 px-1 font-semibold">{t("history.lab.value")}</th>
                    <th className="py-1.5 px-1 font-semibold">{t("history.lab.range")}</th>
                    <th className="py-1.5 px-1 font-semibold">{t("history.lab.flag")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {results.map((r, i) => {
                    const flag = text(r.flag);
                    return (
                      <tr key={i} data-flag={flag ?? ""}>
                        <td className="py-1.5 px-1 font-medium text-slate-800">{text(r.test)}</td>
                        <td className={`py-1.5 px-1 tabular-nums ${flag && flag !== "normal" ? "font-bold text-slate-900" : "text-slate-700"}`}>
                          {[text(r.value), text(r.unit)].filter(Boolean).join(" ")}
                        </td>
                        <td className="py-1.5 px-1 text-slate-500">{text(r.reference_range)}</td>
                        <td className="py-1.5 px-1">
                          {flag && (
                            <span className={`text-[10px] font-bold uppercase rounded px-1.5 py-0.5 border ${FLAG_STYLE[flag] ?? FLAG_STYLE.normal}`}>
                              {t(`history.flag.${flag}` as TranslationKey)}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <dl><Field label={t("history.notes")} value={text(d.notes)} /></dl>
        </div>
      );
    }
    case "imaging":
      return (
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label={t("history.imaging.modality")} value={text(d.modality)} />
          <Field label={t("history.imaging.bodyPart")} value={text(d.body_part)} />
          <Field label={t("history.imaging.findings")} value={text(d.findings)} />
          <Field label={t("history.imaging.impression")} value={text(d.impression)} />
        </dl>
      );
    case "visit_note": {
      const vitals = d.vitals && typeof d.vitals === "object" ? (d.vitals as Record<string, unknown>) : {};
      const shownVitals = (["bp", "pulse", "temp", "weight", "height", "spo2"] as const).filter((k) => text(vitals[k]));
      return (
        <div className="space-y-3">
          <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Field label={t("history.visit.complaint")} value={text(d.complaint)} />
            <Field label={t("history.visit.findings")} value={text(d.findings)} />
            <Field label={t("history.visit.plan")} value={text(d.plan)} />
          </dl>
          {shownVitals.length > 0 && (
            <dl className="grid grid-cols-2 sm:grid-cols-6 gap-2" data-purpose="vitals">
              {shownVitals.map((k) => (
                <div className="rounded-xl bg-slate-50 border border-slate-100 px-2.5 py-1.5" key={k}>
                  <dt className="text-[10px] font-semibold uppercase text-slate-400">{t(`history.vitals.${k}` as TranslationKey)}</dt>
                  <dd className="text-sm font-semibold text-slate-800">{text(vitals[k])}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      );
    }
    default:
      return <dl><Field label={t("history.document.description")} value={text(d.description)} /></dl>;
  }
}

function FileRow({ recordId, file, onPreview }: { recordId: string; file: RecordFile; onPreview: () => void }) {
  const { t, locale } = useI18n();
  const ready = file.state === "ready";
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 px-3 py-2" data-purpose="record-file">
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-slate-800 truncate">{file.filename}</span>
        <span className="block text-[11px] text-slate-400">
          {formatSize(file.size, locale)}
          {!ready && (
            <span data-purpose="file-state" className={`ml-2 font-semibold ${file.state === "arriving" ? "text-amber-700" : "text-red-700"}`}>
              {file.state === "arriving" ? t("history.file.arriving") : t("history.file.unavailable")}
            </span>
          )}
        </span>
      </span>
      {ready && (
        <span className="flex gap-1.5">
          {file.content_type.startsWith("image/") ? (
            <button className="px-2.5 py-1 rounded-lg text-xs font-semibold border border-slate-200 hover:bg-slate-50" data-purpose="file-preview-button" onClick={onPreview} type="button">
              {t("history.file.preview")}
            </button>
          ) : (
            <a className="px-2.5 py-1 rounded-lg text-xs font-semibold border border-slate-200 hover:bg-slate-50" data-purpose="file-open" href={fileUrl(recordId, file.file_id)} rel="noopener" target="_blank">
              {t("history.file.preview")}
            </a>
          )}
          <a className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-slate-900 text-white hover:bg-slate-700" data-purpose="file-download" download={file.filename} href={fileUrl(recordId, file.file_id, true)}>
            {t("history.file.download")}
          </a>
        </span>
      )}
    </li>
  );
}

function FilePreview({ recordId, file, onClose }: { recordId: string; file: RecordFile; onClose: () => void }) {
  const { t } = useI18n();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div aria-label={t("history.file.previewTitle")} aria-modal="true" className="fixed inset-0 z-50 bg-slate-900/80 flex flex-col items-center justify-center p-4" data-purpose="file-preview" onClick={onClose} role="dialog">
      {/* eslint-disable-next-line @next/next/no-img-element -- a private file from the app's own route, not an optimisable asset */}
      <img alt={file.filename} className="max-w-full max-h-[80vh] rounded-lg bg-white" onClick={(e) => e.stopPropagation()} src={fileUrl(recordId, file.file_id)} />
      <div className="mt-3 flex gap-2">
        <a className="px-4 py-2 rounded-xl bg-white text-slate-900 text-sm font-semibold" download={file.filename} href={fileUrl(recordId, file.file_id, true)} onClick={(e) => e.stopPropagation()}>
          {t("history.file.download")}
        </a>
        <button className="px-4 py-2 rounded-xl border border-white/60 text-white text-sm font-semibold" onClick={onClose} type="button">
          {t("common.close")}
        </button>
      </div>
    </div>
  );
}
