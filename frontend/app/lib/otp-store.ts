// In-memory OTP store.
//
// NOTE: There is no database in this project yet, so codes are kept in a
// process-level Map. This works for a single running server (dev and a
// single-instance deployment). If you later run multiple instances or a
// serverless/edge runtime, replace this with a shared store (Redis, a DB
// table, etc.) so a code sent by one instance can be verified by another.

type OtpRecord = {
  code: string;
  expiresAt: number;
  attempts: number;
};

const store = new Map<string, OtpRecord>();

const TTL_MS = 5 * 60 * 1000; // codes are valid for 5 minutes
const MAX_ATTEMPTS = 5;

/** Human-friendly TTL used in the SMS message. */
export const OTP_TTL_MINUTES = 5;

export function generateCode(): string {
  return String(Math.floor(100000 + Math.random() * 900000));
}

export function createOtp(msisdn: string): string {
  const code = generateCode();
  store.set(msisdn, {
    code,
    expiresAt: Date.now() + TTL_MS,
    attempts: 0,
  });
  return code;
}

export type VerifyResult = { ok: true } | { ok: false; reason: string };

export function verifyOtp(msisdn: string, code: string): VerifyResult {
  const record = store.get(msisdn);

  if (!record) {
    return { ok: false, reason: "No code was requested for this number. Please request a new one." };
  }
  if (Date.now() > record.expiresAt) {
    store.delete(msisdn);
    return { ok: false, reason: "The code has expired. Please request a new one." };
  }
  if (record.attempts >= MAX_ATTEMPTS) {
    store.delete(msisdn);
    return { ok: false, reason: "Too many incorrect attempts. Please request a new code." };
  }
  if (record.code !== code) {
    record.attempts += 1;
    return { ok: false, reason: "Incorrect code. Please try again." };
  }

  store.delete(msisdn);
  return { ok: true };
}
