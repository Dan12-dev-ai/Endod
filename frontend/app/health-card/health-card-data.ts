/**
 * Shared Digital Health Card data helpers.
 *
 * Single source of truth for what the card shows: identity (name, ID, phone,
 * dates, the signed QR code) from GET /users/me and /users/me/card, and the
 * emergency details (blood group, allergies, emergency contact) from
 * GET /users/me/health-profile, which exists only with the patient's consent.
 * Used by the /health-card page and the card on the dashboard's Overview.
 */

import { api, ApiError } from "../lib/api";
import { generateQrMatrix, qrMatrixToSvg } from "./qr";

export type HealthCardInfo = {
  firstName: string;
  middleName: string;
  lastName: string;
  fullName: string;
  userId: string;
  phone: string;
  issuedDate: string;
  expiryDate: string;
  qrData: string;
  qrSvg: string;
  /** Null without consent to store health details (nothing to show). */
  medical: CardMedical | null;
  /** The health details exist but could not be loaded (not the same as none). */
  medicalUnavailable: boolean;
};

/** What a hospital needs at a glance in an emergency. */
export type CardMedical = {
  bloodType: string | null;
  allergies: string[];
  emergencyName: string | null;
  emergencyPhone: string | null;
};

/** The parts of GET /users/me/health-profile the card uses. */
export type HealthDetails = {
  blood_type?: string | null;
  allergies?: string[] | null;
  emergency_contact_name?: string | null;
  emergency_contact_phone?: string | null;
};

/** The blood groups the backend accepts. */
export const BLOOD_TYPES = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"];

/** The parts of GET /users/me the card uses. */
export type ProfileForCard = {
  dedan_user_id: string;
  consent?: { treatment_processing?: boolean } | null;
  first_name?: string | null;
  middle_name?: string | null;
  last_name?: string | null;
  display_name?: string | null;
  phone?: string | null;
  created_at?: string | null;
};

export function formatPhoneDisplay(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  if (digits.startsWith("251")) {
    return `+251 ${digits.slice(3, 6)} ${digits.slice(6)}`;
  }
  if (digits.startsWith("09")) {
    return `+251 ${digits.slice(2, 5)} ${digits.slice(5)}`;
  }
  return phone || "+251 9XX XXX XXX";
}

export function formatPhoneE164(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  if (digits.startsWith("251")) return digits;
  if (digits.startsWith("09")) return "251" + digits.slice(1);
  if (digits.startsWith("9") && digits.length === 9) return "251" + digits;
  return digits;
}

export function getFullName(first: string, middle: string, last: string): string {
  const parts = [first, middle, last].filter((p) => p.length > 0);
  return parts.join(" ") || "New User";
}

export function getExpiryDate(createdAt: string): string {
  if (!createdAt) return "—";
  const date = new Date(createdAt);
  date.setFullYear(date.getFullYear() + 1);
  return date.toLocaleDateString("en-ET", { year: "numeric", month: "short", day: "numeric" });
}

export function getIssuedDate(createdAt: string): string {
  if (!createdAt) return "Pending";
  return new Date(createdAt).toLocaleDateString("en-ET", { year: "numeric", month: "short", day: "numeric" });
}

/** GET /users/me/card: the DEDAN ID and the server's signature over it. */
export type CardSignature = { dedan_user_id: string; signature: string };

/**
 * The link in the QR code. Scanning it opens /card/<ID>, which asks the
 * backend whether the signature is genuine; a card with an altered or
 * made-up ID does not verify. The link holds no health data.
 */
export function cardVerifyUrl(origin: string, card: CardSignature): string {
  return `${origin}/card/${encodeURIComponent(card.dedan_user_id)}?s=${encodeURIComponent(card.signature)}`;
}

/**
 * Card data from a profile. The patient ID is the DEDAN ID. The QR code is
 * drawn only with a signed verification link (`qrLink`); without one (e.g.
 * the name-only uses on the dashboard) it is left empty.
 */
