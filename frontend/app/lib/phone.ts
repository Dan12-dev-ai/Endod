// Normalize an Ethiopian phone number into the SMS Ethiopia `msisdn` format:
// 251XXXXXXXXX (country code 251 + 9 digits starting with 9).
// Accepts "2519...", "09...", "9..." and common spacing/punctuation.
// Returns null when the number can't be interpreted as a valid mobile number.
export function normalizeEthiopianPhone(input: string): string | null {
  const digits = (input ?? "").replace(/\D/g, "");

  // Already international: 251 + 9 digits (starts with 9).
  if (/^2519\d{8}$/.test(digits)) {
    return digits;
  }
  // Local without leading zero: 9XXXXXXXX.
  if (/^9\d{8}$/.test(digits)) {
    return `251${digits}`;
  }
  // Local with leading zero: 09XXXXXXXX.
  if (/^09\d{8}$/.test(digits)) {
    return `251${digits.slice(1)}`;
  }

  return null;
}
