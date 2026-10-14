// In-memory user store.
//
// NOTE: Same constraint as otp-store.ts — there is no database in this
// project yet, so user records live in a process-level Map. This works for a
// single running server (dev and a single-instance deployment). Replace with
// a shared database before running multiple instances or a serverless/edge
// runtime.
//
// Passwords are hashed with scrypt (random per-user salt) — plaintext
// passwords are never stored.

import { randomBytes, scryptSync, timingSafeEqual } from "crypto";

type UserRecord = {
  salt: string;
  passwordHash: string;
  createdAt: number;
};

const users = new Map<string, UserRecord>();

const KEY_LENGTH = 64;

export const MIN_PASSWORD_LENGTH = 8;
export const MAX_PASSWORD_LENGTH = 128;

function hashPassword(password: string, salt: string): Buffer {
  return scryptSync(password, salt, KEY_LENGTH);
}

export function hasUser(msisdn: string): boolean {
  return users.has(msisdn);
}

export function setUserPassword(msisdn: string, password: string): void {
  const salt = randomBytes(16).toString("hex");
  const passwordHash = hashPassword(password, salt).toString("hex");
  users.set(msisdn, { salt, passwordHash, createdAt: Date.now() });
}

export function verifyUserPassword(msisdn: string, password: string): boolean {
  const record = users.get(msisdn);
  if (!record) {
    return false;
  }
  const candidate = hashPassword(password, record.salt);
  const expected = Buffer.from(record.passwordHash, "hex");
  return candidate.length === expected.length && timingSafeEqual(candidate, expected);
}