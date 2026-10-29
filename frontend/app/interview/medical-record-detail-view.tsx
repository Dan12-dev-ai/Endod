"use client";

import { Suspense } from "react";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Bone, Skeleton } from "../components/skeleton";
import { RecordDetails, FileRow, FilePreview } from "./record-parts";
import { CATEGORY_LABEL, type HistoryItem, type HistoryResponse, type RecordFile } from "./history-data";
import { PrescriptionPharmacy } from "./prescription-pharmacy";

type Props = {
  recordId?: string;
  onBack?: () => void;
};

export function MedicalRecordDetailView({ recordId: recordIdProp, onBack }: Props) {
  const router = useRouter();
  const { t, locale } = useI18n();
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState<{ recordId: string; file: RecordFile } | null>(null);

  const params = useParams();
  const idFromParams = Array.isArray(params?.id) ? params.id[0] : (params?.id as string | undefined);
  const id = recordIdProp ?? idFromParams;

  const item: HistoryItem | undefined = data?.items.find((entry) => entry.id === id);

  const load = useCallback(async () => {
    try {
      const history = await api<HistoryResponse>("users/me/history");
      setData(history);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("history.error.load"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const history = await api<HistoryResponse>("users/me/history");
        if (cancelled) return;
        setData(history);
        setError("");
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : t("history.error.load"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, t]);

  const arriving = useMemo(() => item?.files?.some((f) => f.state === "arriving") ?? false, [item]);

  useEffect(() => {
    if (!arriving) return;
    const until = Date.now() + 5 * 60 * 1000;
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
      if (timer === null && Date.now() <= until) timer = setInterval(tick, 10_000);
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

  const formatDate = (iso: string) => new Date(iso).toLocaleDateString(locale, { dateStyle: "medium" });

  const handleBack = () => {
    if (onBack) onBack();
    else router.push("/interview?section=followup");
  };

  const embedded = !!onBack;

  const content = (
    <div className={embedded ? "w-full space-y-5 pb-6" : "max-w-3xl mx-auto space-y-5"} data-purpose="medical-record-detail">
        <button
          className="text-sm font-semibold text-black hover:underline"
          data-purpose="back-link"
          onClick={handleBack}
          type="button"
        >
          {"← " + t("print.back")}
        </button>

        {loading && (
          <div data-purpose="record-loading">
            <Skeleton className="space-y-3" label={t("common.loading")}>
              {[0, 1, 2].map((i) => (
                <div className="bg-white rounded-2xl border border-slate-200 p-4 space-y-2.5" key={i}>
                  <Bone className="h-3 w-24 rounded" />
                  <Bone className="h-4 w-2/3 rounded" />
                  <Bone className="h-3 w-1/2 rounded" />
                </div>
              ))}
            </Skeleton>
          </div>
        )}

        {!loading && error && (
          <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">
            {error}
          </p>
        )}

        {!loading && !error && !item && (
          <div className="bg-white rounded-2xl border border-dashed border-slate-300 px-5 py-8 text-center" data-purpose="record-not-found">
            <p className="text-sm text-slate-500">{t("history.empty")}</p>
          </div>
        )}

        {!loading && !error && item && (
          <article className="bg-white rounded-2xl border border-slate-200 card-shadow overflow-hidden" data-purpose="record-card">
            <header className="p-4 sm:p-5 border-b border-slate-100 space-y-2" data-purpose="record-header">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  {t(CATEGORY_LABEL[item.category])}
                </span>
                <span className={"text-[10px] font-semibold rounded px-1.5 py-0.5 border " + (item.verified ? "text-black bg-gray-50 border-gray-200" : "text-slate-500 bg-slate-50 border-slate-200")} data-purpose="record-source">
                  {item.verified ? t("records.verified") : t("records.selfReported")}
                </span>
              </div>
              <h1 className="text-lg sm:text-xl font-bold text-slate-900 break-words" data-purpose="record-title">
                {item.title}
              </h1>
              <p className="text-xs text-slate-500">
                {[formatDate(item.occurred_at), item.hospital_name, item.recorded_by].filter(Boolean).join(" · ")}
              </p>
            </header>

            <div className="p-4 sm:p-5 space-y-4" data-purpose="record-details">
              <div data-purpose="history-details">
                <RecordDetails item={item} />
                {item.category === "prescription" && item.dispensing && (
                  <PrescriptionPharmacy details={item.details} rx={item.dispensing} />
                )}
                {item.files.length > 0 && (
                  <div data-purpose="record-files">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
                      {t("history.files")}
                    </p>
                    <ul className="space-y-1.5">
                      {item.files.map((file) => (
                        <FileRow file={file} key={file.file_id} onPreview={() => setPreview({ recordId: item.id, file })} recordId={item.id} />
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </article>
        )}

        {preview && (
          <FilePreview file={preview.file} onClose={() => setPreview(null)} recordId={preview.recordId} />
        )}
    </div>
  );

  if (embedded) return content;
  return <main className="min-h-screen bg-slate-50 text-slate-900 px-4 py-6 sm:px-10">{content}</main>;
}

export default function MedicalRecordDetailPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-50" />}>
      <MedicalRecordDetailView />
    </Suspense>
  );
}
