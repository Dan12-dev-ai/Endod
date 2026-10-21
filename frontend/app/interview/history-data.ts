// Shapes of the patient history API (backend: dedan_platform/api_history.py)
// and the filters the History page applies to them.

import type { TranslationKey } from "../lib/i18n";

export type FileState = "ready" | "arriving" | "unavailable";

export type RecordFile = {
  file_id: string;
  filename: string;
  content_type: string;
  size: number;
  state: FileState;
};

export type HospitalCategory = "diagnosis" | "prescription" | "lab_result" | "imaging" | "visit_note" | "document";

export type HistoryItem = {
  id: string;
  /** "hospital": sent by a partner hospital (verified); "self": a visit the patient added. */
  kind: "hospital" | "self";
  category: HospitalCategory | "visit";
  title: string;
  hospital_id: string | null;
  hospital_name: string | null;
  occurred_at: string;
  recorded_by: string | null;
  verified: boolean;
  source: string | null;
  visit_id: string | null;
  details: Record<string, unknown>;
  files: RecordFile[];
};

export type HistoryResponse = {
  items: HistoryItem[];
  summary: { total: number; verified: number; self_reported: number; hospitals: number; by_category: Record<string, number> };
};

export type FollowUp = {
  follow_up_id: string;
  hospital_id: string;
  hospital_name: string;
  visit_id: string;
  /** YYYY-MM-DD */
  follow_up_on: string;
  note: string | null;
  doctor_name: string | null;
};

export type QueueEntry = {
  entry_id: string;
  hospital_id: string;
  hospital_name: string;
  doctor_name: string | null;
  day: string;
  ticket: number;
  status: "waiting" | "called" | "done" | "skipped" | "cancelled";
  ahead: number;
  position: number;
  updated_at: string;
};

export type Share = {
  share_id: string;
  hospital_id: string;
  hospital_name: string;
  created_at: string;
  expires_at: string | null;
  status: "active" | "revoked" | "expired";
  record_count: number;
  records: { record_id: string; kind: "hospital" | "self"; title: string }[];
};

export type ShareHospital = { hospital_id: string; name: string; name_am: string | null; city: string | null };

/** What "Book now" hands the booking screen: the hospital and the follow-up day. */
export type BookingPreset = { hospitalId: string; date: string };

export const TABS: { id: string; labelKey: TranslationKey; matches: (item: HistoryItem) => boolean }[] = [
  { id: "all", labelKey: "history.tab.all", matches: () => true },
  { id: "visits", labelKey: "history.tab.visits", matches: (i) => i.category === "visit_note" || i.category === "visit" },
  { id: "diagnoses", labelKey: "history.tab.diagnoses", matches: (i) => i.category === "diagnosis" },
  { id: "prescriptions", labelKey: "history.tab.prescriptions", matches: (i) => i.category === "prescription" },
  { id: "labs", labelKey: "history.tab.labs", matches: (i) => i.category === "lab_result" },
  { id: "imaging", labelKey: "history.tab.imaging", matches: (i) => i.category === "imaging" },
  { id: "documents", labelKey: "history.tab.documents", matches: (i) => i.category === "document" },
  { id: "self", labelKey: "history.tab.self", matches: (i) => i.kind === "self" },
];

export const CATEGORY_LABEL: Record<HistoryItem["category"], TranslationKey> = {
  diagnosis: "history.category.diagnosis",
  prescription: "history.category.prescription",
  lab_result: "history.category.lab_result",
  imaging: "history.category.imaging",
  visit_note: "history.category.visit_note",
  document: "history.category.document",
  visit: "history.category.visit",
};

/** A local calendar day (YYYY-MM-DD) for an instant, in the browser's timezone. */
export function localDay(iso: string): string {
  const at = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
}

/** The items on a tab that match the search text and the date range (inclusive). */
export function filterItems(items: HistoryItem[], tab: string, query: string, from: string, to: string): HistoryItem[] {
  const matchesTab = TABS.find((t) => t.id === tab)?.matches ?? (() => true);
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return items.filter((item) => {
    if (!matchesTab(item)) return false;
    const day = localDay(item.occurred_at);
    if (from && day < from) return false;
    if (to && day > to) return false;
    if (!words.length) return true;
    const haystack = [item.title, item.hospital_name, item.recorded_by, JSON.stringify(item.details), ...item.files.map((f) => f.filename)]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}

/** Where the app's own route serves a record's file (never the backend directly). */
export function fileUrl(recordId: string, fileId: string, download = false): string {
  return `/api/records/files/${recordId}/${fileId}${download ? "?download=1" : ""}`;
}

/** Text from a details field, or null. */
export function text(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

/** A details field that is a list of objects. */
export function rows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((v): v is Record<string, unknown> => Boolean(v) && typeof v === "object") : [];
}

export function formatSize(bytes: number, locale: string): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toLocaleString(locale, { maximumFractionDigits: 0 })} KB`;
  return `${(kb / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} MB`;
}

/** A calendar day (YYYY-MM-DD) for display, without a timezone shift. */
export function formatDay(day: string, locale: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1).toLocaleDateString(locale, { dateStyle: "medium" });
}
