"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n } from "../lib/i18n";
import {
  type Appointment,
  browserTimezone,
  departmentLabel,
  DEPARTMENT_KEYS,
  type Facility,
  type FacilityList,
  formatBirr,
  formatWhen,
  initials,
  localDateTimeToIso,
  type Quote,
  TIME_WINDOWS,
} from "./data";
import HospitalMap, { type MapPoint } from "./hospital-map";
import { RowBones, Skeleton } from "../components/skeleton";

type Props = {
  patientId: string;
  onToast: (title: string, message: string) => void;
  /** Open the Wallet section (to add money). */
  onOpenWallet?: () => void;
};

type Coords = { latitude: number; longitude: number };

function todayLocal(offsetDays = 0): string {
  const now = new Date();
  now.setDate(now.getDate() + offsetDays);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Hospital directory and in-person booking (GET /users/me/care/facilities, POST /users/me/appointments). */
export default function BookingView({ patientId, onToast, onOpenWallet }: Props) {
  const { t, locale } = useI18n();
  const [searchQuery, setSearchQuery] = useState("");
  const [department, setDepartment] = useState("");
  const [sort, setSort] = useState<"name" | "distance">("name");
  const [coords, setCoords] = useState<Coords | null>(null);
  const [directory, setDirectory] = useState<FacilityList | null>(null);
  const [loadError, setLoadError] = useState("");

  const [selected, setSelected] = useState<Facility | null>(null);
  const [booked, setBooked] = useState<Appointment | null>(null);
  // Tomorrow: a default of "today 10:30" is often already past.
  const [bookingDate, setBookingDate] = useState(() => todayLocal(1));
  const [bookingTime, setBookingTime] = useState("10:30");
  const [timeWindow, setTimeWindow] = useState("exact");
  const [bookingDepartment, setBookingDepartment] = useState("");
  const [bookingNote, setBookingNote] = useState("");
  const [formError, setFormError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Partner hospitals: in person or video, and what it costs.
  const [visitMode, setVisitMode] = useState<"in_person" | "telehealth">("in_person");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [needsMoney, setNeedsMoney] = useState(false);
  const [paid, setPaid] = useState<{ total: number } | null>(null);
  // A new search is on its way: the current results are dimmed meanwhile.
  const [isFetching, setIsFetching] = useState(true);

  // Load (and re-load on filter changes, debounced for typing).
  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- marks the refetch below
    setIsFetching(true);
    const timer = setTimeout(() => {
      api<FacilityList>("users/me/care/facilities", {
        query: {
          q: searchQuery.trim() || undefined,
          department: department || undefined,
          sort,
          // Coordinates only for a distance sort, never with other requests.
          latitude: sort === "distance" ? coords?.latitude : undefined,
          longitude: sort === "distance" ? coords?.longitude : undefined,
        },
      })
        .then((list) => {
          if (cancelled) return;
          setDirectory(list);
          setLoadError("");
        })
        .catch((error) => {
          if (cancelled) return;
          // Results for an earlier search would now be misleading.
          setDirectory(null);
          setLoadError(error instanceof ApiError ? error.message : t("booking.error.load"));
        })
        .finally(() => {
          if (!cancelled) setIsFetching(false);
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is stable per language
  }, [searchQuery, department, sort, coords]);

  const chooseSort = (value: string) => {
    if (value !== "distance") {
      setSort("name");
      return;
    }
    if (coords) {
      setSort("distance");
      return;
    }
    if (!navigator.geolocation) {
      onToast(t("booking.toast.locationUnavailable"), t("booking.toast.locationUnavailableBody"));
      return;
    }
    // Location is used only after the patient allows it, and only for sorting.
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoords({ latitude: position.coords.latitude, longitude: position.coords.longitude });
        setSort("distance");
      },
      () => onToast(t("booking.toast.locationNotShared"), t("booking.toast.locationNotSharedBody")),
      { timeout: 10_000, maximumAge: 300_000 },
    );
  };

  const openBooking = (facility: Facility) => {
    setSelected(facility);
    setBooked(null);
    setPaid(null);
    setFormError("");
    setNeedsMoney(false);
    setVisitMode("in_person");
    setQuote(null);
    // A partner hospital takes the service key; other listings the label.
    const first = facility.departments[0];
    setBookingDepartment(first ? (facility.partner ? first : departmentLabel(first, t)) : "");
  };

  // What the visit costs at a partner hospital, for the mode chosen.
  useEffect(() => {
    if (!selected?.partner) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the old quote must not show for the new choice
    setQuote(null);
    setNeedsMoney(false);
    api<Quote>("users/me/hospital-bookings/quote", { query: { hospital_id: selected.id, visit_mode: visitMode } })
      .then((q) => {
        if (!cancelled) {
          setQuote(q);
          setNeedsMoney(!q.enough);
        }
      })
      .catch(() => {
        if (!cancelled) setQuote(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selected, visitMode]);

  const closeBooking = () => {
    setSelected(null);
    setBooked(null);
  };

  const submitBooking = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    const scheduledAt = localDateTimeToIso(bookingDate, bookingTime);
    if (!scheduledAt) {
      setFormError(t("booking.error.invalidDate"));
      return;
    }
    if (new Date(scheduledAt) <= new Date()) {
      setFormError(t("booking.error.futureTime"));
      return;
    }
    setIsSubmitting(true);
    setFormError("");
    try {
      const result = await api<{ appointment: Appointment }>("users/me/appointments", {
        method: "POST",
        body: {
          scheduled_at: scheduledAt,
          timezone: browserTimezone(),
          visit_mode: selected.partner ? visitMode : "in_person",
          facility_id: selected.id,
          department: bookingDepartment || null,
          time_window: timeWindow,
          notes: bookingNote.trim() || null,
        },
      });
      setBooked(result.appointment);
      setPaid(result.appointment.hospital_booking ? { total: result.appointment.hospital_booking.total } : null);
      setBookingNote("");
    } catch (error) {
      // 402: the balance does not cover the visit.
      if (error instanceof ApiError && error.status === 402) setNeedsMoney(true);
      setFormError(error instanceof ApiError ? error.message : t("booking.error.generic"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const facilities = useMemo(() => directory?.facilities ?? [], [directory]);
  const mapPoints: MapPoint[] = useMemo(
    () => facilities.map((f) => ({ id: f.id, latitude: f.latitude, longitude: f.longitude, label: f.name })),
    [facilities],
  );
  const here = useMemo(() => coords, [coords]);

  return (
    <>
      <div data-purpose="booking-view" className="flex-1 min-h-0 overflow-y-auto">
        {/* Breadcrumbs & Welcome Hero */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
          <div>
            <div className="flex items-center space-x-2 text-xs text-slate-400 mb-1">
              <span>{t("booking.breadcrumb")}</span>
              <span>/</span>
              <span className="text-emerald-700 font-medium">{t("booking.breadcrumbCurrent")}</span>
            </div>
            <h1 className="text-xl md:text-2xl font-extrabold text-slate-900 tracking-tight">{t("booking.title")}</h1>
            <p className="text-xs md:text-sm text-slate-500 mt-0.5">{t("booking.subtitle")}</p>
          </div>
          {directory && (
            <div className="flex items-center space-x-2 text-xs text-slate-600 bg-white border border-slate-200 px-3 py-1.5 rounded-xl shadow-xs self-start sm:self-auto">
              <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
              <span>
                {t("booking.directory")} ({t(directory.total === 1 ? "booking.directoryCountOne" : "booking.directoryCountOther", { total: directory.total })})
              </span>
            </div>
          )}
        </div>

        <section data-purpose="manual-booking-section" className="space-y-4 pb-6">
          {/* Search and Filters Bar */}
          <div className="bg-white p-4 rounded-2xl border border-slate-200 card-shadow flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div className="flex-1 relative">
              <svg className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                id="hospital-search"
                data-purpose="hospital-search"
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t("booking.searchPlaceholder")}
                className="w-full pl-9 pr-4 py-2 text-xs md:text-sm rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-slate-800 placeholder-slate-400"
              />
            </div>
            <div className="flex items-center space-x-2">
              <select
                aria-label={t("booking.department")}
                data-purpose="department-filter"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                className="text-xs border border-slate-200 rounded-xl px-3 py-2 bg-white text-slate-600 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">{t("booking.allSpecialties")}</option>
                {(directory?.departments ?? [...DEPARTMENT_KEYS]).map((d) => (
                  <option key={d} value={d}>{departmentLabel(d, t)}</option>
                ))}
              </select>
              <select
                aria-label={t("booking.sort")}
                data-purpose="sort-filter"
                value={sort}
                onChange={(e) => chooseSort(e.target.value)}
                className="text-xs border border-slate-200 rounded-xl px-3 py-2 bg-white text-slate-600 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="name">{t("booking.sortName")}</option>
                <option value="distance">{t("booking.sortDistance")}</option>
              </select>
            </div>
          </div>

          {/* Directory Subhead */}
          <div className="flex items-center justify-between px-1">
            <h3 className="text-sm font-bold text-slate-900 flex items-center space-x-2">
              <span>{t("booking.hospitalsCenters")}</span>
              {directory && <span className="text-xs font-normal text-slate-400">({t("booking.shown", { count: facilities.length })})</span>}
            </h3>
          </div>

          {loadError && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">{loadError}</p>
          )}
          {directory && facilities.length === 0 && !loadError && (
            <p data-purpose="hospital-empty" className="text-xs text-slate-500 px-1">{t("booking.noMatch")}</p>
          )}

          <div className="mb-4">
            <HospitalMap
              here={here}
              onSelect={(id) => {
                const facility = facilities.find((f) => f.id === id);
                if (facility) openBooking(facility);
              }}
              points={mapPoints}
            />
          </div>

          {/* Hospital Grid: placeholders on the first load; later searches dim the current results. */}
          <div
            aria-busy={isFetching}
            className={`grid grid-cols-1 lg:grid-cols-2 gap-4 transition-opacity ${directory && isFetching ? "opacity-60" : ""}`}
            data-purpose="hospital-grid"
            id="hospital-grid"
          >
            {!directory && !loadError && (
              <Skeleton className="contents" label={t("common.loading")}>
                {[0, 1, 2, 3].map((i) => <RowBones key={i} />)}
              </Skeleton>
            )}
            {facilities.map((facility) => (
              <div
                key={facility.id}
                data-purpose={`hospital-${facility.id}`}
                className="hospital-card bg-white rounded-2xl p-4 border border-slate-200 card-shadow hover:border-emerald-300 transition-all flex items-center justify-between gap-3"
              >
                <div className="flex items-center space-x-4 min-w-0">
                  <div className="w-10 h-10 rounded-xl bg-emerald-50 border border-emerald-100 text-emerald-700 flex items-center justify-center font-bold text-sm flex-shrink-0">
                    {initials(facility.name)}
                  </div>
                  <div className="min-w-0">
                    <h4 className="text-sm font-bold text-slate-900">{facility.name}</h4>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-0.5 mt-0.5 text-xs text-slate-500">
                      <span>{facility.city}</span>
                      {facility.distance_km !== null && <span>{facility.distance_km} km</span>}
                      {facility.open_hours && <span className="text-emerald-600 font-medium">{facility.open_hours}</span>}
                      {facility.emergency && <span className="text-rose-600 font-medium">{t("booking.emergencyCare")}</span>}
                      {!facility.verified && <span className="text-amber-600">{t("booking.unconfirmed")}</span>}
                    </div>
                    {facility.partner && (
                      <div className="flex flex-wrap items-center gap-1.5 mt-1.5" data-purpose="partner-details">
                        {facility.price_in_person != null && (
                          <span className="text-[11px] font-semibold text-slate-800">
                            {t("booking.price", { price: formatBirr(facility.price_in_person, locale) })}
                          </span>
                        )}
                        <span className="text-[10px] font-semibold rounded px-1.5 py-0.5 bg-slate-100 text-slate-600">
                          {facility.ownership === "private" ? t("booking.private") : t("booking.public")}
                        </span>
                        {facility.video_enabled && (
                          <span className="text-[10px] font-semibold rounded px-1.5 py-0.5 bg-sky-50 text-sky-700">{t("booking.videoAvailable")}</span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => openBooking(facility)}
                  className="inline-flex items-center space-x-1.5 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition shadow-sm flex-shrink-0"
                >
                  <span>{t("booking.bookNow")}</span>
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* ===== Booking Time & Submit Modal ===== */}
      {selected && !booked && (
        <div id="booking-modal" data-purpose="booking-modal" className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200 max-h-[95vh] overflow-y-auto">
            <div className="flex items-start justify-between pb-4 border-b border-slate-100">
              <div>
                <span className="text-[11px] font-semibold text-emerald-600 uppercase tracking-wider">{t("booking.modalBadge")}</span>
                <h3 className="text-lg font-bold text-slate-900 mt-0.5">{selected.name}</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  {[selected.address, selected.city].filter(Boolean).join(", ")}
                  {selected.phone ? ` • ${selected.phone}` : ""}
                </p>
              </div>
              <button type="button" aria-label={t("common.close")} onClick={closeBooking} className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <form onSubmit={submitBooking} className="space-y-4 mt-4">
              <div className="bg-slate-50 rounded-xl p-3 border border-slate-100 flex items-center justify-between text-xs">
                <div className="flex items-center space-x-2">
                  <div className="w-6 h-6 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center font-bold text-[10px]">P</div>
                  <span className="font-medium text-slate-700">{t("booking.patient", { id: patientId || "—" })}</span>
                </div>
              </div>

              {selected.partner && (
                <fieldset data-purpose="visit-mode">
                  <legend className="block text-xs font-semibold text-slate-700 mb-1">{t("booking.visitMode")}</legend>
                  <div className="grid grid-cols-2 gap-2">
                    {(["in_person", "telehealth"] as const).map((mode) => {
                      const disabled = mode === "telehealth" && !selected.video_enabled;
                      return (
                        <label
                          className={`flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold ${
                            visitMode === mode ? "border-emerald-600 bg-emerald-50 text-emerald-800" : "border-slate-200 text-slate-600"
                          } has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-emerald-500 ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                          key={mode}
                        >
                          <input
                            checked={visitMode === mode}
                            className="sr-only"
                            disabled={disabled}
                            name="visit-mode"
                            onChange={() => setVisitMode(mode)}
                            type="radio"
                            value={mode}
                          />
                          {mode === "in_person" ? t("booking.inPerson") : t("booking.video")}
                        </label>
                      );
                    })}
                  </div>
                  {visitMode === "telehealth" && (
                    <p className="text-[11px] text-slate-500 mt-1">{t("booking.videoNeedsApproval")}</p>
                  )}
                </fieldset>
              )}

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="booking-date">{t("booking.selectDate")}</label>
                <input type="date" id="booking-date" required min={todayLocal()} value={bookingDate} onChange={(e) => setBookingDate(e.target.value)} className="w-full text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="booking-time">{t("booking.visitTime")}</label>
                <div className="grid grid-cols-2 gap-2 mb-2">
                  <input type="time" id="booking-time" required value={bookingTime} onChange={(e) => setBookingTime(e.target.value)} className="w-full text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
                  <select aria-label={t("booking.arrivalWindow")} data-purpose="time-window" value={timeWindow} onChange={(e) => setTimeWindow(e.target.value)} className="text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500">
                    {TIME_WINDOWS.map((w) => (
                      <option key={w.value} value={w.value}>{t(w.labelKey)}</option>
                    ))}
                  </select>
                </div>
                <p className="text-[11px] text-slate-400">{t("booking.arrivalWindowHint")}</p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="booking-department">{t("booking.departmentClinic")}</label>
                <select id="booking-department" value={bookingDepartment} onChange={(e) => setBookingDepartment(e.target.value)} className="w-full text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500">
                  {selected.departments.map((d) => (
                    <option key={d} value={selected.partner ? d : departmentLabel(d, t)}>{departmentLabel(d, t)}</option>
                  ))}
                  <option value="">{t("booking.notSure")}</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="booking-note">{t("booking.reasonLabel")}</label>
                <textarea id="booking-note" rows={2} maxLength={1000} value={bookingNote} onChange={(e) => setBookingNote(e.target.value)} placeholder={t("booking.reasonPlaceholder")} className="w-full text-xs rounded-xl border border-slate-200 px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>

              {selected.partner && quote && (
                <dl className="rounded-xl bg-slate-50 border border-slate-100 p-3 text-xs space-y-1" data-purpose="booking-quote">
                  <div className="flex justify-between"><dt className="text-slate-500">{t("booking.quote.price")}</dt><dd className="font-semibold">{formatBirr(quote.price, locale)}</dd></div>
                  <div className="flex justify-between"><dt className="text-slate-500">{t("booking.quote.fee")}</dt><dd className="font-semibold">{formatBirr(quote.service_fee, locale)}</dd></div>
                  <div className="flex justify-between border-t border-slate-200 pt-1"><dt className="font-bold text-slate-800">{t("booking.quote.total")}</dt><dd className="font-bold" data-purpose="quote-total">{formatBirr(quote.total, locale)}</dd></div>
                  <div className="flex justify-between"><dt className="text-slate-500">{t("booking.quote.balance")}</dt><dd className={quote.enough ? "text-emerald-700 font-semibold" : "text-red-600 font-semibold"}>{formatBirr(quote.balance, locale)}</dd></div>
                </dl>
              )}

              {needsMoney && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 flex items-center justify-between gap-3" data-purpose="needs-money">
                  <p className="text-xs text-amber-900">{t("booking.needsMoney")}</p>
                  {onOpenWallet && (
                    <button className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-xs font-semibold whitespace-nowrap" onClick={onOpenWallet} type="button">
                      {t("booking.addMoney")}
                    </button>
                  )}
                </div>
              )}

              {formError && (
                <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" data-purpose="booking-error" role="alert">{formError}</p>
              )}

              <div className="pt-3 border-t border-slate-100 flex items-center justify-end space-x-3">
                <button type="button" onClick={closeBooking} className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-50 transition">
                  {t("common.cancel")}
                </button>
                <button type="submit" disabled={isSubmitting} className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white text-xs font-semibold transition shadow-sm flex items-center space-x-1.5">
                  <span>{isSubmitting ? t("booking.submitting") : t("booking.submit")}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ===== Success Confirmation Modal ===== */}
      {selected && booked && (
        <div id="success-modal" data-purpose="success-modal" className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-slate-200 text-center">
            <div className="w-14 h-14 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h3 className="text-lg font-bold text-slate-900">{t("booking.visitBooked")}</h3>
            <p className="text-xs text-slate-500 mt-1">
              {t("booking.savedPrefix", { facility: selected.name })}
              {selected.phone
                ? t("booking.savedCallSuffix", { phone: selected.phone })
                : t("booking.savedContactSuffix")}
            </p>

            <div className="bg-slate-50 rounded-xl p-4 my-4 text-left border border-slate-100 space-y-2 text-xs">
              <div className="flex justify-between gap-3">
                <span className="text-slate-400">{t("booking.hospitalLabel")}</span>
                <span className="font-bold text-slate-800 text-right">{selected.name}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-slate-400">{t("booking.visitTimeLabel")}</span>
                <span className="font-bold text-emerald-600 text-right">{formatWhen(booked.scheduled_at, locale)}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-slate-400">{t("booking.reference")}</span>
                <span className="font-mono font-bold text-slate-800">{booked.appointment_id.slice(0, 8).toUpperCase()}</span>
              </div>
              {paid && (
                <div className="flex justify-between gap-3" data-purpose="booked-paid">
                  <span className="text-slate-400">{t("booking.paid")}</span>
                  <span className="font-bold text-slate-800">{formatBirr(paid.total, locale)}</span>
                </div>
              )}
            </div>
            {booked.hospital_booking?.state === "awaiting_doctor" && (
              <p className="text-xs text-sky-800 bg-sky-50 border border-sky-100 rounded-lg px-3 py-2 mb-4" data-purpose="booked-awaiting-doctor">
                {t("booking.awaitingDoctor")}
              </p>
            )}

            <button type="button" onClick={closeBooking} className="w-full py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition">
              {t("common.done")}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
