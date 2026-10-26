// Shapes of the backend data the /interview screens use (see docs/api.md),
// and small display helpers shared between them.
//
// Anything the patient reads is produced through the translator, so these
// helpers take `t` (and, for dates, the active locale) as arguments rather
// than baking in English.

import type { Translate, TranslationKey } from "../lib/i18n";

export type Facility = {
  id: string;
  name: string;
  kind: string;
  address: string;
  city: string;
  country: string;
  departments: string[];
  phone: string | null;
  emergency: boolean;
  open_hours: string | null;
  website: string | null;
  verified: boolean;
  distance_km: number | null;
  latitude: number;
  longitude: number;
  /** An Endod partner hospital: booked and paid through Endod. */
  partner?: boolean;
  /** "public" or "private" (partners). */
  ownership?: string | null;
  ambulance_phone?: string | null;
  video_enabled?: boolean;
  /** Santim (partners). */
  price_in_person?: number | null;
  price_video?: number | null;
};

export type FacilityList = {
  facilities: Facility[];
  total: number;
  location_used: boolean;
  departments: string[];
};

export type AppointmentStatus = "SCHEDULED" | "CONFIRMED" | "RESCHEDULED" | "CANCELLED" | "COMPLETED" | "MISSED";

export type Appointment = {
  appointment_id: string;
  appointment_type: string;
  scheduled_at: string;
  duration_minutes: number;
  status: AppointmentStatus;
  location: string | null;
  meeting_url: string | null;
  visit_mode: "in_person" | "telehealth";
  department: string | null;
  time_window: "exact" | "morning" | "afternoon" | "evening";
  facility: { id: string; name: string | null; address?: string; city?: string; phone?: string | null } | null;
  provider_name: string | null;
  notes: string | null;
  timezone: string;
  /** Booked and paid at an Endod partner hospital; null for the patient's own entries. */
  hospital_booking?: HospitalBooking | null;
};

export type HospitalBookingState =
  | "awaiting_payment" | "payment_expired"
  | "awaiting_hospital" | "awaiting_doctor" | "confirmed" | "rejected" | "cancelled" | "completed";

/** Where the patient's payment (through Chapa) for a booking is. */
export type PaymentStatus = "awaiting_payment" | "paid" | "expired" | "refund_pending" | "refunded";

export type HospitalBooking = {
  hospital_id: string;
  state: HospitalBookingState;
  /** Santim. */
  price: number;
  service_fee: number;
  total: number;
  reason: string | null;
  video_ready: boolean;
  payment: {
    status: PaymentStatus;
    /** While awaiting payment: when the hold on the time ends. */
    due_at: string | null;
    /** While awaiting payment: Chapa's checkout page ("Pay now"). */
    checkout_url: string | null;
  };
};

/** GET /users/me/hospital-bookings/quote (santim). */
export type Quote = {
  hospital_id: string;
  visit_mode: "in_person" | "telehealth";
  price: number;
  service_fee: number;
  total: number;
};

/** POST /users/me/appointments for a partner hospital: the hold and its checkout. */
export type BookingPayment = {
  price: number;
  service_fee: number;
  total: number;
  status: PaymentStatus;
  checkout_url: string | null;
  tx_ref: string | null;
  expires_at: string | null;
};

/** GET /users/me/booking-payments/{tx_ref}: the payment, checked with Chapa. */
export type BookingPaymentCheck = {
  tx_ref: string;
  status: "pending" | "paid" | "expired" | "mismatch";
  appointment: Appointment;
};

/** GET /users/me/payments/status: whether online payment is on, and where paying may happen. */
export type PaymentsStatus = { online_payments: boolean; checkout_origins: string[] };

/** Chapa's hosted checkout: the only place a patient is sent to pay by default. */
export const CHAPA_CHECKOUT_ORIGIN = "https://checkout.chapa.co";

/**
 * A checkout address the app may send the patient to: only Chapa's checkout
 * (https://checkout.chapa.co), or an origin the backend names for its
 * configured Chapa server (the browser tests' stand-in). Anything else,
 * javascript: included, is refused.
 */
export function safeCheckoutUrl(url: string | null | undefined, origins: string[] = [CHAPA_CHECKOUT_ORIGIN]): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
    if (parsed.username || parsed.password) return null;
    const allowed = new Set([CHAPA_CHECKOUT_ORIGIN, ...origins]);
    return allowed.has(parsed.origin) ? parsed.toString() : null;
  } catch {
    return null;
  }
}

/** Santim as birr for display, e.g. 15050 -> "150.50 ብር" / "ETB 150.50". */
export function formatBirr(santim: number, locale: string): string {
  const birr = santim / 100;
  const number = birr.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return locale.startsWith("am") ? `${number} ብር` : `ETB ${number}`;
}

/** The arrival-window choices, with the key their label comes from. */
export const TIME_WINDOWS: { value: "exact" | "morning" | "afternoon" | "evening"; labelKey: TranslationKey }[] = [
  { value: "exact", labelKey: "booking.timeWindow.exact" },
  { value: "morning", labelKey: "booking.timeWindow.morning" },
  { value: "afternoon", labelKey: "booking.timeWindow.afternoon" },
  { value: "evening", labelKey: "booking.timeWindow.evening" },
];

/** The department keys the backend uses, in the order they are shown. */
export const DEPARTMENT_KEYS = [
  "general_medicine",
  "emergency",
  "maternal_health",
  "pediatrics",
  "cardiology",
  "respiratory",
] as const;

/** A department's display name. An unknown key is shown as the backend sent it. */
export function departmentLabel(department: string, t: Translate): string {
  const key = `department.${department}` as TranslationKey;
  const label = t(key);
  return label === key ? department : label;
}

export const ACTIVE_STATUSES: AppointmentStatus[] = ["SCHEDULED", "CONFIRMED", "RESCHEDULED"];

/** The browser's IANA timezone, sent with bookings so arrival windows are checked locally. */
export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** A date (YYYY-MM-DD) and time (HH:MM) in the browser's timezone, as an ISO instant. */
export function localDateTimeToIso(date: string, time: string): string | null {
  const value = new Date(`${date}T${time}`);
  return Number.isNaN(value.getTime()) ? null : value.toISOString();
}

/**
 * A date and time in the browser's timezone: the same zone the booking and
 * reschedule forms use, so what is shown is what gets edited.
 */
export function formatWhen(iso: string, locale: string): string {
  return new Date(iso).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

export function initials(text: string): string {
  const letters = text
    .replace(/^dr\.?\s+/i, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "");
  return letters.join("") || "?";
}

/** Who or where the appointment is with, for the card title. */
export function appointmentTitle(appointment: Appointment, t: Translate): string {
  return (
    appointment.provider_name ||
    appointment.facility?.name ||
    (appointment.department ? departmentLabel(appointment.department, t) : "") ||
    t("appointments.genericTitle", {
      type: appointment.appointment_type.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()),
    })
  );
}

export function appointmentPlace(appointment: Appointment, t: Translate): string {
  if (appointment.visit_mode === "telehealth") {
    // A video visit with a partner hospital still says which hospital.
    const video = t("appointments.visitMode.video");
    return appointment.facility?.name ? `${video} · ${appointment.facility.name}` : video;
  }
  return appointment.facility?.name && appointment.provider_name
    ? appointment.facility.name
    : appointment.location || t("appointments.visitMode.placeNotSet");
}
