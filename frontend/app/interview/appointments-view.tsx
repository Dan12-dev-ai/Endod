"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n, type TranslationKey } from "../lib/i18n";
import {
  ACTIVE_STATUSES,
  type Appointment,
  appointmentPlace,
  type BookingPaymentCheck,
  CHAPA_CHECKOUT_ORIGIN,
  type PaymentsStatus,
  appointmentTitle,
  browserTimezone,
  departmentLabel,
  type FacilityList,
  formatBirr,
  formatWhen,
  initials,
  localDateTimeToIso,
  safeCheckoutUrl,
  TIME_WINDOWS,
} from "./data";
import { RowBones, Skeleton } from "../components/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { QueueCard } from "./care-cards";

type Props = {
  /** data-purpose of a card to highlight (from a notification link). */
  highlightTarget: string | null;
  onToast: (title: string, message: string) => void;
};

type Tab = "upcoming" | "past" | "cancelled";
type ModalState = { mode: "book" } | { mode: "reschedule"; appointment: Appointment } | null;

/**
 * The column headers of the month grid, in the active locale. Built from a
 * known Sunday (7 Jan 2024) so the week starts on the same day everywhere.
 */
function weekdayLabels(locale: string): string[] {
  const formatter = new Intl.DateTimeFormat(locale, { weekday: "short" });
  return Array.from({ length: 7 }, (_, i) =>
    formatter.format(new Date(2024, 0, 7 + i)),
  );
}

