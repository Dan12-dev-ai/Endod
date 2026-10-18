"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useI18n, type TranslationKey } from "../lib/i18n";
import { type Appointment, appointmentTitle, formatWhen } from "./data";

type Props = {
  firstName: string;
  onNavigate: (nav: string) => void;
};

const SHORTCUTS: { nav: string; titleKey: TranslationKey; hintKey: TranslationKey }[] = [
  { nav: "booking", titleKey: "home.shortcut.booking.title", hintKey: "home.shortcut.booking.hint" },
  { nav: "appointment", titleKey: "home.shortcut.appointment.title", hintKey: "home.shortcut.appointment.hint" },
  { nav: "followup", titleKey: "home.shortcut.followup.title", hintKey: "home.shortcut.followup.hint" },
  { nav: "message", titleKey: "home.shortcut.message.title", hintKey: "home.shortcut.message.hint" },
];

/** The landing screen: what is next, and where to go. */
export default function HomeView({ firstName, onNavigate }: Props) {
  const { t, locale } = useI18n();
  const [next, setNext] = useState<Appointment | null | undefined>(undefined);
  const [unread, setUnread] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Appointment[]>("users/me/appointments", { query: { upcoming_only: true, limit: 1 } })
      .then((list) => !cancelled && setNext(list[0] ?? null))
      .catch(() => !cancelled && setNext(null));
    api<{ unread_count: number }>("users/me/inbox", { query: { limit: 1 } })
      .then((page) => !cancelled && setUnread(page.unread_count))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div data-purpose="home-view" className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-5xl mx-auto space-y-6 py-6">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
            {firstName ? t("home.welcomeNamed", { name: firstName }) : t("home.welcome")}
          </h1>
          <p className="text-sm text-slate-500 mt-1">{t("home.subtitle")}</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <button type="button" data-purpose="home-next-appointment" onClick={() => onNavigate("appointment")} className="text-left bg-white p-5 rounded-2xl border border-slate-200 card-shadow hover:border-emerald-300 transition">
            <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">{t("home.nextAppointment")}</p>
            <h2 className="text-base font-bold text-slate-900 mt-1">
              {next === undefined ? t("common.loading") : next ? formatWhen(next.scheduled_at, locale) : t("home.noneScheduled")}
            </h2>
            {next && <p className="text-xs text-emerald-600 font-medium mt-0.5">{appointmentTitle(next, t)}</p>}
          </button>
          <button type="button" data-purpose="home-unread" onClick={() => onNavigate("message")} className="text-left bg-white p-5 rounded-2xl border border-slate-200 card-shadow hover:border-emerald-300 transition">
            <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">{t("home.notifications")}</p>
            <h2 className="text-base font-bold text-slate-900 mt-1">
              {unread === null ? "—" : unread === 0 ? t("home.upToDate") : t("home.unread", { count: unread })}
            </h2>
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {SHORTCUTS.map((s) => (
            <button key={s.nav} type="button" data-purpose={`home-shortcut-${s.nav}`} onClick={() => onNavigate(s.nav)} className="text-left bg-white p-5 rounded-2xl border border-slate-200 card-shadow hover:border-emerald-300 transition">
              <h3 className="text-sm font-bold text-slate-900">{t(s.titleKey)}</h3>
              <p className="text-xs text-slate-500 mt-1">{t(s.hintKey)}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
