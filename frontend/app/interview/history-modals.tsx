"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { RowBones, Skeleton } from "../components/skeleton";
import { CATEGORY_LABEL, type HistoryItem, type Share, type ShareHospital } from "./history-data";

function todayInput(offsetDays = 0): string {
  const now = new Date();
  now.setDate(now.getDate() + offsetDays);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const EMPTY_VISIT = { date: "", facility: "", department: "", diagnosis: "", medications: "", followUpDays: "", followUpNote: "" };

/** A visit the patient adds themselves (POST /users/me/records; shown as self-reported). */
export function AddVisitModal({ onClose, onSaved, onOpenSettings }: {
  onClose: () => void;
  onSaved: () => void | Promise<void>;
  onOpenSettings: () => void;
}) {
  const { t } = useI18n();
  const [form, setForm] = useState(() => ({ ...EMPTY_VISIT, date: todayInput() }));
  const [error, setError] = useState("");
  const [needsConsent, setNeedsConsent] = useState(false);
  const [saving, setSaving] = useState(false);

  const set = (field: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [field]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setNeedsConsent(false);
    const followUp = form.followUpDays.trim();
    // A date-only visit: noon that day (clear of timezone edges), or now for a visit today.
    const when = form.date === todayInput() ? new Date() : new Date(`${form.date}T12:00:00`);
    if (Number.isNaN(when.getTime()) || when > new Date()) {
      setError(t("records.error.pastDate"));
      return;
    }
    setSaving(true);
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
      await onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setNeedsConsent(true);
      setError(err instanceof ApiError ? err.message : t("records.error.save"));
    } finally {
      setSaving(false);
    }
  };

  const input = "w-full text-sm rounded-xl border border-slate-200 px-3 py-2";
  return (
    <div data-purpose="record-modal" className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
      <div aria-labelledby="record-modal-title" aria-modal="true" role="dialog" className="bg-white rounded-2xl max-w-lg w-full p-5 sm:p-6 shadow-2xl border border-slate-200 max-h-[95vh] overflow-y-auto">
        <h3 id="record-modal-title" className="text-lg font-bold text-slate-900">{t("records.modal.title")}</h3>
        <p className="text-xs text-slate-500 mt-0.5">{t("records.modal.subtitle")}</p>
        <form onSubmit={submit} className="space-y-3 mt-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="record-date" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.date")}</label>
              <input id="record-date" type="date" required max={todayInput()} value={form.date} onChange={set("date")} className={input} />
            </div>
            <div>
              <label htmlFor="record-follow-up" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.followUpIn")}</label>
              <input id="record-follow-up" type="number" min={1} max={730} value={form.followUpDays} onChange={set("followUpDays")} className={input} />
            </div>
          </div>
          <div>
            <label htmlFor="record-facility" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.facility")}</label>
            <input id="record-facility" required maxLength={160} value={form.facility} onChange={set("facility")} className={input} />
          </div>
          <div>
            <label htmlFor="record-department" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.department")}</label>
            <input id="record-department" maxLength={120} value={form.department} onChange={set("department")} className={input} />
          </div>
          <div>
            <label htmlFor="record-diagnosis" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.diagnosis")}</label>
            <input id="record-diagnosis" maxLength={300} value={form.diagnosis} onChange={set("diagnosis")} className={input} />
          </div>
          <div>
            <label htmlFor="record-medications" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.medications")}</label>
            <input id="record-medications" value={form.medications} onChange={set("medications")} placeholder={t("records.modal.medicationsPlaceholder")} className={input} />
          </div>
          <div>
            <label htmlFor="record-note" className="block text-xs font-semibold text-slate-700 mb-1">{t("records.modal.note")}</label>
            <textarea id="record-note" rows={2} maxLength={500} value={form.followUpNote} onChange={set("followUpNote")} className={input} />
          </div>
          {error && (
            <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" data-purpose="record-error" role="alert">
              {error}
              {needsConsent && (
                <button type="button" onClick={onOpenSettings} className="ml-1 font-semibold underline">{t("records.modal.openSettings")}</button>
              )}
            </div>
          )}
          <div className="pt-2 flex items-center justify-end gap-3">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-50">{t("common.cancel")}</button>
            <button type="submit" disabled={saving} className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white text-xs font-semibold">
              {saving ? t("common.saving") : t("records.modal.save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** Choose records, a partner hospital and (optionally) an end date; POST /users/me/shares. */
export function ShareModal({ items, onClose, onShared }: {
  items: HistoryItem[];
  onClose: () => void;
  onShared: (share: Share) => void | Promise<void>;
}) {
  const { t, locale, language } = useI18n();
  const [chosen, setChosen] = useState<Set<string>>(() => new Set());
  const [hospitals, setHospitals] = useState<ShareHospital[] | null>(null);
  const [hospitalId, setHospitalId] = useState("");
  const [until, setUntil] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    let cancelled = false;
    api<{ hospitals: ShareHospital[] }>("users/me/shares/hospitals")
      .then((data) => !cancelled && setHospitals(data.hospitals))
      .catch(() => {
        if (cancelled) return;
        setHospitals([]);
        setError(t("share.error.load"));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is stable per language
  }, []);

  const visible = useMemo(() => {
    const words = filter.trim().toLowerCase();
    return words ? items.filter((i) => `${i.title} ${i.hospital_name ?? ""}`.toLowerCase().includes(words)) : items;
  }, [items, filter]);

  const toggle = (id: string) =>
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!chosen.size) return setError(t("share.error.none"));
    if (!hospitalId) return setError(t("share.error.hospital"));
    setSaving(true);
    try {
      // The end of the chosen day, in the patient's own timezone.
      const expires = until ? new Date(`${until}T23:59:59`).toISOString() : null;
      const share = await api<Share>("users/me/shares", {
        method: "POST",
        body: { hospital_id: hospitalId, record_ids: [...chosen], expires_at: expires },
      });
      await onShared(share);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.somethingWrong"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div data-purpose="share-modal" className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-slate-900/60 backdrop-blur-xs">
      <div aria-labelledby="share-modal-title" aria-modal="true" role="dialog" className="bg-white rounded-2xl max-w-xl w-full p-5 sm:p-6 shadow-2xl border border-slate-200 max-h-[95vh] overflow-y-auto">
        <h3 id="share-modal-title" className="text-lg font-bold text-slate-900">{t("share.title")}</h3>
        <p className="text-xs text-slate-500 mt-0.5">{t("share.subtitle")}</p>
        <form onSubmit={submit} className="space-y-4 mt-4">
          <fieldset>
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <legend className="text-xs font-semibold text-slate-700">{t("share.chooseRecords")}</legend>
              <span className="text-[11px] text-slate-500" data-purpose="share-selected">{t("share.selected", { count: chosen.size })}</span>
            </div>
            <div className="flex gap-2 mb-2">
              <input aria-label={t("history.search")} type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t("history.search")} className="flex-1 min-w-0 text-sm rounded-xl border border-slate-200 px-3 py-1.5" />
              <button type="button" onClick={() => setChosen(new Set(visible.map((i) => i.id)))} className="px-2.5 py-1.5 rounded-xl text-xs font-semibold border border-slate-200 hover:bg-slate-50">{t("share.selectAll")}</button>
              <button type="button" onClick={() => setChosen(new Set())} className="px-2.5 py-1.5 rounded-xl text-xs font-semibold border border-slate-200 hover:bg-slate-50">{t("share.clear")}</button>
            </div>
            <ul className="max-h-60 overflow-y-auto rounded-xl border border-slate-200 divide-y divide-slate-100">
              {visible.map((item) => (
                <li key={item.id}>
                  <label className="flex items-start gap-3 px-3 py-2 cursor-pointer hover:bg-slate-50" data-purpose="share-record">
                    <input checked={chosen.has(item.id)} className="mt-1" onChange={() => toggle(item.id)} type="checkbox" />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-slate-800 break-words">{item.title}</span>
                      <span className="block text-[11px] text-slate-500">
                        {[t(CATEGORY_LABEL[item.category]), new Date(item.occurred_at).toLocaleDateString(locale, { dateStyle: "medium" }),
                          item.kind === "self" ? t("records.selfReported") : item.hospital_name].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="share-hospital" className="block text-xs font-semibold text-slate-700 mb-1">{t("share.hospital")}</label>
              <select id="share-hospital" value={hospitalId} onChange={(e) => setHospitalId(e.target.value)} disabled={!hospitals} className="w-full text-sm rounded-xl border border-slate-200 px-3 py-2 bg-white">
                <option value="">{t("share.chooseHospital")}</option>
                {(hospitals ?? []).map((h) => (
                  <option key={h.hospital_id} value={h.hospital_id}>
                    {(language === "am" && h.name_am) || h.name}{h.city ? ` · ${h.city}` : ""}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="share-until" className="block text-xs font-semibold text-slate-700 mb-1">{t("share.until")}</label>
              <input id="share-until" type="date" min={todayInput(1)} max={todayInput(365)} value={until} onChange={(e) => setUntil(e.target.value)} className="w-full text-sm rounded-xl border border-slate-200 px-3 py-2" />
              <p className="text-[11px] text-slate-400 mt-1">{t("share.untilHint")}</p>
            </div>
          </div>
          {error && <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" data-purpose="share-error" role="alert">{error}</p>}
          <div className="flex items-center justify-end gap-3">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-50">{t("common.cancel")}</button>
            <button type="submit" disabled={saving} data-purpose="share-submit" className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white text-xs font-semibold">
              {saving ? t("share.sharing") : t("share.submit")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** The patient's shares, with "Stop sharing" on the active ones. */
export function SharesList({ shares, onChanged, onToast }: {
  shares: Share[] | null;
  onChanged: () => void | Promise<void>;
  onToast: (title: string, message: string) => void;
}) {
  const { t, locale } = useI18n();
  const [busy, setBusy] = useState<string | null>(null);

  const revoke = async (share: Share) => {
    setBusy(share.share_id);
    try {
      await api(`users/me/shares/${share.share_id}`, { method: "DELETE" });
      onToast(t("share.revokedTitle"), t("share.revokedBody", { hospital: share.hospital_name }));
      await onChanged();
    } catch (err) {
      onToast(t("common.couldNotUpdate"), err instanceof ApiError ? err.message : t("common.pleaseTryAgain"));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section aria-labelledby="shares-title" className="bg-white rounded-2xl border border-slate-200 card-shadow p-4 sm:p-5" data-purpose="shares">
      <h2 id="shares-title" className="text-sm font-bold text-slate-900">{t("share.listTitle")}</h2>
      {shares === null ? (
        <Skeleton className="mt-3" label={t("common.loading")}>
          <RowBones />
        </Skeleton>
      ) : !shares.length ? (
        <p className="text-xs text-slate-500 mt-2" data-purpose="shares-empty">{t("share.listEmpty")}</p>
      ) : (
        <ul className="mt-3 divide-y divide-slate-100">
          {shares.map((share) => (
            <li className="py-3 flex flex-col sm:flex-row sm:items-center gap-2 justify-between" data-purpose="share" data-status={share.status} key={share.share_id}>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900">{share.hospital_name}</p>
                <p className="text-xs text-slate-500">
                  {[t(share.record_count === 1 ? "share.recordsOne" : "share.recordsOther", { count: share.record_count }),
                    share.expires_at ? t("share.untilDate", { date: new Date(share.expires_at).toLocaleDateString(locale, { dateStyle: "medium" }) }) : t("share.noEnd"),
                  ].join(" · ")}
                </p>
                <p className="text-[11px] text-slate-400 truncate">{share.records.map((r) => r.title).filter(Boolean).join(", ")}</p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <span data-purpose="share-status" className={`text-[10px] font-semibold uppercase rounded px-1.5 py-0.5 border ${share.status === "active" ? "text-emerald-700 bg-emerald-50 border-emerald-200" : "text-slate-500 bg-slate-50 border-slate-200"}`}>
                  {t(`share.status.${share.status}`)}
                </span>
                {share.status === "active" && (
                  <button className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-red-200 text-red-700 hover:bg-red-50 disabled:opacity-50" data-purpose="share-revoke" disabled={busy === share.share_id} onClick={() => void revoke(share)} type="button">
                    {t("share.revoke")}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