/** An active visit stays "upcoming" until it ends, so one in progress can still be joined. */
function tabOf(appointment: Appointment, now: number): Tab {
  if (appointment.status === "CANCELLED") return "cancelled";
  const ends = new Date(appointment.scheduled_at).getTime() + (appointment.duration_minutes || 30) * 60_000;
  if (ACTIVE_STATUSES.includes(appointment.status) && ends >= now) return "upcoming";
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
  const { t, locale } = useI18n();
  const [appointments, setAppointments] = useState<Appointment[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [tab, setTab] = useState<Tab>("upcoming");
  const [typeFilter, setTypeFilter] = useState<"all" | "in_person" | "telehealth">("all");
  const [sortOrder, setSortOrder] = useState<"earliest" | "latest" | "name">("earliest");
  const [confirmCancelId, setConfirmCancelId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
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
  const [formWindow, setFormWindow] = useState<Appointment["time_window"]>("exact");
  const [facilities, setFacilities] = useState<FacilityList["facilities"]>([]);

  // Where "Pay now" may lead (Chapa's checkout; see safeCheckoutUrl).
  const [checkoutOrigins, setCheckoutOrigins] = useState<string[]>([CHAPA_CHECKOUT_ORIGIN]);
  useEffect(() => {
    let cancelled = false;
    api<PaymentsStatus>("users/me/payments/status")
      .then((status) => !cancelled && setCheckoutOrigins(status.checkout_origins))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      setAppointments(await api<Appointment[]>("users/me/appointments", { query: { limit: 200 } }));
      setLoadError("");
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : t("appointments.error.load"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is stable per language
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
  }, [load]);

  // Back from Chapa (?payment=<tx_ref>): the backend checks the payment with
  // Chapa itself (the address proves nothing), a few times while Chapa has
  // not confirmed it yet.
  useEffect(() => {
    const txRef = new URL(window.location.href).searchParams.get("payment");
    if (!txRef) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = async (attempt: number) => {
      let result: BookingPaymentCheck | null = null;
      try {
        result = await api<BookingPaymentCheck>(`users/me/booking-payments/${encodeURIComponent(txRef)}`);
      } catch {
        result = null;
      }
      if (cancelled) return;
      if (attempt === 0) {
        // Handled here: a refresh does not check (and toast) again.
        const url = new URL(window.location.href);
        url.searchParams.delete("payment");
        window.history.replaceState({}, "", url);
      }
      await load();
      if (cancelled) return;
      const booked = result?.status === "paid" && result.appointment.hospital_booking?.payment.status === "paid";
      if (booked) {
        onToast(t("appointments.paymentToast.paidTitle"), t("appointments.paymentToast.paid"));
      } else if (result && result.status !== "pending") {
        // Expired, not matching, or paid after the time was released: refunded (shown on the card).
        onToast(t("appointments.paymentToast.failedTitle"), t("appointments.paymentToast.failed"));
      } else if (attempt < 4) {
        timer = setTimeout(() => void check(attempt + 1), 3000);
      } else {
        onToast(t("appointments.paymentToast.pendingTitle"), t("appointments.paymentToast.pending"));
      }
    };
    void check(0);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on arrival from Chapa
  }, []);

  // Keep "upcoming" and "past" honest on a page left open.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);

  // A notification link: show the tab that holds the highlighted card, once
  // per link, so later reloads (after a cancel or reschedule) keep the tab.
  const followedTarget = useRef<string | null>(null);
  useEffect(() => {
    if (!highlightTarget || followedTarget.current === highlightTarget) return;
    const target = (appointments ?? []).find((a) => `appointment-card-${a.appointment_id}` === highlightTarget);
    if (!target) return;
    followedTarget.current = highlightTarget;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- follows the linked appointment
    setTab(tabOf(target, now));
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
    if (sortOrder === "name") list.sort((a, b) => appointmentTitle(a, t).localeCompare(appointmentTitle(b, t)));
    else if (sortOrder === "latest") list.sort((a, b) => time(b) - time(a));
    else list.sort((a, b) => time(a) - time(b));
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is stable per language
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
    setFormWindow(appointment.time_window);
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
      setFormError(t("appointments.error.future"));
      return;
    }
    setIsSubmitting(true);
    setFormError("");
    try {
      if (modal.mode === "reschedule") {
        await api(`users/me/appointments/${modal.appointment.appointment_id}/reschedule`, {
          method: "POST",
          body: { scheduled_at: scheduledAt, time_window: formWindow },
        });
        setSuccess(t("appointments.toast.moved"));
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
        setSuccess(t("appointments.toast.booked"));
        setFormNotes("");
      }
      await load();
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : t("common.somethingWrong"));
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
      onToast(t("appointments.toast.cancelledTitle"), t("appointments.toast.cancelled", { name: appointmentTitle(appointment, t) }));
      await load();
    } catch (error) {
      onToast(t("appointments.toast.couldNotCancel"), error instanceof ApiError ? error.message : t("common.pleaseTryAgain"));
    } finally {
      setBusyId(null);
      setConfirmCancelId(null);
    }
  };

  const monthLabel = month.toLocaleDateString(locale, { month: "long", year: "numeric" });
  const weekdays = weekdayLabels(locale);
  const leadingBlanks = month.getDay();
  const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const todayKey = dateKey(new Date());

    const card = (a: Appointment) => {
    const id = `appointment-card-${a.appointment_id}`;
    const highlighted = highlightTarget === id;
    const telehealth = a.visit_mode === "telehealth";
    const cancelled = a.status === "CANCELLED";
    const timeWindowLabel = TIME_WINDOWS.find((w) => w.value === a.time_window);
    // Booked and paid at an Endod partner hospital.
    const hb = a.hospital_booking ?? null;
    const payment = hb?.payment.status ?? null;
    const closed = hb && (hb.state === "rejected" || hb.state === "cancelled" || hb.state === "payment_expired");
    const unpaid = hb?.state === "awaiting_payment";
    const payNow = unpaid ? safeCheckoutUrl(hb.payment.checkout_url, checkoutOrigins) : null;
    const amount = hb ? formatBirr(hb.total, locale) : "";
    return (
      <div
        key={a.appointment_id}
        data-purpose={id}
        className={`bg-white dark:bg-gray-800 rounded-2xl border p-4 card-shadow flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${cancelled ? "opacity-60" : ""} ${highlighted ? "border-black ring-2 ring-gray-300" : "border-slate-200"}`}
      >
        <div className="flex items-center space-x-4 min-w-0">
          <div className={`w-10 h-10 rounded-xl border flex items-center justify-center font-bold text-sm flex-shrink-0 ${telehealth ? "bg-gray-50 border-gray-200 text-black" : "bg-gray-50 border-gray-200 text-black"}`}>
            {initials(appointmentTitle(a, t))}
          </div>
          <div className="min-w-0">
            <h4 className="text-sm font-bold text-slate-900 dark:text-gray-100">{appointmentTitle(a, t)}</h4>
            <p className="text-xs text-slate-500 mt-0.5">{appointmentPlace(a, t)}</p>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-0.5 mt-1 text-xs text-slate-500">
              <span>{formatWhen(a.scheduled_at, locale)}</span>
              <span>{telehealth ? t("appointments.virtual") : t("appointments.inPersonTag")}</span>
              {a.department && <span>{departmentLabel(a.department, t)}</span>}
              {a.time_window !== "exact" && timeWindowLabel && (
                <span>{t("appointments.arriveIn", { window: t(timeWindowLabel.labelKey) })}</span>
              )}
            </div>
            {hb && (
              <div className="flex flex-wrap items-center gap-2 mt-1.5" data-purpose="hospital-booking">
                <span
                  className={`text-[11px] font-semibold rounded px-1.5 py-0.5 ${
                    hb.state === "confirmed" || hb.state === "completed" ? "bg-gray-50 text-gray-900"
                      : closed ? "bg-rose-50 text-rose-700"
                      : unpaid ? "bg-amber-50 text-amber-800" : "bg-sky-50 text-sky-700"
                  }`}
                  data-purpose="hospital-state"
                >
                  {t(`appointments.hospital.${hb.state}` as TranslationKey)}
                </span>
                <span className="text-[11px] text-slate-500" data-purpose="payment-status" data-status={payment ?? undefined}>
                  {payment === "awaiting_payment"
                    ? t("appointments.payment.awaiting", {
                        amount,
                        time: hb.payment.due_at
                          ? new Date(hb.payment.due_at).toLocaleTimeString(locale, { timeStyle: "short" })
                          : "",
                      })
                    : payment === "refund_pending" ? t("appointments.payment.refundPending", { amount })
                    : payment === "refunded" ? t("appointments.refunded", { amount })
                    : payment === "expired" ? t("appointments.payment.expired")
                    : t("appointments.paid", { amount })}
                </span>
                {hb.reason && closed && hb.state !== "payment_expired" && (
                  <span className="text-[11px] text-slate-500">· {hb.reason}</span>
                )}
              </div>
            )}
            {payNow && tabOf(a, now) === "upcoming" && (
              <a
                className="inline-flex items-center gap-1.5 mt-2 px-3 py-1.5 rounded-lg bg-black hover:bg-gray-800 text-white text-xs font-semibold"
                data-purpose="pay-now"
                href={payNow}
              >
                {t("appointments.payNow")}
              </a>
            )}
            {hb?.video_ready && tabOf(a, now) === "upcoming" && (
              <a
                className="inline-flex items-center gap-1.5 mt-2 px-3 py-1.5 rounded-lg bg-black hover:bg-gray-800 text-white text-xs font-semibold"
                data-purpose="join-video"
                href={`/visit/${a.appointment_id}`}
              >
                {t("appointments.joinVideo")}
              </a>
            )}
            {!hb && telehealth && a.meeting_url && tabOf(a, now) === "upcoming" && (
              <a href={a.meeting_url} target="_blank" rel="noopener noreferrer" className="inline-block mt-1 text-xs font-semibold text-black hover:underline">
                {t("appointments.joinVideo")}
              </a>
            )}
          </div>
        </div>
        {tabOf(a, now) === "upcoming" ? (
          confirmCancelId === a.appointment_id ? (
            <div className="flex items-center gap-2 flex-shrink-0" data-purpose="cancel-confirm">
              <span className="text-xs text-slate-600">
                {unpaid ? t("appointments.cancelUnpaid")
                  : hb ? t("appointments.cancelRefund", { amount }) : t("appointments.cancelThis")}
              </span>
              <button type="button" disabled={busyId === a.appointment_id} onClick={() => cancelAppointment(a)} className="px-3 py-1.5 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 rounded-lg transition">
                {t("appointments.yesCancel")}
              </button>
              <button type="button" onClick={() => setConfirmCancelId(null)} className="px-3 py-1.5 text-xs font-semibold text-slate-700 bg-white dark:bg-gray-800 border border-slate-300 hover:bg-slate-50 rounded-lg transition">
                {t("appointments.keep")}
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2 flex-shrink-0">
              {/* A paid hospital visit is changed by cancelling (refunded) and booking again. */}
              {!hb && (
                <button type="button" onClick={() => openReschedule(a)} className="px-3.5 py-1.5 text-xs font-semibold text-slate-700 bg-white dark:bg-gray-800 border border-slate-300 hover:bg-slate-50 rounded-lg transition">
                  {t("appointments.reschedule")}
                </button>
              )}
              <button type="button" onClick={() => setConfirmCancelId(a.appointment_id)} className="px-3.5 py-1.5 text-xs font-semibold text-rose-700 bg-white dark:bg-gray-800 border border-rose-200 hover:bg-rose-50 rounded-lg transition">
                {t("appointments.cancel")}
              </button>
            </div>
          )
        ) : (
          <span className={`px-3 py-1 text-xs font-semibold rounded-lg flex-shrink-0 border ${
            cancelled ? "text-rose-700 bg-rose-50 border-rose-200"
              : a.status === "COMPLETED" ? "text-gray-900 bg-gray-50 border-gray-200"
              : "text-slate-600 bg-slate-50 border-slate-200"
          }`}>
            {cancelled ? t("appointments.status.cancelled")
              : a.status === "COMPLETED" ? t("appointments.status.completed")
              : a.status === "MISSED" ? t("appointments.status.missed")
              : t("appointments.status.past")}
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
                <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 dark:text-gray-100 tracking-tight">{t("appointments.title")}</h1>
                <span data-purpose="upcoming-count" className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-black border border-gray-200">
                  {t("appointments.scheduledCount", { count: counts.upcoming })}
                </span>
              </div>
            </div>
            <button type="button" onClick={openBook} className="hidden lg:inline-flex items-center space-x-2 px-4 py-2 rounded-xl bg-black hover:bg-gray-800 text-white text-xs font-semibold shadow-sm transition self-start md:self-auto">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2.2} viewBox="0 0 24 24">
                <path d="M12 4v16m8-8H4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>{t("appointments.scheduleVisit")}</span>
            </button>
          </div>

          <QueueCard />

          {/* Stat cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div data-purpose="next-appointment" className="bg-white dark:bg-gray-800 p-4 rounded-2xl border border-slate-200/90 card-shadow flex items-center space-x-3.5">
              <div className="w-12 h-12 rounded-xl bg-gray-50 text-black flex items-center justify-center flex-shrink-0">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div>
                <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">{t("appointments.nextAppointment")}</p>
                <h4 className="text-base font-bold text-slate-900 dark:text-gray-100 mt-0.5">{nextVisit ? formatWhen(nextVisit.scheduled_at, locale) : t("appointments.noneScheduled")}</h4>
                {nextVisit && <span className="text-[11px] text-black dark:text-gray-200 font-medium">{appointmentTitle(nextVisit, t)}</span>}
              </div>
            </div>
            <div data-purpose="next-video-visit" className="bg-white dark:bg-gray-800 p-4 rounded-2xl border border-slate-200/90 card-shadow flex items-center space-x-3.5">
              <div className="w-12 h-12 rounded-xl bg-gray-50 text-black flex items-center justify-center flex-shrink-0">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div>
                <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">{t("appointments.nextVideoVisit")}</p>
                <h4 className="text-base font-bold text-slate-900 dark:text-gray-100 mt-0.5">{nextVideo ? formatWhen(nextVideo.scheduled_at, locale) : t("appointments.noneScheduled")}</h4>
                {nextVideo && <span className="text-[11px] text-black dark:text-gray-200 font-medium">{appointmentTitle(nextVideo, t)}</span>}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            <div className="xl:col-span-2 space-y-5">
              {/* Tabs & Filters */}
              <div className="bg-white dark:bg-gray-800 p-3.5 rounded-2xl border border-slate-200/90 card-shadow flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center space-x-1 p-1 bg-slate-100 dark:bg-gray-700 rounded-xl overflow-x-auto">
                  {([
                    { id: "upcoming" as const, label: t("appointments.tabUpcoming", { count: counts.upcoming }) },
                    { id: "past" as const, label: t("appointments.tabPast", { count: counts.past }) },
                    { id: "cancelled" as const, label: t("appointments.tabCancelled", { count: counts.cancelled }) },
                  ]).map((t2) => (
                    <button
                      key={t2.id}
                      type="button"
                      data-purpose={`appointment-tab-${t2.id}`}
                      onClick={() => setTab(t2.id)}
                      className={`px-3.5 py-1.5 rounded-lg text-xs whitespace-nowrap transition ${tab === t2.id ? "font-semibold bg-white dark:bg-gray-800 text-slate-800 shadow-xs" : "font-medium text-slate-600 hover:text-slate-900 dark:text-gray-100 hover:bg-slate-200/60"}`}
                    >
                      {t2.label}
                    </button>
                  ))}
                </div>
                <div className="flex items-center space-x-2">
                  <Select value={typeFilter} onValueChange={(v) => setTypeFilter(v as typeof typeFilter)}>
                    <SelectTrigger
                      aria-label={t("appointments.modal.type")}
                      className="text-xs w-auto"
                      data-purpose="appointment-type-filter"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">{t("appointments.allTypes")}</SelectItem>
                      <SelectItem value="in_person">{t("appointments.inPerson")}</SelectItem>
                      <SelectItem value="telehealth">{t("appointments.videoTelehealth")}</SelectItem>
                    </SelectContent>
                  </Select>
                  <Select value={sortOrder} onValueChange={(v) => setSortOrder(v as typeof sortOrder)}>
                    <SelectTrigger aria-label={t("booking.sort")} className="text-xs w-auto">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="earliest">{t("appointments.sortEarliest")}</SelectItem>
                      <SelectItem value="latest">{t("appointments.sortLatest")}</SelectItem>
                      <SelectItem value="name">{t("appointments.sortName")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {loadError && (
                <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">{loadError}</p>
              )}
              <div data-purpose={`appointment-${tab}-list`} className="space-y-3">
                {!appointments && !loadError && (
                  <Skeleton className="space-y-3" label={t("common.loading")}>
                    <RowBones />
                    <RowBones />
                    <RowBones />
                  </Skeleton>
                )}
                {appointments && visible.length === 0 && (
                  <p data-purpose="appointment-empty" className="text-xs text-slate-500 bg-white dark:bg-gray-800 border border-slate-200 rounded-2xl p-4">
                    {tab === "upcoming" ? t("appointments.emptyUpcoming")
                      : tab === "past" ? t("appointments.emptyPast") : t("appointments.emptyCancelled")}
                  </p>
                )}
                {visible.map(card)}
              </div>
            </div>

            {/* Calendar */}
            <div className="space-y-5">
              <div data-purpose="appointment-calendar" className="bg-white dark:bg-gray-800 rounded-2xl border border-slate-200/90 p-5 card-shadow">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-bold text-slate-900 dark:text-gray-100">{monthLabel}</h3>
                  <div className="flex items-center space-x-1">
                    <button type="button" aria-label={t("appointments.previousMonth")} onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d="M15 19l-7-7 7-7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                    </button>
                    <button type="button" aria-label={t("appointments.nextMonth")} onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-7 text-center text-[11px] font-semibold text-slate-400 mb-2">
                  {weekdays.map((d) => <div key={d}>{d}</div>)}
                </div>
                <div className="grid grid-cols-7 gap-1 text-center text-xs">
                  {Array.from({ length: leadingBlanks }, (_, i) => <span key={`blank-${i}`} />)}
                  {Array.from({ length: daysInMonth }, (_, i) => i + 1).map((day) => {
                    const key = dateKey(new Date(month.getFullYear(), month.getMonth(), day));
                    const mode = busyDays.get(key);
                    let cls = "p-2 text-slate-700 rounded-lg";
                    if (key === todayKey) cls = "p-2 rounded-lg ring-2 ring-gray-400 font-bold text-slate-900 dark:text-gray-100";
                    if (mode === "in_person") cls = "p-2 rounded-lg bg-black text-white font-bold";
                    if (mode === "telehealth") cls = "p-2 rounded-lg bg-gray-200 text-black font-bold";
                    return <span key={key} data-purpose={mode ? "calendar-busy-day" : undefined} className={cls}>{day}</span>;
                  })}
                </div>
                <div className="mt-4 pt-3 border-t border-slate-100 flex items-center gap-4 text-[11px] text-slate-500">
                  <div className="flex items-center space-x-1.5"><span className="w-2.5 h-2.5 rounded-full bg-black"></span><span>{t("appointments.legendInPerson")}</span></div>
                  <div className="flex items-center space-x-1.5"><span className="w-2.5 h-2.5 rounded-full bg-gray-200 border border-gray-400"></span><span>{t("appointments.legendTelehealth")}</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ===== Book / Reschedule Modal ===== */}
      {modal && (
        <div data-purpose="appointment-modal" className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-800 rounded-3xl max-w-lg w-full p-6 shadow-2xl border border-slate-200 max-h-[95vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div>
                <h3 className="text-base font-bold text-slate-900 dark:text-gray-100">
                  {modal.mode === "reschedule" ? t("appointments.modal.rescheduleTitle", { name: appointmentTitle(modal.appointment, t) }) : t("appointments.modal.scheduleTitle")}
                </h3>
                <p className="text-xs text-slate-500">
                  {modal.mode === "reschedule" ? t("appointments.modal.chooseNew") : t("appointments.modal.selectDetails")}
                </p>
              </div>
              <button type="button" aria-label={t("common.close")} onClick={closeModal} className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>

            {success ? (
              <div data-purpose="appointment-modal-success" className="mt-4 p-4 rounded-2xl bg-gray-50 border border-gray-200 text-center">
                <h4 className="text-sm font-bold text-black">{modal.mode === "reschedule" ? t("appointments.modal.moved") : t("appointments.modal.booked")}</h4>
                <p className="text-xs text-gray-900 mt-1">{success}</p>
                <button type="button" onClick={closeModal} className="mt-3 px-4 py-1.5 text-xs font-semibold text-white bg-black hover:bg-gray-800 rounded-lg">
                  {t("common.done")}
                </button>
              </div>
            ) : (
              <form onSubmit={submit} className="mt-4 space-y-4">
                {modal.mode === "book" && (
                  <>
                    <div>
                      <label htmlFor="appointment-provider" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">{t("appointments.modal.doctor")}</label>
                      <input id="appointment-provider" maxLength={120} value={formProvider} onChange={(e) => setFormProvider(e.target.value)} placeholder={t("appointments.modal.doctorPlaceholder")} className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800 focus:bg-white dark:bg-gray-800 focus:ring-2 focus:ring-black font-medium" />
                    </div>
                    <div>
                      <span className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">{t("appointments.modal.type")}</span>
                      <div className="grid grid-cols-2 gap-2">
                        <label className={`flex items-center space-x-2 p-2.5 rounded-xl border cursor-pointer ${formType === "in-person" ? "border-black bg-gray-50/50" : "border-slate-200 hover:bg-slate-50"}`}>
                          <input type="radio" name="apptVisitType" checked={formType === "in-person"} onChange={() => setFormType("in-person")} className="text-black" />
                          <span className="text-xs font-bold text-black">{t("appointments.modal.inPersonFacility")}</span>
                        </label>
                        <label className={`flex items-center space-x-2 p-2.5 rounded-xl border cursor-pointer ${formType === "telehealth" ? "border-black bg-gray-50/50" : "border-slate-200 hover:bg-slate-50"}`}>
                          <input type="radio" name="apptVisitType" checked={formType === "telehealth"} onChange={() => setFormType("telehealth")} className="text-black" />
                          <span className="text-xs font-medium text-slate-700">{t("appointments.videoTelehealth")}</span>
                        </label>
                      </div>
                    </div>
                    {formType === "in-person" ? (
                      <div>
                        <label htmlFor="appointment-facility" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">{t("appointments.modal.facility")}</label>
                        <Select value={formFacility === "" ? "none" : formFacility} onValueChange={(v) => setFormFacility(v === "none" ? "" : v)}>
                          <SelectTrigger className="w-full text-xs" id="appointment-facility">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">{t("appointments.modal.notListed")}</SelectItem>
                            {facilities.map((f) => (
                              <SelectItem key={f.id} value={f.id}>
                                {f.name} — {f.city}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    ) : (
                      <div>
                        <label htmlFor="appointment-meeting-url" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">{t("appointments.modal.videoLink")}</label>
                        <input id="appointment-meeting-url" type="url" maxLength={500} value={formMeetingUrl} onChange={(e) => setFormMeetingUrl(e.target.value)} placeholder="https://..." className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800" />
                      </div>
                    )}
                  </>
                )}

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="appointment-date" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">{t("appointments.modal.date")}</label>
                    <input id="appointment-date" type="date" required min={localDateInput(new Date())} value={formDate} onChange={(e) => setFormDate(e.target.value)} className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800 font-medium" />
                  </div>
                  <div>
                    <label htmlFor="appointment-time" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">{t("appointments.modal.time")}</label>
                    <input id="appointment-time" type="time" required value={formTime} onChange={(e) => setFormTime(e.target.value)} className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800 font-medium" />
                  </div>
                </div>

                {modal.mode === "reschedule" && modal.appointment.visit_mode === "in_person" && (
                  <div>
                    <label htmlFor="appointment-window" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">{t("appointments.modal.arrivalWindow")}</label>
                    <Select value={formWindow} onValueChange={(v) => setFormWindow(v as Appointment["time_window"])}>
                      <SelectTrigger className="w-full text-xs" id="appointment-window">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {TIME_WINDOWS.map((w) => (
                          <SelectItem key={w.value} value={w.value}>
                            {t(w.labelKey)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {modal.mode === "book" && (
                  <div>
                    <label htmlFor="appointment-notes" className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">{t("appointments.modal.symptoms")}</label>
                    <textarea id="appointment-notes" rows={2} maxLength={1000} value={formNotes} onChange={(e) => setFormNotes(e.target.value)} placeholder={t("appointments.modal.symptomsPlaceholder")} className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800" />
                  </div>
                )}

                {formError && (
                  <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" data-purpose="appointment-error" role="alert">{formError}</p>
                )}

                <div className="pt-2 flex items-center justify-end space-x-3">
                  <button type="button" onClick={closeModal} className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl transition">
                    {t("common.cancel")}
                  </button>
                  <button type="submit" disabled={isSubmitting} className="px-5 py-2 text-xs font-bold text-white bg-black hover:bg-gray-800 disabled:opacity-60 rounded-xl shadow-sm transition">
                    {isSubmitting ? t("common.saving") : modal.mode === "reschedule" ? t("appointments.modal.confirmReschedule") : t("appointments.modal.confirmBooking")}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
      {!modal && (
        <button
          type="button"
          aria-label={t("appointments.scheduleVisit")}
          data-purpose="appointment-fab"
          onClick={openBook}
          className="fixed bottom-20 right-4 z-50 lg:hidden flex items-center justify-center w-12 h-12 rounded-full bg-black hover:bg-gray-800 dark:bg-gray-700 dark:hover:bg-gray-600 text-white shadow-lg transition"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={2.2} viewBox="0 0 24 24">
            <path d="M12 4v16m8-8H4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
    </>
  );
}
