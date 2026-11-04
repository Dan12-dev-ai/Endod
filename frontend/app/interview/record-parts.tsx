"use client";

import { useEffect } from "react";
import { useI18n, type TranslationKey } from "../lib/i18n";
import { formatSize, type HistoryItem, type RecordFile, rows, text, fileUrl } from "./history-data";
function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-[#46545B]">{label}</dt>
      <dd className="text-sm text-[#18242B] whitespace-pre-line break-words">{value}</dd>
    </div>
  );
}

const FLAG_STYLE: Record<string, string> = {
  low: "text-[#18242B] bg-[#F4F7F7] border-[#DCE4E6]",
  high: "text-[#B7791F] bg-[#B7791F]/10 border-[#B7791F]/20",
  critical: "text-[#B42318] bg-[#B42318]/10 border-[#B42318]/20",
  normal: "text-[#18242B] bg-[#F4F7F7] border-[#DCE4E6]",
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
                <li className="rounded-xl border border-[#DCE4E6] px-3 py-2" key={i}>
                  <p className="text-sm font-semibold text-[#18242B]">{[text(m.drug), text(m.dose)].filter(Boolean).join(" ")}</p>
                  <p className="text-xs text-[#25343D]">
                    {[text(m.route), text(m.frequency), text(m.duration) ? t("history.rx.for", { duration: text(m.duration) ?? "" }) : null,
                      text(m.quantity) ? t("history.rx.quantity", { quantity: text(m.quantity) ?? "" }) : null].filter(Boolean).join(" · ")}
                  </p>
                  {text(m.notes) && <p className="text-xs text-[#25343D] mt-0.5">{text(m.notes)}</p>}
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
          {text(d.specimen) && <p className="text-xs text-[#25343D]">{t("history.lab.specimen", { specimen: text(d.specimen) ?? "" })}</p>}
          {results.length > 0 && (
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-sm border-collapse min-w-[420px]" data-purpose="lab-table">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-[#46545B] border-b border-[#DCE4E6]">
                    <th className="py-1.5 px-1 font-semibold">{t("history.lab.test")}</th>
                    <th className="py-1.5 px-1 font-semibold">{t("history.lab.value")}</th>
                    <th className="py-1.5 px-1 font-semibold">{t("history.lab.range")}</th>
                    <th className="py-1.5 px-1 font-semibold">{t("history.lab.flag")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[##F4F7F7]">
                  {results.map((r, i) => {
                    const flag = text(r.flag);
                    return (
                      <tr key={i} data-flag={flag ?? ""}>
                        <td className="py-1.5 px-1 font-medium text-[#18242B]">{text(r.test)}</td>
                        <td className={`py-1.5 px-1 tabular-nums ${flag && flag !== "normal" ? "font-bold text-[#18242B]" : "text-[#25343D]"}`}>
                          {[text(r.value), text(r.unit)].filter(Boolean).join(" ")}
                        </td>
                        <td className="py-1.5 px-1 text-[#25343D]">{text(r.reference_range)}</td>
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
                <div className="rounded-xl bg-[#F4F7F7] border border-[#F4F7F7] px-2.5 py-1.5" key={k}>
                  <dt className="text-[10px] font-semibold uppercase text-[#46545B]">{t(`history.vitals.${k}` as TranslationKey)}</dt>
                  <dd className="text-sm font-semibold text-[#18242B]">{text(vitals[k])}</dd>
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

export function FileRow({ recordId, file, onPreview }: { recordId: string; file: RecordFile; onPreview: () => void }) {
  const { t, locale } = useI18n();
  const ready = file.state === "ready";
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-xl border border-[#DCE4E6] px-3 py-2" data-purpose="record-file">
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-[#18242B] truncate">{file.filename}</span>
        <span className="block text-[11px] text-[#46545B]">
          {formatSize(file.size, locale)}
          {!ready && (
            <span data-purpose="file-state" className={`ml-2 font-semibold ${file.state === "arriving" ? "text-[#B7791F]" : "text-[#B42318]"}`}>
              {file.state === "arriving" ? t("history.file.arriving") : t("history.file.unavailable")}
            </span>
          )}
        </span>
      </span>
      {ready && (
        <span className="flex gap-1.5">
          {file.content_type.startsWith("image/") ? (
            <button className="px-2.5 py-1 rounded-lg text-xs font-semibold border border-[#DCE4E6] hover:bg-[#F4F7F7]" data-purpose="file-preview-button" onClick={onPreview} type="button">
              {t("history.file.preview")}
            </button>
          ) : (
            <a className="px-2.5 py-1 rounded-lg text-xs font-semibold border border-[#DCE4E6] hover:bg-[#F4F7F7]" data-purpose="file-open" href={fileUrl(recordId, file.file_id)} rel="noopener" target="_blank">
              {t("history.file.preview")}
            </a>
          )}
          <a className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-[#18242B] text-white hover:bg-[#25343D]" data-purpose="file-download" download={file.filename} href={fileUrl(recordId, file.file_id, true)}>
            {t("history.file.download")}
          </a>
        </span>
      )}
    </li>
  );
}

export function FilePreview({ recordId, file, onClose }: { recordId: string; file: RecordFile; onClose: () => void }) {
  const { t } = useI18n();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div aria-label={t("history.file.previewTitle")} aria-modal="true" className="fixed inset-0 z-50 bg-[#18242B]/80 flex flex-col items-center justify-center p-4" data-purpose="file-preview" onClick={onClose} role="dialog">
      {/* eslint-disable-next-line @next/next/no-img-element -- a private file from the app's own route, not an optimisable asset */}
      <img alt={file.filename} className="max-w-full max-h-[80vh] rounded-lg bg-white" onClick={(e) => e.stopPropagation()} src={fileUrl(recordId, file.file_id)} />
      <div className="mt-3 flex gap-2">
        <a className="px-4 py-2 rounded-xl bg-white text-[#18242B] text-sm font-semibold" download={file.filename} href={fileUrl(recordId, file.file_id, true)} onClick={(e) => e.stopPropagation()}>
          {t("history.file.download")}
        </a>
        <button className="px-4 py-2 rounded-xl border border-white/60 text-white text-sm font-semibold" onClick={onClose} type="button">
          {t("common.close")}
        </button>
      </div>
    </div>
  );
}
