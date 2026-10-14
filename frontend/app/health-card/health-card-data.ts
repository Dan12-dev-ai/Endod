/**
 * Shared Digital Health Card data helpers.
 *
 * Single source of truth for the card identity data (full name, patient ID,
 * phone, issued/expiry dates, QR payload) used by both the /health-card
 * route and the Digital Health Card preview on the /interview settings page.
 * Data is read from the onboarding/session entries written at signup.
 */

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
};

export type StoredOnboarding = {
  firstName?: string;
  middleName?: string;
  lastName?: string;
  completedAt?: string;
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

export function generateUserId(phone: string): string {
  const e164 = formatPhoneE164(phone);
  let hash = 0;
  for (let i = 0; i < e164.length; i++) {
    hash = ((hash << 5) - hash + e164.charCodeAt(i)) & 0xffffffff;
  }
  const positive = Math.abs(hash);
  return "HCA" + String(10000000 + (positive % 90000000)).slice(1);
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

/**
 * Read the health card data from localStorage (written during onboarding).
 * Returns null when no onboarding/session data exists — callers decide how
 * to fall back (redirect to signup on /health-card, profile defaults on the
 * settings preview).
 */
export function readHealthCardData(): HealthCardInfo | null {
  if (typeof window === "undefined") return null;

  let onboarding: StoredOnboarding = {};
  try {
    onboarding = JSON.parse(localStorage.getItem("dedan_onboarding") ?? "{}");
  } catch {
    // parse error — fall through with defaults
  }
  let sessionPhone = "";
  try {
    const session = JSON.parse(localStorage.getItem("dedan_session") ?? "{}");
    sessionPhone = session.phone ?? "";
  } catch {
    // parse error — fall through
  }

  const hasOnboarding =
    !!onboarding &&
    (onboarding.firstName || onboarding.lastName || onboarding.completedAt);
  if (!hasOnboarding && !sessionPhone) return null;

  const fullName = getFullName(
    onboarding.firstName ?? "",
    onboarding.middleName ?? "",
    onboarding.lastName ?? "",
  );
  const createdAt = onboarding.completedAt ?? new Date().toISOString();
  const userId = sessionPhone ? generateUserId(sessionPhone) : "HCA00000001";
  const qrData = `endod:${userId}:${createdAt}`;

  return {
    firstName: onboarding.firstName ?? "",
    middleName: onboarding.middleName ?? "",
    lastName: onboarding.lastName ?? "",
    fullName,
    userId,
    phone: formatPhoneDisplay(sessionPhone),
    issuedDate: getIssuedDate(createdAt),
    expiryDate: getExpiryDate(createdAt),
    qrData,
    qrSvg: qrMatrixToSvg(generateQrMatrix(qrData), 152),
  };
}
