// Shapes of the backend data the /interview screens use (see docs/api.md),
// and small display helpers shared between them.

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
};

export const TIME_WINDOWS = [
  { value: "exact", label: "Exact Arrival Time" },
  { value: "morning", label: "Morning (08:00 - 12:00)" },
  { value: "afternoon", label: "Afternoon (12:00 - 17:00)" },
  { value: "evening", label: "Evening (17:00 - 21:00)" },
] as const;

export const DEPARTMENT_LABELS: Record<string, string> = {
  general_medicine: "General Medicine",
  emergency: "Emergency & Trauma",
  maternal_health: "Maternal Health",
  pediatrics: "Pediatrics",
  cardiology: "Cardiology",
  respiratory: "Respiratory",
};

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

export function formatWhen(iso: string, timezone?: string): string {
  const date = new Date(iso);
  const options: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" };
  try {
    return date.toLocaleString(undefined, { ...options, timeZone: timezone || undefined });
  } catch {
    return date.toLocaleString(undefined, options);
  }
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
export function appointmentTitle(appointment: Appointment): string {
  return (
    appointment.provider_name ||
    appointment.facility?.name ||
    appointment.department ||
    `${appointment.appointment_type.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())} appointment`
  );
}

export function appointmentPlace(appointment: Appointment): string {
  if (appointment.visit_mode === "telehealth") return "Video visit";
  return appointment.facility?.name && appointment.provider_name
    ? appointment.facility.name
    : appointment.location || "Place not set";
}
