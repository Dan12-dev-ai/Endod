"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n, type TranslationKey } from "../lib/i18n";
import { Bone, Skeleton } from "../components/skeleton";

/** GET/PUT /users/me/sms-pin (backend-v2/dedan_platform/api_sms.py). */
export type SmsPinState = {
  has_pin: boolean;
  /** Set while too many wrong PINs keep it locked; a new PIN unlocks it. */
  locked_until: string | null;
  /** Only while patients can text commands (SMS_INBOUND_ENABLED and SMS_SHORT_CODE). */
  short_code: string | null;
  commands_enabled: boolean;
};

/** The commands a patient texts with their PIN (docs/sms.md, section 3). */
const COMMANDS: { word: string; replyKey: TranslationKey }[] = [
  { word: "CARD", replyKey: "settings.smsPin.cmd.card" },
  { word: "APPT", replyKey: "settings.smsPin.cmd.appt" },
  { word: "RESULT", replyKey: "settings.smsPin.cmd.result" },
  { word: "REPORT", replyKey: "settings.smsPin.cmd.report" },
  { word: "RX", replyKey: "settings.smsPin.cmd.rx" },
];

// Mirrors dedan_platform/sms_pin.py so most mistakes are caught before sending;
// the backend still decides.
const WEAK = new Set(["1234", "4321", "1212", "1122", "2580", "0852", "1984", "2000", "1010", "6969", "0123",
  "9876", "1004", "2001", "1111", "0000"]);

function pinProblem(pin: string, confirm: string): TranslationKey | null {
  if (!/^\d{4}$/.test(pin)) return "settings.smsPin.error.format";
  if (new Set(pin).size === 1 || WEAK.has(pin)) return "settings.smsPin.error.weak";
  if (pin !== confirm) return "settings.smsPin.error.mismatch";
  return null;
}

const inputClass = "w-full text-base tracking-[0.5em] rounded-xl border border-brand-border bg-brand-inputbg focus:border-brand-primary focus:ring-brand-primary py-2.5 px-3.5 shadow-xs text-brand-heading";
const labelClass = "block text-xs font-semibold uppercase tracking-wider text-brand-heading mb-1.5";
const saveClass = "px-5 py-2.5 bg-brand-primary hover:bg-[#12564F] disabled:opacity-60 text-white font-semibold text-xs sm:text-sm rounded-xl shadow-sm transition-all";

type Props = {
  /** Commands only work from the account's verified phone. */
  phoneVerified: boolean;
};