export function healthCardFromProfile(
  profile: ProfileForCard,
  qrLink = "",
  health: HealthDetails | null = null,
  medicalUnavailable = false,
): HealthCardInfo {
  const firstName = profile.first_name ?? "";
  const middleName = profile.middle_name ?? "";
  const lastName = profile.last_name ?? "";
  const fullName = getFullName(firstName, middleName, lastName) === "New User" && profile.display_name
    ? profile.display_name
    : getFullName(firstName, middleName, lastName);
  const createdAt = profile.created_at ?? "";
  const userId = profile.dedan_user_id;
  const qrData = qrLink;

  return {
    firstName,
    middleName,
    lastName,
    fullName,
    userId,
    phone: profile.phone ? formatPhoneDisplay(profile.phone) : "—",
    issuedDate: getIssuedDate(createdAt),
    expiryDate: getExpiryDate(createdAt),
    qrData,
    qrSvg: qrData ? qrMatrixToSvg(generateQrMatrix(qrData), 152) : "",
    medical: health ? {
      bloodType: health.blood_type || null,
      allergies: (health.allergies ?? []).filter(Boolean),
      emergencyName: health.emergency_contact_name || null,
      emergencyPhone: health.emergency_contact_phone ? formatPhoneDisplay(health.emergency_contact_phone) : null,
    } : null,
    medicalUnavailable,
  };
}

/**
 * The full card, with its signed QR code (redirects to login when signed out).
 * If only the signature cannot be fetched, the card still shows, without a QR
 * code, rather than not at all. The health details are absent (403) without
 * consent; the card then shows identity only.
 */
export function loadHealthCard(): Promise<HealthCardInfo> {
  // One load per page visit, shared by the Overview (which remounts on every
  // tab switch) and anything else; edits in Settings call invalidateHealthCard().
  cached ??= fetchHealthCard().catch((error) => {
    cached = null;
    throw error;
  });
  return cached;
}

/** Call after changing anything the card shows, so the next view loads afresh. */
export function invalidateHealthCard(): void {
  cached = null;
}

let cached: Promise<HealthCardInfo> | null = null;

async function fetchHealthCard(): Promise<HealthCardInfo> {
  const [profile, card] = await Promise.all([
    api<ProfileForCard>("users/me"),
    api<CardSignature>("users/me/card").catch(() => null),
  ]);
  // Health details exist only with consent: without it there is nothing to ask for.
  let health: HealthDetails | null = null;
  let unavailable = false;
  if (profile.consent?.treatment_processing) {
    try {
      health = await api<HealthDetails>("users/me/health-profile");
    } catch (error) {
      // 403: consent withdrawn meanwhile (none to show); anything else: unknown.
      unavailable = !(error instanceof ApiError && error.status === 403);
    }
  }
  const link = card ? cardVerifyUrl(window.location.origin, card) : "";
  return healthCardFromProfile(profile, link, health, unavailable);
}

/** Splits a typed allergy list on commas, the Ethiopic comma (፣) and semicolons. */
export function splitAllergies(text: string): string[] {
  return text.split(/[,፣;]/).map((a) => a.trim()).filter(Boolean);
}

/** An emergency contact's phone: Ethiopian mobiles (09…, 07…) as +251…, or an international +… number. */
export function normalizeEmergencyPhone(input: string): string | null {
  const trimmed = input.trim();
  const digits = trimmed.replace(/\D/g, "");
  const ethiopian = digits.match(/^(?:251|0)?([79]\d{8})$/);
  if (ethiopian) return `+251${ethiopian[1]}`;
  if (trimmed.startsWith("+") && /^\d{8,15}$/.test(digits)) return `+${digits}`;
  return null;
}

/**
 * The card's emergency lines as text: what the screen, print and image all show.
 * Nothing recorded shows "—", never "none": a blank allergy field must not
 * read as "no allergies" to someone treating the patient.
 */
export function medicalLines(medical: CardMedical | null): {
  blood: string; allergies: string; emergency: string; emergencyPhone: string;
} {
  return {
    blood: medical?.bloodType ?? "—",
    allergies: medical?.allergies.length ? medical.allergies.join(", ") : "—",
    emergency: medical?.emergencyName ?? (medical?.emergencyPhone ? "" : "—"),
    emergencyPhone: medical?.emergencyPhone ?? "",
  };
}

/**
 * Allergies that fit `fits`, ending in "+N" for the rest: when space runs
 * out, the count of hidden allergies is shown rather than silently cut.
 */
export function fitAllergies(allergies: string[], fits: (text: string) => boolean): string {
  if (!allergies.length) return "—";
  for (let shown = allergies.length; shown >= 1; shown -= 1) {
    const rest = allergies.length - shown;
    const text = allergies.slice(0, shown).join(", ") + (rest ? ` +${rest}` : "");
    if (fits(text)) return text;
  }
  return `${allergies[0]} +${allergies.length - 1}`;
}
