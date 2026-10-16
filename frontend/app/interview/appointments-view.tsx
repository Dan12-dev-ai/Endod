"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import {
  ACTIVE_STATUSES,
  type Appointment,
  appointmentPlace,
  appointmentTitle,
  browserTimezone,
  type FacilityList,
  formatWhen,
  initials,
  localDateTimeToIso,
} from "./data";

type Props = {
  /** data-purpose of a card to highlight (from a notification link). */
  highlightTarget: string | null;
  onToast: (title: string, message: string) => void;
};

type Tab = "upcoming" | "past" | "cancelled";
type ModalState = { mode: "book" } | { mode: "reschedule"; appointment: Appointment } | null;

const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function tabOf(appointment: Appointment, now: number): Tab {
  if (appointment.status === "CANCELLED") return "cancelled";
  if (ACTIVE_STATUSES.includes(appointment.status) && new Date(appointment.scheduled_at).getTime() >= now) {
    return "upcoming";
  }
  return "past";
}

function dateKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function localDateInput(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** The patient's appointments (GET/POST /users/me/appointments, reschedule, cancel). */
export default function AppointmentsView({ highlightTarget, onToast }: Props) {
  const [appointments, setAppointments] = useState<Appointment[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [tab, setTab] = useState<Tab>("upcoming");
  const [typeFilter, setTypeFilter] = useState<"all" | "in_person" | "telehealth">("all");
  const [sortOrder, setSortOrder] = useState<"earliest" | "latest" | "name">("earliest");
  const [confirmCancelId, setConfirmCancelId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [now] = useState(() => Date.now());
  const [month, setMonth] = useState(() => {
    const today = new Date();
    return new Date(today.getFullYear(), today.getMonth(), 1);
  });

  const [modal, setModal] = useState<ModalState>(null);
  const [success, setSuccess] = useState("");
  const [formError, setFormError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formProvider, setFormProvider] = useState("");
  const [formFacility, setFormFacility] = useState("");
  const [formDate, setFormDate] = useState(() => localDateInput(new Date(Date.now() + 86_400_000)));
  const [formTime, setFormTime] = useState("10:00");
  const [formType, setFormType] = useState<"in-person" | "telehealth">("in-person");
  const [formMeetingUrl, setFormMeetingUrl] = useState("");
  const [formNotes, setFormNotes] = useState("");
  const [facilities, setFacilities] = useState<FacilityList["facilities"]>([]);

  const load = useCallback(async () => {
    try {
      setAppointments(await api<Appointment[]>("users/me/appointments", { query: { limit: 200 } }));
      setLoadError("");
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : "Unable to load your appointments.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
  }, [load]);

  // A notification link: show the tab that holds the highlighted card.
  useEffect(() => {
    const target = (appointments ?? []).find((a) => `appointment-card-${a.appointment_id}` === highlightTarget);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- follows the linked appointment
    if (target) setTab(tabOf(target, now));
  }, [appointments, highlightTarget, now]);

  const counts = useMemo(() => {
    const result = { upcoming: 0, past: 0, cancelled: 0 };
    for (const a of appointments ?? []) result[tabOf(a, now)] += 1;
    return result;
  }, [appointments, now]);

  const visible = useMemo(() => {
    const list = (appointments ?? [])
      .filter((a) => tabOf(a, now) === tab)
      .filter((a) => typeFilter === "all" || a.visit_mode === typeFilter);
    const time = (a: Appointment) => new Date(a.scheduled_at).getTime();
    if (sortOrder === "name") list.sort((a, b) => appointmentTitle(a).localeCompare(appointmentTitle(b)));
    else if (sortOrder === "latest") list.sort((a, b) => time(b) - time(a));
    else list.sort((a, b) => time(a) - time(b));
    return list;
  }, [appointments, tab, typeFilter, sortOrder, now]);

  const upcomingSorted = useMemo(
    () => (appointments ?? [])
      .filter((a) => tabOf(a, now) === "upcoming")
      .sort((a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime()),
    [appointments, now],
  );
  const nextVisit = upcomingSorted[0];
  const nextVideo = upcomingSorted.find((a) => a.visit_mode === "telehealth");

  // Days in the shown month that have an active appointment, by visit mode.
  const busyDays = useMemo(() => {
    const days = new Map<string, Appointment["visit_mode"]>();
    for (const a of appointments ?? []) {
      if (a.status === "CANCELLED") continue;
      days.set(dateKey(new Date(a.scheduled_at)), a.visit_mode);
    }
    return days;
  }, [appointments]);

  const openBook = () => {
    setModal({ mode: "book" });
    setSuccess("");
    setFormError("");
    if (facilities.length === 0) {
      api<FacilityList>("users/me/care/facilities", { query: { limit: 100 } })
        .then((list) => setFacilities(list.facilities))
        .catch(() => undefined);
    }
  };

  const openReschedule = (appointment: Appointment) => {
    const at = new Date(appointment.scheduled_at);
    setFormDate(localDateInput(at));
    setFormTime(`${pad(at.getHours())}:${pad(at.getMinutes())}`);
    setModal({ mode: "reschedule", appointment });
    setSuccess("");
    setFormError("");
  };

  const closeModal = () => {
    setModal(null);
    setSuccess("");
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!modal) return;
    const scheduledAt = localDateTimeToIso(formDate, formTime);
    if (!scheduledAt || new Date(scheduledAt) <= new Date()) {
      setFormError("Please choose a date and time in the future.");
      return;
    }
    setIsSubmitting(true);
    setFormError("");
    try {
      if (modal.mode === "reschedule") {
        await api(`users/me/appointments/${modal.appointment.appointment_id}/reschedule`, {
          method: "POST",
          body: { scheduled_at: scheduledAt },
        });
        setSuccess("Appointment moved. Reminders were updated for the new time.");
      } else {
        const telehealth = formType === "telehealth";
        await api("users/me/appointments", {
          method: "POST",
          body: {
            scheduled_at: scheduledAt,
            timezone: browserTimezone(),
            visit_mode: telehealth ? "telehealth" : "in_person",
            provider_name: formProvider.trim() || null,
            facility_id: !telehealth && formFacility ? formFacility : null,
            meeting_url: telehealth ? formMeetingUrl.trim() || null : null,
            notes: formNotes.trim() || null,
          },
        });
        setSuccess("Appointment booked. You'll get reminders based on your notification settings.");
        setFormNotes("");
      }
      await load();
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : "Something went wrong. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const cancelAppointment = async (appointment: Appointment) => {
    setBusyId(appointment.appointment_id);
    try {
      await api(`users/me/appointments/${appointment.appointment_id}/status`, {
        method: "PATCH",
        body: { status: "CANCELLED" },
      });
      onToast("Appointment Cancelled", `${appointmentTitle(appointment)} was cancelled and its reminders stopped.`);
      await load();
    } catch (error) {
      onToast("Could not cancel", error instanceof ApiError ? error.message : "Please try again.");
    } finally {
      setBusyId(null);
      setConfirmCancelId(null);
    }
  };

  const monthLabel = month.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const leadingBlanks = month.getDay();
  const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const todayKey = dateKey(new Date());

  const card = (a: Appointment) => {
    const id = `appointment-card-${a.appointment_id}`;
    const highlighted = highlightTarget === id;
    const telehealth = a.visit_mode === "telehealth";
    const cancelled = a.status === "CANCELLED";
    return (
      <div
        key={a.appointment_id}
        data-purpose={id}
        className={`bg-white rounded-2xl border p-4 card-shadow flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${cancelled ? "opacity-60" : ""} ${highlighted ? "border-emerald-500 ring-2 ring-emerald-200" : "border-slate-200"}`}
      >
        <div className="flex items-center space-x-4 min-w-0">
          <div className={`w-10 h-10 rounded-xl border flex items-center justify-center font-bold text-sm flex-shrink-0 ${telehealth ? "bg-teal-50 border-teal-100 text-teal-600" : "bg-emerald-50 border-emerald-100 text-emerald-600"}`}>
            {initials(appointmentTitle(a))}
          </div>
          <div className="min-w-0">
            <h4 className="text-sm font-bold text-slate-900">{appointmentTitle(a)}</h4>
            <p className="text-xs text-slate-500 mt-0.5">{appointmentPlace(a)}</p>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-0.5 mt-1 text-xs text-slate-500">
              <span>{formatWhen(a.scheduled_at, a.timezone)}</span>
              <span>{telehealth ? "Virtual" : "In person"}</span>
              {a.department && <span>{a.department}</span>}
              {a.time_window !== "exact" && <span>Arrive in the {a.time_window}</span>}
            </div>
            {telehealth && a.meeting_url && tabOf(a, now) === "upcoming" && (
              <a href={a.meeting_url} target="_blank" rel="noopener noreferrer" className="inline-block mt-1 text-xs font-semibold text-teal-700 hover:underline">
                Join video visit
              </a>
            )}
          </div>
        </div>
        {tabOf(a, now) === "upcoming" ? (
          confirmCancelId === a.appointment_id ? (
            <div className="flex items-center gap-2 flex-shrink-0" data-purpose="cancel-confirm">
              <span className="text-xs text-slate-600">Cancel this visit?</span>
              <button type="button" disabled={busyId === a.appointment_id} onClick={() => cancelAppointment(a)} className="px-3 py-1.5 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 rounded-lg transition">
                Yes, cancel
              </button>
              <button type="button" onClick={() => setConfirmCancelId(null)} className="px-3 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-lg transition">
                Keep
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2 flex-shrink-0">
              <button type="button" onClick={() => openReschedule(a)} className="px-3.5 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-lg transition">
                Reschedule
              </button>
              <button type="button" onClick={() => setConfirmCancelId(a.appointment_id)} className="px-3.5 py-1.5 text-xs font-semibold text-rose-700 bg-white border border-rose-200 hover:bg-rose-50 rounded-lg transition">
                Cancel
              </button>
            </div>
          )
        ) : (
          <span className={`px-3 py-1 text-xs font-semibold rounded-lg flex-shrink-0 border ${
            cancelled ? "text-rose-700 bg-rose-50 border-rose-200"
              : a.status === "COMPLETED" ? "text-emerald-700 bg-emerald-50 border-emerald-200"
              : "text-slate-600 bg-slate-50 border-slate-200"
          }`}>
            {cancelled ? "Cancelled" : a.status === "COMPLETED" ? "Completed" : a.status === "MISSED" ? "Missed" : "Past"}
          </span>
        )}
      </div>
    );
  };

  return (
    <>
      <div data-purpose="appointment-view" className="flex-1 min-h-0 overflow-y-auto">
        <div className="space-y-6 pb-6">
          {/* Title */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-slate-200">
            <div>
              <div className="flex items-center space-x-3">
                <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">Appointments</h1>
                <span data-purpose="upcoming-count" className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200">
                  {counts.upcoming} Scheduled
                </span>
              </div>
              <p className="text-xs sm:text-sm text-slate-500 mt-1">Review scheduled visits, reschedule or cancel them.</p>
            </div>
            <button type="button" onClick={openBook} className="inline-flex items-center space-x-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold shadow-sm transition self-start md:self-auto">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2.2} viewBox="0 0 24 24">
                <path d="M12 4v16m8-8H4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>Schedule Visit</span>
            </button>
          </div>

          {/* Stat cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div data-purpose="next-appointment" className="bg-white p-4 rounded-2xl border border-slate-200/90 card-shadow flex items-center space-x-3.5">
              <div className="w-12 h-12 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center flex-shrink-0">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div>
                <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Next Appointment</p>
                <h4 className="text-base font-bold text-slate-900 mt-0.5">{nextVisit ? formatWhen(nextVisit.scheduled_at, nextVisit.timezone) : "None scheduled"}</h4>
                {nextVisit && <span className="text-[11px] text-emerald-600 font-medium">{appointmentTitle(nextVisit)}</span>}
              </div>
            </div>
            <div data-purpose="next-video-visit" className="bg-white p-4 rounded-2xl border border-slate-200/90 card-shadow flex items-center space-x-3.5">
              <div className="w-12 h-12 rounded-xl bg-teal-50 text-teal-600 flex items-center justify-center flex-shrink-0">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div>
                <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Next Video Visit</p>
                <h4 className="text-base font-bold text-slate-900 mt-0.5">{nextVideo ? formatWhen(nextVideo.scheduled_at, nextVideo.timezone) : "None scheduled"}</h4>
                {nextVideo && <span className="text-[11px] text-teal-600 font-medium">{appointmentTitle(nextVideo)}</span>}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            <div className="xl:col-span-2 space-y-5">
              {/* Tabs & Filters */}
              <div className="bg-white p-3.5 rounded-2xl border border-slate-200/90 card-shadow flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center space-x-1 p-1 bg-slate-100 rounded-xl overflow-x-auto">
                  {([
                    { id: "upcoming" as const, label: `Upcoming (${counts.upcoming})` },
                    { id: "past" as const, label: `Past (${counts.past})` },
                    { id: "cancelled" as const, label: `Cancelled (${counts.cancelled})` },
                  ]).map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      data-purpose={`appointment-tab-${t.id}`}
                      onClick={() => setTab(t.id)}
                      className={`px-3.5 py-1.5 rounded-lg text-xs whitespace-nowrap transition ${tab === t.id ? "font-semibold bg-white text-slate-800 shadow-xs" : "font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-200/60"}`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
                <div className="flex items-center space-x-2">
                  <select aria-label="Visit type" data-purpose="appointment-type-filter" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as typeof typeFilter)} className="text-xs bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1.5 text-slate-700 font-medium">
                    <option value="all">All Types</option>
                    <option value="in_person">In Person</option>
                    <option value="telehealth">Video Telehealth</option>
                  </select>
                  <select aria-label="Sort" value={sortOrder} onChange={(e) => setSortOrder(e.target.value as typeof sortOrder)} className="text-xs bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1.5 text-slate-700 font-medium">
                    <option value="earliest">Sort by: Earliest</option>
                    <option value="latest">Sort by: Latest</option>
                    <option value="name">Doctor / Place</option>
                  </select>
                </div>
              </div>

              {loadError && (
                <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">{loadError}</p>
              )}
              <div data-purpose={`appointment-${tab}-list`} className="space-y-3">
                {appointments && visible.length === 0 && (
                  <p data-purpose="appointment-empty" className="text-xs text-slate-500 bg-white border border-slate-200 rounded-2xl p-4">
                    {tab === "upcoming" ? "No upcoming appointments. Use Schedule Visit or the Booking page to book one."
                      : tab === "past" ? "No past appointments yet." : "No cancelled appointments."}
                  </p>
                )}
                {visible.map(card)}
              </div>
            </div>

            {/* Calendar */}
            <div className="space-y-5">
              <div data-purpose="appointment-calendar" className="bg-white rounded-2xl border border-slate-200/90 p-5 card-shadow">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-bold text-slate-900">{monthLabel}</h3>
                  <div className="flex items-center space-x-1">
                    <button type="button" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d="M15 19l-7-7 7-7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                    </button>
                    <button type="button" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-7 text-center text-[11px] font-semibold text-slate-400 mb-2">
                  {WEEKDAYS.map((d) => <div key={d}>{d}</div>)}
                </div>
                <div className="grid grid-cols-7 gap-1 text-center text-xs">
                  {Array.from({ length: leadingBlanks }, (_, i) => <span key={`blank-${i}`} />)}
                  {Array.from({ length: daysInMonth }, (_, i) => i + 1).map((day) => {
                    const key = dateKey(new Date(month.getFullYear(), month.getMonth(), day));
                    const mode = busyDays.get(key);
                    let cls = "p-2 text-slate-700 rounded-lg";
                    if (key === todayKey) cls = "p-2 rounded-lg ring-2 ring-emerald-300 font-bold text-slate-900";
                    if (mode === "in_person") cls = "p-2 rounded-lg bg-emerald-600 text-white font-bold";
                    if (mode === "telehealth") cls = "p-2 rounded-lg bg-teal-100 text-teal-800 font-bold";
                    return <span key={key} data-purpose={mode ? "calendar-busy-day" : undefined} className={cls}>{day}</span>;
                  })}
                </div>
                <div className="mt-4 pt-3 border-t border-slate-100 flex items-center gap-4 text-[11px] text-slate-500">
                  <div className="flex items-center space-x-1.5"><span className="w-2.5 h-2.5 rounded-full bg-emerald-600"></span><span>In-Person</span></div>
                  <div className="flex items-center space-x-1.5"><span className="w-2.5 h-2.5 rounded-full bg-teal-500"></span><span>Telehealth</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ===== Book / Reschedule Modal ===== */}
      {modal && (
        <div data-purpose="appointment-modal" className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-3xl max-w-lg w-full p-6 shadow-2xl border border-slate-200 max-h-[95vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div>
                <h3 className="text-base font-bold text-slate-900">
                  {modal.mode === "reschedule" ? `Reschedule: ${appointmentTitle(modal.appointment)}` : "Schedule an Appointment"}
                </h3>
                <p className="text-xs text-slate-500">
                  {modal.mode === "reschedule" ? "Choose a new date and time" : "Select date, time, and care format"}
                </p>
              </div>
              <button type="button" aria-label="Close" onClick={closeModal} className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>

            {success ? (
              <div data-purpose="appointment-modal-success" className="mt-4 p-4 rounded-2xl bg-emerald-50 border border-emerald-200 text-center">
                <h4 className="text-sm font-bold text-emerald-900">{modal.mode === "reschedule" ? "Appointment Moved" : "Appointment Booked"}</h4>
                <p className="text-xs text-emerald-700 mt-1">{success}</p>
                <button type="button" onClick={closeModal} className="mt-3 px-4 py-1.5 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg">
                  Done
                </button>
              </div>
            ) : (
              <form onSubmit={submit} className="mt-4 space-y-4">
                {modal.mode === "book" && (
                  <>
                    <div>
                      <label htmlFor="appointment-provider" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Doctor (optional)</label>
                      <input id="appointment-provider" maxLength={120} value={formProvider} onChange={(e) => setFormProvider(e.target.value)} placeholder="e.g. Dr. Abebe Kebede" className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800 focus:bg-white focus:ring-2 focus:ring-emerald-500 font-medium" />
                    </div>
                    <div>
                      <span className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Appointment Type</span>
                      <div className="grid grid-cols-2 gap-2">
                        <label className={`flex items-center space-x-2 p-2.5 rounded-xl border cursor-pointer ${formType === "in-person" ? "border-emerald-500 bg-emerald-50/50" : "border-slate-200 hover:bg-slate-50"}`}>
                          <input type="radio" name="apptVisitType" checked={formType === "in-person"} onChange={() => setFormType("in-person")} className="text-emerald-600" />
                          <span className="text-xs font-bold text-emerald-900">In-Person Facility</span>
                        </label>
                        <label className={`flex items-center space-x-2 p-2.5 rounded-xl border cursor-pointer ${formType === "telehealth" ? "border-emerald-500 bg-emerald-50/50" : "border-slate-200 hover:bg-slate-50"}`}>
                          <input type="radio" name="apptVisitType" checked={formType === "telehealth"} onChange={() => setFormType("telehealth")} className="text-emerald-600" />
                          <span className="text-xs font-medium text-slate-700">Video Telehealth</span>
                        </label>
                      </div>
                    </div>
                    {formType === "in-person" ? (
                      <div>
                        <label htmlFor="appointment-facility" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Facility (optional)</label>
                        <select id="appointment-facility" value={formFacility} onChange={(e) => setFormFacility(e.target.value)} className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800 font-medium">
                          <option value="">Not listed / not sure</option>
                          {facilities.map((f) => <option key={f.id} value={f.id}>{f.name} — {f.city}</option>)}
                        </select>
                      </div>
                    ) : (
                      <div>
                        <label htmlFor="appointment-meeting-url" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Video link (optional)</label>
                        <input id="appointment-meeting-url" type="url" maxLength={500} value={formMeetingUrl} onChange={(e) => setFormMeetingUrl(e.target.value)} placeholder="https://..." className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800" />
                      </div>
                    )}
                  </>
                )}

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="appointment-date" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Date</label>
                    <input id="appointment-date" type="date" required min={localDateInput(new Date())} value={formDate} onChange={(e) => setFormDate(e.target.value)} className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800 font-medium" />
                  </div>
                  <div>
                    <label htmlFor="appointment-time" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Time</label>
                    <input id="appointment-time" type="time" required value={formTime} onChange={(e) => setFormTime(e.target.value)} className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800 font-medium" />
                  </div>
                </div>

                {modal.mode === "book" && (
                  <div>
                    <label htmlFor="appointment-notes" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Symptoms or Visit Notes</label>
                    <textarea id="appointment-notes" rows={2} maxLength={1000} value={formNotes} onChange={(e) => setFormNotes(e.target.value)} placeholder="Briefly describe what you'd like to discuss..." className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800" />
                  </div>
                )}

                {formError && (
                  <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" data-purpose="appointment-error" role="alert">{formError}</p>
                )}

                <div className="pt-2 flex items-center justify-end space-x-3">
                  <button type="button" onClick={closeModal} className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl transition">
                    Cancel
                  </button>
                  <button type="submit" disabled={isSubmitting} className="px-5 py-2 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 rounded-xl shadow-sm transition">
                    {isSubmitting ? "Saving..." : modal.mode === "reschedule" ? "Confirm Reschedule" : "Confirm Booking"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </>
  );
}