/** Settings section: the 4-digit PIN for SMS commands, and the commands themselves while the short code is live. */
export default function SmsPinSection({ phoneVerified }: Props) {
  const { t, locale } = useI18n();
  const [state, setState] = useState<SmsPinState | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [pin, setPin] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [saving, setSaving] = useState(false);

  const fetchState = useCallback(() => api<SmsPinState>("users/me/sms-pin"), []);

  useEffect(() => {
    let cancelled = false;
    fetchState()
      .then((s) => { if (!cancelled) setState(s); })
      .catch(() => { if (!cancelled) setLoadError(true); });
    return () => {
      cancelled = true;
    };
  }, [fetchState]);

  const retry = () => {
    setLoadError(false);
    fetchState().then(setState).catch(() => setLoadError(true));
  };

  const onlyDigits = (value: string) => value.replace(/\D/g, "").slice(0, 4);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!state) return;
    setSuccess("");
    const problem = pinProblem(pin, confirm);
    if (problem) {
      setError(t(problem));
      return;
    }
    setError("");
    setSaving(true);
    const hadPin = state.has_pin;
    try {
      setState(await api<SmsPinState>("users/me/sms-pin", { method: "PUT", body: { pin } }));
      setPin("");
      setConfirm("");
      setSuccess(t(hadPin ? "settings.smsPin.success.changed" : "settings.smsPin.success.set"));
    } catch (err) {
      // 422: the backend refused the PIN (too easy to guess, or not 4 digits).
      setError(err instanceof ApiError && err.status === 422 ? t("settings.smsPin.error.weak")
        : err instanceof ApiError && err.status === 0 ? err.message : t("settings.smsPin.error.save"));
    } finally {
      setSaving(false);
    }
  };

  // The server sends locked_until only while the PIN is locked.
  const lockedUntil = state?.locked_until ? new Date(state.locked_until) : null;
  const commandsLive = Boolean(state?.commands_enabled && state.short_code);

  return (
    <section data-purpose="sms-pin-section" aria-labelledby="sms-pin-title" className="bg-white rounded-2xl border border-brand-border shadow-xs p-5 sm:p-7 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2 border-b border-brand-bg pb-4">
        <div>
          <h2 id="sms-pin-title" className="text-lg font-bold text-brand-heading">{t("settings.smsPin.title")}</h2>
          <p className="text-xs sm:text-sm text-brand-muted">{t("settings.smsPin.subtitle")}</p>
        </div>
        {state && (
          <span
            data-purpose="sms-pin-status"
            data-has-pin={state.has_pin}
            className={`self-start shrink-0 px-3 py-1 text-xs font-semibold rounded-full border ${state.has_pin
              ? "bg-app-green-light text-brand-primary border-brand-primary/20"
              : "bg-app-amber/10 text-app-amber border-app-amber/20"}`}
          >
            {state.has_pin ? t("settings.smsPin.status.set") : t("settings.smsPin.status.notSet")}
          </span>
        )}
      </div>

      <p className="text-sm text-brand-heading">{t("settings.smsPin.explain")}</p>

      {loadError ? (
        <div className="flex flex-wrap items-center gap-3">
          <p data-purpose="sms-pin-load-error" className="text-xs text-[#B42318]" role="alert">{t("settings.smsPin.error.load")}</p>
          <button type="button" onClick={retry} className="text-xs font-semibold text-brand-primary hover:underline">
            {t("common.tryAgain")}
          </button>
        </div>
      ) : !state ? (
        <Skeleton className="space-y-3" label={t("settings.smsPin.loading")}>
          <Bone className="h-10 w-full rounded-xl" />
          <Bone className="h-10 w-full rounded-xl" />
        </Skeleton>
      ) : (
        <>
          {lockedUntil && (
            <p data-purpose="sms-pin-locked" role="status" className="text-xs text-app-amber bg-app-amber/10 border border-app-amber/20 rounded-xl p-3">
              {t("settings.smsPin.locked", { time: lockedUntil.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" }) })}
            </p>
          )}

          <form onSubmit={save} noValidate className="space-y-5" aria-describedby="sms-pin-hint">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label className={labelClass} htmlFor="sms-pin-new">
                  {state.has_pin ? t("settings.smsPin.new") : t("settings.smsPin.pin")}
                </label>
                <input
                  id="sms-pin-new"
                  data-purpose="sms-pin-new"
                  type="password"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength={4}
                  autoComplete="off"
                  required
                  value={pin}
                  aria-invalid={error ? true : undefined}
                  aria-describedby="sms-pin-hint"
                  onChange={(e) => { setPin(onlyDigits(e.target.value)); setError(""); setSuccess(""); }}
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass} htmlFor="sms-pin-confirm">{t("settings.smsPin.confirm")}</label>
                <input
                  id="sms-pin-confirm"
                  data-purpose="sms-pin-confirm"
                  type="password"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength={4}
                  autoComplete="off"
                  required
                  value={confirm}
                  aria-invalid={error ? true : undefined}
                  onChange={(e) => { setConfirm(onlyDigits(e.target.value)); setError(""); setSuccess(""); }}
                  className={inputClass}
                />
              </div>
            </div>
            <p id="sms-pin-hint" className="text-xs text-brand-muted">{t("settings.smsPin.hint")}</p>
            {error && <p data-purpose="sms-pin-error" className="text-xs text-[#B42318] bg-[#B42318]/10 border border-[#B42318]/20 rounded-xl p-3" role="alert">{error}</p>}
            <div aria-live="polite">
              {success && <p data-purpose="sms-pin-success" className="text-xs text-brand-primary bg-app-green-light border border-brand-primary/20 rounded-xl p-3">{success}</p>}
            </div>
            <div className="flex items-center justify-end gap-3 pt-3 border-t border-brand-bg">
              <button type="submit" data-purpose="sms-pin-save" disabled={saving} className={saveClass}>
                {state.has_pin ? t("settings.smsPin.save.change") : t("settings.smsPin.save.set")}
              </button>
            </div>
          </form>

          {commandsLive ? (
            <div data-purpose="sms-commands" className="bg-brand-bg rounded-xl border border-brand-border p-4 space-y-3">
              <h3 className="text-sm font-bold text-brand-heading">{t("settings.smsPin.commands.title")}</h3>
              <p className="text-xs text-brand-heading">
                {t("settings.smsPin.commands.intro")}{" "}
                <span data-purpose="sms-short-code" className="font-bold text-brand-primary whitespace-nowrap">{state.short_code}</span>
              </p>
              <table className="w-full text-xs sm:text-sm bg-white rounded-lg overflow-hidden">
                <caption className="sr-only">{t("settings.smsPin.commands.title")}</caption>
                <thead>
                  <tr className="text-left text-brand-muted border-b border-brand-border">
                    <th scope="col" className="py-2 px-3 font-semibold">{t("settings.smsPin.commands.colText")}</th>
                    <th scope="col" className="py-2 px-3 font-semibold">{t("settings.smsPin.commands.colReply")}</th>
                  </tr>
                </thead>
                <tbody>
                  {COMMANDS.map((c) => (
                    <tr key={c.word} data-purpose={`sms-command-${c.word.toLowerCase()}`} className="border-b border-brand-bg last:border-0 align-top">
                      <td className="py-2 px-3 whitespace-nowrap">
                        <code className="font-mono font-bold text-brand-primary">{c.word}</code>{" "}
                        <span className="text-brand-muted">+ {t("settings.smsPin.commands.yourPin")}</span>
                      </td>
                      <td className="py-2 px-3 text-brand-heading">{t(c.replyKey)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-xs text-brand-muted">{t("settings.smsPin.commands.sensitive")}</p>
              {!phoneVerified && (
                <p data-purpose="sms-commands-verify-phone" className="text-xs text-app-amber">{t("settings.smsPin.commands.verifiedPhone")}</p>
              )}
            </div>
          ) : (
            <p data-purpose="sms-commands-soon" className="text-xs text-brand-heading bg-brand-bg border border-brand-border rounded-xl p-3">
              {t("settings.smsPin.comingSoon")}
            </p>
          )}
        </>
      )}
    </section>
  );
}
