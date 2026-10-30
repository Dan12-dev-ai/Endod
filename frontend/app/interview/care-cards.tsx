"use client";

// Two live cards shown on Home (and Appointments / History):
//
// - QueueCard: the patient's place in today's hospital queues ("You are
//   number 4, 3 people ahead of you, Dr Hana"). Polled every 15 seconds
//   while the page is visible, and refreshed as soon as it is shown again.
// - FollowUpCards: follow-ups a hospital doctor set, with "Book now", which
//   opens booking at that hospital on that day (an earlier day can be chosen).

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { type BookingPreset, type FollowUp, formatDay, type QueueEntry } from "./history-data";

export const QUEUE_POLL_MS = 15_000;

/** Today's queue places; renders nothing when there are none. */
export function QueueCard() {
  const { t } = useI18n();
  const [entries, setEntries] = useState<QueueEntry[]>([]);

  const load = useCallback(async () => {
    try {
      const data = await api<{ entries: QueueEntry[] }>("users/me/queue");
      setEntries(data.entries.filter((e) => e.status === "waiting" || e.status === "called"));
    } catch {
      // Keep what is shown; the next poll tries again.
    }
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer === null) timer = setInterval(() => void load(), QUEUE_POLL_MS);
    };
    const stop = () => {
      if (timer !== null) clearInterval(timer);
      timer = null;
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        void load();
        start();
      } else {
        stop();
      }
    };
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the first fetch; polling follows
    void load();
    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [load]);

  if (!entries.length) return null;
  return (
    <section aria-label={t("queue.title")} className="space-y-3" data-purpose="queue-cards">
      {entries.map((entry) => (
        <div
          aria-live="polite"
          className={`rounded-2xl border p-4 sm:p-5 card-shadow ${entry.status === "called" ? "bg-emerald-600 border-emerald-700 text-white" : "bg-white dark:bg-gray-800 border-emerald-200"}`}
          data-purpose="queue-card"
          key={entry.entry_id}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className={`text-[11px] font-semibold uppercase tracking-wider ${entry.status === "called" ? "text-emerald-100" : "text-emerald-700"}`}>
                <span className="inline-block w-2 h-2 rounded-full bg-current mr-1.5 motion-safe:animate-pulse" aria-hidden />
                {t("queue.title")} · {t("queue.live")}
              </p>
              {entry.status === "called" ? (
                <p className="text-lg sm:text-xl font-bold mt-1" data-purpose="queue-called">{t("queue.called")}</p>
              ) : (
                <>
                  <p className="text-lg sm:text-xl font-bold text-slate-900 dark:text-gray-100 mt-1" data-purpose="queue-position">
                    {t("queue.position", { position: entry.position })}
                  </p>
                  <p className="text-sm text-slate-600" data-purpose="queue-ahead">
                    {entry.ahead === 0 ? t("queue.aheadNone") : entry.ahead === 1 ? t("queue.aheadOne") : t("queue.aheadOther", { count: entry.ahead })}
                  </p>
                </>
              )}
              <p className={`text-xs mt-1 truncate ${entry.status === "called" ? "text-emerald-50" : "text-slate-500"}`}>
                {[entry.doctor_name, entry.hospital_name].filter(Boolean).join(" · ")}
              </p>
            </div>
            <div className={`text-center rounded-xl px-3 py-2 flex-shrink-0 ${entry.status === "called" ? "bg-white/15" : "bg-emerald-50 border border-emerald-100"}`}>
              <p className={`text-[10px] font-semibold uppercase ${entry.status === "called" ? "text-emerald-50" : "text-emerald-700"}`}>{t("queue.ticketLabel")}</p>
              <p className={`text-2xl font-extrabold tabular-nums ${entry.status === "called" ? "text-white" : "text-slate-900 dark:text-gray-100"}`}>{entry.ticket}</p>
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}

/** Upcoming follow-ups with "Book now"; renders nothing when there are none. */
export function FollowUpCards({ onBook, highlight }: { onBook: (preset: BookingPreset) => void; highlight?: string | null }) {
  const { t, locale } = useI18n();
  const [followUps, setFollowUps] = useState<FollowUp[]>([]);

  useEffect(() => {
    let cancelled = false;
    api<{ follow_ups: FollowUp[] }>("users/me/follow-ups")
      .then((data) => !cancelled && setFollowUps(data.follow_ups))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!followUps.length) return null;
  return (
    <section aria-labelledby="follow-ups-title" className="bg-white dark:bg-gray-800 rounded-2xl border border-amber-200 card-shadow p-4 sm:p-5" data-purpose="follow-ups">
      <h2 id="follow-ups-title" className="text-sm font-bold text-slate-900 dark:text-gray-100">{t("followUp.title")}</h2>
      <p className="text-xs text-slate-500 mt-0.5">{t("followUp.hint")}</p>
      <ul className="mt-3 divide-y divide-slate-100">
        {followUps.map((f) => (
          <li
            className={`py-3 flex flex-col sm:flex-row sm:items-center gap-3 justify-between ${highlight === `follow-up-${f.follow_up_id}` ? "bg-amber-50 rounded-xl px-2" : ""}`}
            data-purpose="follow-up"
            key={f.follow_up_id}
          >
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-900 dark:text-gray-100">{formatDay(f.follow_up_on, locale)}</p>
              <p className="text-xs text-slate-600 truncate">
                {f.hospital_name}
                {f.doctor_name ? ` · ${t("followUp.with", { doctor: f.doctor_name })}` : ""}
              </p>
              {f.note && <p className="text-xs text-slate-500 mt-0.5">{f.note}</p>}
            </div>
            <button
              className="self-start sm:self-auto px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold flex-shrink-0"
              data-purpose="follow-up-book"
              onClick={() => onBook({ hospitalId: f.hospital_id, date: f.follow_up_on })}
              type="button"
            >
              {t("followUp.bookNow")}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
