"use client";

// The Endod balance: what the patient has, adding money through Chapa, and
// every movement (deposits, payments, Endod's fee, refunds). The balance pays
// for health services only; it cannot be withdrawn.

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n, type TranslationKey } from "../lib/i18n";
import { Bone, RowBones, Skeleton } from "../components/skeleton";
import { formatBirr, formatWhen } from "./data";

type Entry = {
  id: string;
  kind: "deposit" | "payment" | "service_fee" | "refund" | "reversal";
  amount: number;
  balance_after: number;
  description: string | null;
  created_at: string;
};

type Wallet = { balance: number; currency: string; entries: Entry[] };

type Deposit = { deposit_id: string; status: "pending" | "succeeded" | "failed" | "reversed"; checkout_url: string | null; amount: number };

/** How often, and how many times, a payment is checked on the way back from Chapa. */
const CHECK_EVERY_MS = 2000;
const CHECKS = 10;

/** Quick amounts, in birr. */
const PRESETS = [100, 250, 500, 1000];

const KIND_KEYS: Record<Entry["kind"], TranslationKey> = {
  deposit: "wallet.kind.deposit",
  payment: "wallet.kind.payment",
  service_fee: "wallet.kind.service_fee",
  refund: "wallet.kind.refund",
  reversal: "wallet.kind.reversal",
};

