"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { departmentLabel } from "./data";
import { Bone } from "../components/skeleton";

type MedicalRecord = {
  record_id: string;
  occurred_at: string;
  facility_name: string | null;
  department: string | null;
  diagnosis: string | null;
  medications: { name: string; dose: string | null }[];
  follow_up_days: number | null;
  follow_up_due: string | null;
  follow_up_note: string | null;
  verified: boolean;
  source: string | null;
};

type RecordsResponse = {
  records: MedicalRecord[];
  summary: {
    total_visits: number;
    verified_records: number;
    facilities_visited: number;
    medications_used: number;
    active_follow_ups: number;
  };
};

type Props = {
  highlightTarget: string | null;
  onToast: (title: string, message: string) => void;
  /** Opens Settings, where consent is managed. */
  onOpenSettings: () => void;
};

function todayInput(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Past visits (GET/POST /users/me/records). */
export default function RecordsView({ highlightTarget, onToast, onOpenSettings }: Props) {
  const { t, locale } = useI18n();
  const [data, setData] = useState<RecordsResponse | null>(null);
  const [loadError, setLoadError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [formError, setFormError] = useState("");
  const [needsConsent, setNeedsConsent] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [form, setForm] = useState({
    date: todayInput(), facility: "", department: "", diagnosis: "", medications: "", followUpDays: "", followUpNote: "",
  });

  const formatDate = (iso: string): { date: string; time: string } => {
    const at = new Date(iso);
    return {
      date: at.toLocaleDateString(locale, { dateStyle: "medium" }),
      time: at.toLocaleTimeString(locale, { timeStyle: "short" }),
    };
  };

  const load = useCallback(async () => {
    try {
      setData(await api<RecordsResponse>("users/me/records"));
      setLoadError("");
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : t("records.error.load"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is stable per language
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
  }, [load]);

  const set = (field: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [field]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    setNeedsConsent(false);
    const followUp = form.followUpDays.trim();
    // A date-only visit: noon that day (clear of timezone edges), or now
    // for a visit today.
    const when = form.date === todayInput() ? new Date() : new Date(`${form.date}T12:00:00`);
    if (Number.isNaN(when.getTime()) || when > new Date()) {
      setFormError(t("records.error.pastDate"));
      return;
    }
    setIsSaving(true);
    try {
      await api("users/me/records", {
        method: "POST",
        body: {
          occurred_at: when.toISOString(),
          facility_name: form.facility.trim(),
          department: form.department.trim() || null,
          diagnosis: form.diagnosis.trim() || null,
          medications: form.medications.split(/[,\n]/).map((m) => m.trim()).filter(Boolean),
          follow_up_days: followUp ? Number(followUp) : null,
          follow_up_note: form.followUpNote.trim() || null,
        },
      });
      setShowForm(false);
      setForm({ date: todayInput(), facility: "", department: "", diagnosis: "", medications: "", followUpDays: "", followUpNote: "" });
      onToast(t("records.toast.addedTitle"), t("records.toast.added"));
      await load();
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) setNeedsConsent(true);
      setFormError(error instanceof ApiError ? error.message : t("records.error.save"));
    } finally {
      setIsSaving(false);
    }
  };

  const records = data?.records ?? [];
  const summary = data?.summary;

  return (
    <div data-purpose="medical-record-view" className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-5xl mx-auto space-y-6 pb-6">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">{t("records.title")}</h1>
            <p className="text-sm text-slate-500 mt-1">{t("records.subtitle")}</p>
          </div>
          <div className="flex items-center gap-2 self-start">
            <span data-purpose="records-count" className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3.5 py-1.5 text-xs font-semibold text-emerald-700 shadow-sm">
              {t(summary?.verified_records === 1 ? "records.verifiedOne" : "records.verifiedOther", { count: summary?.verified_records ?? 0 })}
            </span>
            <button type="button" data-purpose="add-record" onClick={() => { setShowForm(true); setFormError(""); setNeedsConsent(false); }} className="px-3.5 py-1.5 rounded-full text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm">
              {t("records.addVisit")}
            </button>
          </div>
        </div>

        {/* Summary */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
          {[
            { id: "stat-total-visits", label: t("records.totalVisits"), value: summary?.total_visits ?? 0 },
            { id: "stat-hospitals", label: t("records.hospitalsVisited"), value: summary?.facilities_visited ?? 0 },
            { id: "stat-drugs", label: t("records.drugsUsed"), value: summary?.medications_used ?? 0 },
          ].map((stat) => (
            <div key={stat.id} data-purpose={stat.id} className="bg-white rounded-2xl border border-slate-200 card-shadow p-4">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{stat.label}</p>
              {data ? (
                <p className="text-xl font-bold text-slate-900 leading-tight tabular-nums">{stat.value}</p>
              ) : loadError ? (
                <p className="text-xl font-bold text-slate-300 leading-tight">—</p>
              ) : (
                <Bone className="h-6 w-12 rounded mt-0.5" />
              )}
            </div>
          ))}
        </div>

        {loadError && (
          <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">{loadError}</p>
        )}

        {!data && !loadError && (
          <p className="sr-only" data-purpose="skeleton" role="status">{t("common.loading")}</p>
        )}
        <div data-purpose="medical-records-table" className="bg-white rounded-2xl border border-slate-200 card-shadow overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="bg-gradient-to-r from-slate-50 via-slate-50 to-emerald-50/40 border-b-2 border-slate-200">
                  {[t("records.col.date"), t("records.col.hospital"), t("records.col.disease"), t("records.col.drug"), t("records.col.followup")].map((heading) => (
                    <th key={heading} className="text-left px-5 py-4 text-[11px] font-bold uppercase tracking-wider text-slate-500 whitespace-nowrap">{heading}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {!data && !loadError && [0, 1, 2, 3].map((row) => (
                  <tr data-purpose="skeleton" key={`skeleton-${row}`} aria-hidden>
                    {[28, 40, 36, 32, 24].map((width, cell) => (
                      <td className="px-5 py-4" key={cell}>
                        <Bone className="h-3 rounded" style={{ width: `${width + ((row * 7 + cell * 5) % 20)}%` }} />
                      </td>
                    ))}
                  </tr>
                ))}
                {data && records.length === 0 && (
                  <tr>
                    <td data-purpose="records-empty" colSpan={5} className="px-5 py-6 text-xs text-slate-500 text-center">
                      {t("records.empty")}
                    </td>
                  </tr>
                )}
                {records.map((record) => {
                  const when = formatDate(record.occurred_at);
                  // Visits the patient added are date-only: no made-up time.
                  const dateOnly = record.source === "patient";
                  const target = `record-${record.record_id}`;
                  return (
                    <tr key={record.record_id} data-purpose={target} className={`transition-colors even:bg-slate-50/40 hover:bg-emerald-50/60 ${highlightTarget === target ? "bg-emerald-50 ring-2 ring-inset ring-emerald-300" : ""}`}>
                      <td className="px-5 py-4 align-middle">
                        <div className="font-semibold text-slate-900 whitespace-nowrap">{when.date}</div>
                        {!dateOnly && <div className="text-[11px] text-slate-400">{when.time}</div>}
                      </td>
                      <td className="px-5 py-4 align-middle">
                        <div className="font-semibold text-slate-900">{record.facility_name ?? "—"}</div>
                        <div className="text-[11px] text-emerald-600 font-medium">{record.department ? departmentLabel(record.department, t) : ""}</div>
                        <span data-purpose="record-source" className={`mt-1 inline-block text-[10px] font-semibold rounded px-1.5 py-0.5 border ${record.verified ? "text-emerald-700 bg-emerald-50 border-emerald-200" : "text-slate-500 bg-slate-50 border-slate-200"}`}>
                          {record.verified ? t("records.verified") : t("records.selfReported")}
                        </span>
                      </td>
                      <td className="px-5 py-4 align-middle text-slate-700">{record.diagnosis ?? <span className="text-slate-400">—</span>}</td>
                      <td className="px-5 py-4 align-middle text-slate-700">
                        {record.medications.length
                          ? record.medications.map((m) => [m.name, m.dose].filter(Boolean).join(" ")).join(", ")
                          : <span className="text-slate-400">{t("records.none")}</span>}
                      </td>
                      <td className="px-5 py-4 align-middle">
                        {record.follow_up_days ? (
                          <>
                            <div className="font-bold text-emerald-700">{t("records.days", { count: record.follow_up_days })}</div>
                            <div className="text-[11px] text-slate-400">
                              {record.follow_up_due ? t("records.due", { date: new Date(record.follow_up_due).toLocaleDateString(locale, { dateStyle: "medium" }) }) : ""}
                              {record.follow_up_note ? ` · ${record.follow_up_note}` : ""}
                            </div>
                          </>
                        ) : (
                          <div className="font-medium text-slate-500">{t("records.noFollowUp")}</div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              {summary && (
                <tfoot>
                  <tr className="bg-slate-50/80 border-t-2 border-slate-200">
                    <td className="px-5 py-3.5 text-[11px] font-bold uppercase tracking-wider text-slate-500" colSpan={4}>
                      {t(summary.total_visits === 1 ? "records.recordOne" : "records.recordOther", { count: summary.total_visits })}
                    </td>
                    <td className="px-5 py-3.5">
                      <span data-purpose="active-follow-ups" className="text-xs font-semibold text-emerald-700">
                        {t(summary.active_follow_ups === 1 ? "records.activeFollowUpsOne" : "records.activeFollowUpsOther", { count: summary.active_follow_ups })}
                      </span>
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </div>
      </div>

      {showForm && (
        <div data-purpose="record-modal" className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200 max-h-[95vh] overflow-y-auto">
            <h3 className="text-lg font-bold text-slate-900">{t("records.modal.title")}</h3>
            <p className="text-xs text-slate-500 mt-0.5">{t("records.modal.subtitle")}</p>
            <form onSubmit={submit} className="space-y-3 mt-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="record-date" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.date")}</label>
                  <input id="record-date" type="date" required max={todayInput()} value={form.date} onChange={set("date")} className="w-full text-xs rounded-xl border border-slate-200 px-3 py-2" />
                </div>
                <div>
                  <label htmlFor="record-follow-up" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.followUpIn")}</label>
                  <input id="record-follow-up" type="number" min={1} max={730} value={form.followUpDays} onChange={set("followUpDays")} className="w-full text-xs rounded-xl border border-slate-200 px-3 py-2" />
                </div>
              </div>
              <div>
                <label htmlFor="record-facility" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.facility")}</label>
                <input id="record-facility" required maxLength={160} value={form.facility} onChange={set("facility")} className="w-full text-xs rounded-xl border border-slate-200 px-3 py-2" />
              </div>
              <div>
                <label htmlFor="record-department" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.department")}</label>
                <input id="record-department" maxLength={120} value={form.department} onChange={set("department")} className="w-full text-xs rounded-xl border border-slate-200 px-3 py-2" />
              </div>
              <div>
                <label htmlFor="record-diagnosis" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.diagnosis")}</label>
                <input id="record-diagnosis" maxLength={300} value={form.diagnosis} onChange={set("diagnosis")} className="w-full text-xs rounded-xl border border-slate-200 px-3 py-2" />
              </div>
              <div>
                <label htmlFor="record-medications" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.medications")}</label>
                <input id="record-medications" value={form.medications} onChange={set("medications")} placeholder={t("records.modal.medicationsPlaceholder")} className="w-full text-xs rounded-xl border border-slate-200 px-3 py-2" />
              </div>
              <div>
                <label htmlFor="record-note" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.note")}</label>
                <textarea id="record-note" rows={2} maxLength={500} value={form.followUpNote} onChange={set("followUpNote")} className="w-full text-xs rounded-xl border border-slate-200 px-3 py-2" />
              </div>

              {formError && (
                <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" data-purpose="record-error" role="alert">
                  {formError}
                  {needsConsent && (
                    <button type="button" onClick={onOpenSettings} className="ml-1 font-semibold underline">{t("records.modal.openSettings")}</button>
                  )}
                </div>
              )}

              <div className="pt-2 flex items-center justify-end gap-3">
                <button type="button" onClick={() => setShowForm(false)} className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-50">{t("common.cancel")}</button>
                <button type="submit" disabled={isSaving} className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white text-xs font-semibold">
                  {isSaving ? t("common.saving") : t("records.modal.save")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
