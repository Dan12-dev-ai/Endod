"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import {
  type Appointment,
  browserTimezone,
  DEPARTMENT_LABELS,
  type Facility,
  type FacilityList,
  formatWhen,
  initials,
  localDateTimeToIso,
  TIME_WINDOWS,
} from "./data";

type Props = {
  patientId: string;
  onToast: (title: string, message: string) => void;
};

type Coords = { latitude: number; longitude: number };

function todayLocal(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Hospital directory and in-person booking (GET /users/me/care/facilities, POST /users/me/appointments). */
export default function BookingView({ patientId, onToast }: Props) {
  const [searchQuery, setSearchQuery] = useState("");
  const [department, setDepartment] = useState("");
  const [sort, setSort] = useState<"name" | "distance">("name");
  const [coords, setCoords] = useState<Coords | null>(null);
  const [directory, setDirectory] = useState<FacilityList | null>(null);
  const [loadError, setLoadError] = useState("");

  const [selected, setSelected] = useState<Facility | null>(null);
  const [booked, setBooked] = useState<Appointment | null>(null);
  const [bookingDate, setBookingDate] = useState(todayLocal);
  const [bookingTime, setBookingTime] = useState("10:30");
  const [timeWindow, setTimeWindow] = useState("exact");
  const [bookingDepartment, setBookingDepartment] = useState("");
  const [bookingNote, setBookingNote] = useState("");
  const [formError, setFormError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Load (and re-load on filter changes, debounced for typing).
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      api<FacilityList>("users/me/care/facilities", {
        query: {
          q: searchQuery.trim() || undefined,
          department: department || undefined,
          sort,
          latitude: coords?.latitude,
          longitude: coords?.longitude,
        },
      })
        .then((list) => {
          if (cancelled) return;
          setDirectory(list);
          setLoadError("");
        })
        .catch((error) => {
          if (!cancelled) setLoadError(error instanceof ApiError ? error.message : "Unable to load hospitals.");
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
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
      onToast("Location unavailable", "This browser cannot share your location.");
      return;
    }
    // Location is used only after the patient allows it, and only for sorting.
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoords({ latitude: position.coords.latitude, longitude: position.coords.longitude });
        setSort("distance");
      },
      () => onToast("Location not shared", "Allow location access to sort hospitals by distance."),
      { timeout: 10_000, maximumAge: 300_000 },
    );
  };

  const openBooking = (facility: Facility) => {
    setSelected(facility);
    setBooked(null);
    setFormError("");
    setBookingDepartment(facility.departments[0] ? DEPARTMENT_LABELS[facility.departments[0]] ?? "" : "");
  };

  const closeBooking = () => {
    setSelected(null);
    setBooked(null);
  };

  const submitBooking = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    const scheduledAt = localDateTimeToIso(bookingDate, bookingTime);
    if (!scheduledAt) {
      setFormError("Please choose a valid date and time.");
      return;
    }
    if (new Date(scheduledAt) <= new Date()) {
      setFormError("Please choose a time in the future.");
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
          visit_mode: "in_person",
          facility_id: selected.id,
          department: bookingDepartment || null,
          time_window: timeWindow,
          notes: bookingNote.trim() || null,
        },
      });
      setBooked(result.appointment);
      setBookingNote("");
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : "Unable to book right now. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const facilities = directory?.facilities ?? [];

  return (
    <>
      <div data-purpose="booking-view" className="flex-1 min-h-0 overflow-y-auto">
        {/* Breadcrumbs & Welcome Hero */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
          <div>
            <div className="flex items-center space-x-2 text-xs text-slate-400 mb-1">
              <span>ENDOD Care</span>
              <span>/</span>
              <span className="text-emerald-700 font-medium">Hospital Booking</span>
            </div>
            <h1 className="text-xl md:text-2xl font-extrabold text-slate-900 tracking-tight">Hospital &amp; Clinic Reservation</h1>
            <p className="text-xs md:text-sm text-slate-500 mt-0.5">Find a facility and book your visit.</p>
          </div>
          {directory && (
            <div className="flex items-center space-x-2 text-xs text-slate-600 bg-white border border-slate-200 px-3 py-1.5 rounded-xl shadow-xs self-start sm:self-auto">
              <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
              <span>Care directory ({directory.total} {directory.total === 1 ? "facility" : "facilities"})</span>
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
                placeholder="Search hospitals by name or location..."
                className="w-full pl-9 pr-4 py-2 text-xs md:text-sm rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-slate-800 placeholder-slate-400"
              />
            </div>
            <div className="flex items-center space-x-2">
              <select
                aria-label="Department"
                data-purpose="department-filter"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                className="text-xs border border-slate-200 rounded-xl px-3 py-2 bg-white text-slate-600 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">All Specialties</option>
                {(directory?.departments ?? Object.keys(DEPARTMENT_LABELS)).map((d) => (
                  <option key={d} value={d}>{DEPARTMENT_LABELS[d] ?? d}</option>
                ))}
              </select>
              <select
                aria-label="Sort"
                data-purpose="sort-filter"
                value={sort}
                onChange={(e) => chooseSort(e.target.value)}
                className="text-xs border border-slate-200 rounded-xl px-3 py-2 bg-white text-slate-600 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="name">Name (A–Z)</option>
                <option value="distance">Distance: Nearest</option>
              </select>
            </div>
          </div>

          {/* Directory Subhead */}
          <div className="flex items-center justify-between px-1">
            <h3 className="text-sm font-bold text-slate-900 flex items-center space-x-2">
              <span>Hospitals &amp; Centers</span>
              <span className="text-xs font-normal text-slate-400">({facilities.length} shown)</span>
            </h3>
          </div>

          {loadError && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">{loadError}</p>
          )}
          {directory && facilities.length === 0 && !loadError && (
            <p data-purpose="hospital-empty" className="text-xs text-slate-500 px-1">No facilities match your search.</p>
          )}

          {/* Hospital Grid */}
          <div id="hospital-grid" data-purpose="hospital-grid" className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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
                      {facility.emergency && <span className="text-rose-600 font-medium">Emergency care</span>}
                      {!facility.verified && <span className="text-amber-600">Details unconfirmed</span>}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => openBooking(facility)}
                  className="inline-flex items-center space-x-1.5 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition shadow-sm flex-shrink-0"
                >
                  <span>Book Now</span>
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
                <span className="text-[11px] font-semibold text-emerald-600 uppercase tracking-wider">Hospital Booking</span>
                <h3 className="text-lg font-bold text-slate-900 mt-0.5">{selected.name}</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  {[selected.address, selected.city].filter(Boolean).join(", ")}
                  {selected.phone ? ` • ${selected.phone}` : ""}
                </p>
              </div>
              <button type="button" aria-label="Close" onClick={closeBooking} className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <form onSubmit={submitBooking} className="space-y-4 mt-4">
              <div className="bg-slate-50 rounded-xl p-3 border border-slate-100 flex items-center justify-between text-xs">
                <div className="flex items-center space-x-2">
                  <div className="w-6 h-6 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center font-bold text-[10px]">P</div>
                  <span className="font-medium text-slate-700">Patient: {patientId || "—"}</span>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="booking-date">Select Visit Date</label>
                <input type="date" id="booking-date" required min={todayLocal()} value={bookingDate} onChange={(e) => setBookingDate(e.target.value)} className="w-full text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="booking-time">Visit Time *</label>
                <div className="grid grid-cols-2 gap-2 mb-2">
                  <input type="time" id="booking-time" required value={bookingTime} onChange={(e) => setBookingTime(e.target.value)} className="w-full text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
                  <select aria-label="Arrival window" data-purpose="time-window" value={timeWindow} onChange={(e) => setTimeWindow(e.target.value)} className="text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500">
                    {TIME_WINDOWS.map((w) => (
                      <option key={w.value} value={w.value}>{w.label}</option>
                    ))}
                  </select>
                </div>
                <p className="text-[11px] text-slate-400">With an arrival window, the visit time must fall inside it.</p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="booking-department">Department / Clinic</label>
                <select id="booking-department" value={bookingDepartment} onChange={(e) => setBookingDepartment(e.target.value)} className="w-full text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500">
                  {selected.departments.map((d) => (
                    <option key={d} value={DEPARTMENT_LABELS[d] ?? d}>{DEPARTMENT_LABELS[d] ?? d}</option>
                  ))}
                  <option value="">Not sure</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="booking-note">Reason for Visit / Note (Optional)</label>
                <textarea id="booking-note" rows={2} maxLength={1000} value={bookingNote} onChange={(e) => setBookingNote(e.target.value)} placeholder="e.g. Follow-up for chest pain" className="w-full text-xs rounded-xl border border-slate-200 px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>

              {formError && (
                <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" data-purpose="booking-error" role="alert">{formError}</p>
              )}

              <div className="pt-3 border-t border-slate-100 flex items-center justify-end space-x-3">
                <button type="button" onClick={closeBooking} className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-50 transition">
                  Cancel
                </button>
                <button type="submit" disabled={isSubmitting} className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white text-xs font-semibold transition shadow-sm flex items-center space-x-1.5">
                  <span>{isSubmitting ? "Booking..." : "Submit Booking"}</span>
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
            <h3 className="text-lg font-bold text-slate-900">Visit Booked</h3>
            <p className="text-xs text-slate-500 mt-1">
              Saved to your appointments, with reminders. {selected.name} does not receive bookings from Endod yet
              {selected.phone ? `, so please call ${selected.phone} to confirm.` : ", so please contact them to confirm."}
            </p>

            <div className="bg-slate-50 rounded-xl p-4 my-4 text-left border border-slate-100 space-y-2 text-xs">
              <div className="flex justify-between gap-3">
                <span className="text-slate-400">Hospital:</span>
                <span className="font-bold text-slate-800 text-right">{selected.name}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-slate-400">Visit Time:</span>
                <span className="font-bold text-emerald-600 text-right">{formatWhen(booked.scheduled_at, booked.timezone)}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-slate-400">Booking Reference:</span>
                <span className="font-mono font-bold text-slate-800">{booked.appointment_id.slice(0, 8).toUpperCase()}</span>
              </div>
            </div>

            <button type="button" onClick={closeBooking} className="w-full py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition">
              Done
            </button>
          </div>
        </div>
      )}
    </>
  );
}
