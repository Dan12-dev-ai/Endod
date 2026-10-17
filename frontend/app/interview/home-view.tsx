"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { type Appointment, appointmentTitle, formatWhen } from "./data";

type Props = {
  firstName: string;
  onNavigate: (nav: string) => void;
};

const SHORTCUTS = [
  { nav: "booking", title: "Book a visit", hint: "Find a hospital or clinic and reserve a time." },
  { nav: "appointment", title: "My appointments", hint: "Reschedule or cancel upcoming visits." },
  { nav: "followup", title: "Medical records", hint: "Past visits, diagnoses and medicines." },
  { nav: "message", title: "Notifications", hint: "Appointment updates and account security." },
];

/** The landing screen: what is next, and where to go. */
export default function HomeView({ firstName, onNavigate }: Props) {
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
            {firstName ? `Welcome, ${firstName}` : "Welcome"}
          </h1>
          <p className="text-sm text-slate-500 mt-1">Your visits, records and updates in one place.</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <button type="button" data-purpose="home-next-appointment" onClick={() => onNavigate("appointment")} className="text-left bg-white p-5 rounded-2xl border border-slate-200 card-shadow hover:border-emerald-300 transition">
            <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Next Appointment</p>
            <h2 className="text-base font-bold text-slate-900 mt-1">
              {next === undefined ? "Loading..." : next ? formatWhen(next.scheduled_at) : "None scheduled"}
            </h2>
            {next && <p className="text-xs text-emerald-600 font-medium mt-0.5">{appointmentTitle(next)}</p>}
          </button>
          <button type="button" data-purpose="home-unread" onClick={() => onNavigate("message")} className="text-left bg-white p-5 rounded-2xl border border-slate-200 card-shadow hover:border-emerald-300 transition">
            <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Notifications</p>
            <h2 className="text-base font-bold text-slate-900 mt-1">
              {unread === null ? "—" : unread === 0 ? "You're up to date" : `${unread} unread`}
            </h2>
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {SHORTCUTS.map((s) => (
            <button key={s.nav} type="button" data-purpose={`home-shortcut-${s.nav}`} onClick={() => onNavigate(s.nav)} className="text-left bg-white p-5 rounded-2xl border border-slate-200 card-shadow hover:border-emerald-300 transition">
              <h3 className="text-sm font-bold text-slate-900">{s.title}</h3>
              <p className="text-xs text-slate-500 mt-1">{s.hint}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