export default function WalletView({ onToast }: { onToast: (title: string, message: string) => void }) {
  const { t, locale } = useI18n();
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [loadError, setLoadError] = useState("");
  const [amount, setAmount] = useState("250");
  const [formError, setFormError] = useState("");
  const [isStarting, setIsStarting] = useState(false);
  const [checking, setChecking] = useState(false);

  const load = useCallback(async () => {
    try {
      setWallet(await api<Wallet>("users/me/wallet"));
      setLoadError("");
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : t("wallet.error.load"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is stable per language
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
  }, [load]);

  // Back from Chapa (?deposit=<id>): ask until the payment is settled. Safe
  // to run again if the view remounts (checking a deposit is idempotent).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const depositId = params.get("deposit");
    if (!depositId || !/^[a-f0-9]{32}$/.test(depositId)) return;
    let cancelled = false;
    const poll = async () => {
      setChecking(true);
      let settled = false;
      for (let attempt = 0; attempt < CHECKS && !cancelled && !settled; attempt++) {
        try {
          const deposit = await api<Deposit>(`users/me/wallet/deposits/${depositId}`);
          if (cancelled) return;
          if (deposit.status === "succeeded") {
            onToast(t("wallet.toast.addedTitle"), t("wallet.toast.added", { amount: formatBirr(deposit.amount, locale) }));
            settled = true;
          } else if (deposit.status === "failed") {
            onToast(t("wallet.toast.failedTitle"), t("wallet.toast.failed"));
            settled = true;
          } else if (deposit.status === "reversed") {
            settled = true;
          }
        } catch {
          // keep trying a few times
        }
        if (!settled) await new Promise((resolve) => setTimeout(resolve, CHECK_EVERY_MS));
      }
      if (cancelled) return;
      // Still pending: the backend keeps checking with Chapa and adds the
      // money when it is confirmed; the patient is told so.
      if (!settled) onToast(t("wallet.toast.pendingTitle"), t("wallet.toast.pending"));
      setChecking(false);
      window.history.replaceState(null, "", window.location.pathname);
      void load();
    };
    void poll();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on arrival
  }, []);

  const startDeposit = async (e: React.FormEvent) => {
    e.preventDefault();
    const value = Number(amount);
    if (!Number.isFinite(value) || value < 10 || value > 100_000) {
      setFormError(t("wallet.error.amount"));
      return;
    }
    setIsStarting(true);
    setFormError("");
    try {
      const deposit = await api<Deposit>("users/me/wallet/deposits", {
        method: "POST", body: { amount: value.toFixed(2) },
      });
      if (!deposit.checkout_url) throw new Error(t("wallet.error.start"));
      window.location.assign(deposit.checkout_url);
    } catch (error) {
      setFormError(error instanceof ApiError || error instanceof Error ? error.message : t("wallet.error.start"));
      setIsStarting(false);
    }
  };

  // Back from Chapa with the browser's Back button (page restored from
  // cache): the Continue button works again.
  useEffect(() => {
    const onShow = (event: PageTransitionEvent) => {
      if (event.persisted) setIsStarting(false);
    };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  return (
    <div data-purpose="wallet-view" className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-3xl mx-auto py-6 space-y-6">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">{t("wallet.title")}</h1>
          <p className="text-sm text-slate-500 mt-1">{t("wallet.subtitle")}</p>
        </div>

        {loadError && (
          <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">{loadError}</p>
        )}

        <section className="rounded-2xl bg-gradient-to-br from-[#1e3a2e] to-[#1e5852] text-white p-6" data-purpose="wallet-balance">
          <p className="text-xs uppercase tracking-wider text-[#94e0c0] font-semibold">{t("wallet.balance")}</p>
          {wallet ? (
            <p className="text-3xl font-extrabold mt-2" data-purpose="wallet-amount">{formatBirr(wallet.balance, locale)}</p>
          ) : !loadError ? (
            <Skeleton className="mt-2" label={t("common.loading")}>
              <Bone className="h-9 w-40 rounded bg-white/20" />
            </Skeleton>
          ) : null}
          {checking && <p className="text-xs text-white/80 mt-2" role="status">{t("wallet.checking")}</p>}
          <p className="text-xs text-white/70 mt-3">{t("wallet.noWithdrawals")}</p>
        </section>

        <section className="bg-white rounded-2xl border border-slate-200 card-shadow p-5 sm:p-6">
          <h2 className="text-lg font-bold text-slate-900">{t("wallet.addMoney")}</h2>
          <p className="text-xs text-slate-500 mt-1">{t("wallet.addMoneyHint")}</p>
          <form className="mt-4 space-y-4" data-purpose="deposit-form" onSubmit={startDeposit}>
            <div className="flex flex-wrap gap-2">
              {PRESETS.map((preset) => (
                <button
                  className={`px-4 py-2 rounded-xl border text-sm font-semibold transition ${
                    amount === String(preset) ? "border-emerald-600 bg-emerald-50 text-emerald-800" : "border-slate-200 text-slate-600 hover:bg-slate-50"
                  }`}
                  key={preset}
                  onClick={() => setAmount(String(preset))}
                  type="button"
                >
                  {preset} {t("wallet.birr")}
                </button>
              ))}
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="deposit-amount">{t("wallet.amountLabel")}</label>
              <input
                className="w-full sm:w-60 rounded-xl border border-slate-200 px-3 py-2 text-sm"
                id="deposit-amount"
                inputMode="decimal"
                max={100000}
                min={10}
                onChange={(e) => setAmount(e.target.value)}
                step="0.01"
                type="number"
                value={amount}
              />
            </div>
            {formError && (
              <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" data-purpose="deposit-error" role="alert">{formError}</p>
            )}
            <button
              className="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white text-sm font-semibold"
              data-purpose="deposit-submit"
              disabled={isStarting}
              type="submit"
            >
              {isStarting ? t("wallet.redirecting") : t("wallet.payWithChapa")}
            </button>
          </form>
        </section>

        <section className="space-y-3">
          <h2 className="text-sm font-bold text-slate-700 uppercase tracking-wider">{t("wallet.history")}</h2>
          {!wallet && !loadError && (
            <Skeleton className="space-y-3" label={t("common.loading")}>
              <RowBones />
              <RowBones />
            </Skeleton>
          )}
          {wallet && wallet.entries.length === 0 && (
            <p className="text-xs text-slate-500 bg-white border border-slate-200 rounded-2xl p-4" data-purpose="wallet-empty">{t("wallet.empty")}</p>
          )}
          {wallet?.entries.map((entry) => (
            <div className="bg-white rounded-2xl border border-slate-200 p-4 flex items-center justify-between gap-3" data-purpose={`wallet-entry-${entry.kind}`} key={entry.id}>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900">{t(KIND_KEYS[entry.kind])}</p>
                <p className="text-xs text-slate-500 truncate">{entry.description ?? ""} · {formatWhen(entry.created_at, locale)}</p>
              </div>
              <p className={`text-sm font-bold whitespace-nowrap ${entry.amount > 0 ? "text-emerald-700" : "text-slate-800"}`}>
                {entry.amount > 0 ? "+" : "−"}{formatBirr(Math.abs(entry.amount), locale)}
              </p>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
