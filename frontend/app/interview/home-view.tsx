"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { useI18n, type TranslationKey } from "../lib/i18n";
import { QrCode } from "lucide-react";
import { type Appointment, appointmentTitle, formatWhen } from "./data";
import { Bone, HealthCardBones, InlineSkeleton, Skeleton } from "../components/skeleton";
import HealthCardView from "../health-card/card-view";
import { FollowUpCards, QueueCard } from "./care-cards";
import type { BookingPreset } from "./history-data";
import { invalidateHealthCard, loadHealthCard, type HealthCardInfo } from "../health-card/health-card-data";

type Props = {
  firstName: string;
  onNavigate: (nav: string) => void;
  /** "Book now" on a follow-up. */
  onBook: (preset: BookingPreset) => void;
};

const SHORTCUTS: { nav: string; titleKey: TranslationKey; hintKey: TranslationKey }[] = [
  { nav: "booking", titleKey: "home.shortcut.booking.title", hintKey: "home.shortcut.booking.hint" },
  { nav: "appointment", titleKey: "home.shortcut.appointment.title", hintKey: "home.shortcut.appointment.hint" },
  { nav: "followup", titleKey: "home.shortcut.followup.title", hintKey: "home.shortcut.followup.hint" },
  { nav: "message", titleKey: "home.shortcut.message.title", hintKey: "home.shortcut.message.hint" },
];

/** The landing screen: what is next, and where to go. */
export default function HomeView({ firstName, onNavigate, onBook }: Props) {
  const { t, locale } = useI18n();
  const [next, setNext] = useState<Appointment | null | undefined>(undefined);
  // undefined while loading; null if it could not be loaded.
  const [unread, setUnread] = useState<number | null | undefined>(undefined);
  const [card, setCard] = useState<HealthCardInfo | null | undefined>(undefined);
  const [qrOpen, setQrOpen] = useState(false);
  const closeQr = useCallback(() => setQrOpen(false), []);
  const [cardAttempt, setCardAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api<Appointment[]>("users/me/appointments", { query: { upcoming_only: true, limit: 1 } })
      .then((list) => !cancelled && setNext(list[0] ?? null))
      .catch(() => !cancelled && setNext(null));
    api<{ unread_count: number }>("users/me/inbox", { query: { limit: 1 } })
      .then((page) => !cancelled && setUnread(page.unread_count))
      .catch(() => !cancelled && setUnread(null));
    return () => {
      cancelled = true;
    };
  }, []);

  // The card loads on its own, so "Try again" can repeat just this part.
  useEffect(() => {
    let cancelled = false;
    loadHealthCard()
      .then((info) => !cancelled && setCard(info))
      .catch(() => !cancelled && setCard(null));
    return () => {
      cancelled = true;
    };
  }, [cardAttempt]);

  return (
    <div data-purpose="home-view" className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-5xl mx-auto space-y-6 py-6">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 dark:text-gray-100 tracking-tight">
            {firstName ? t("home.welcomeNamed", { name: firstName }) : t("home.welcome")}
          </h1>
          <button
            type="button"
            data-purpose="open-settings"
            onClick={() => onNavigate("setting")}
            className="inline-flex items-center justify-center w-9 h-9 rounded-lg border border-slate-200 dark:border-gray-600 text-slate-600 dark:text-gray-200 hover:bg-slate-50 dark:hover:bg-gray-700 hover:text-slate-900 dark:hover:text-white transition"
            aria-label={t("interview.nav.setting")}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>

        {/* Live: a place in today's queue, and follow-ups to book. */}
        <QueueCard />
        <FollowUpCards onBook={onBook} />

        {/* The card comes first: open the app, show the phone, get scanned. */}
        <section aria-labelledby="home-card-title" className="bg-white dark:bg-gray-800 rounded-2xl border border-slate-200 card-shadow p-4 sm:p-6" data-purpose="home-card">
          <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-5 md:gap-8 items-center">
            <div className="w-full max-w-[520px] mx-auto md:mx-0">
              {card === undefined ? (
                <Skeleton label={t("common.loading")}>
                  <HealthCardBones />
                </Skeleton>
              ) : card ? (
                <HealthCardView card={card} />
              ) : (
                <div className="aspect-[1.586] w-full rounded-2xl border border-dashed border-slate-300 flex flex-col items-center justify-center gap-3 p-6 text-center" data-purpose="home-card-error" role="alert">
                  <p className="text-sm text-slate-600">{t("home.cardLoadError")}</p>
                  <button
                    className="px-4 py-2 rounded-lg border border-slate-300 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    onClick={() => {
                      invalidateHealthCard();
                      setCard(undefined);
                      setCardAttempt((n) => n + 1);
                    }}
                    type="button"
                  >
                    {t("common.tryAgain")}
                  </button>
                </div>
              )}
            </div>
            <div className="space-y-4">
              <div>
                <h2 id="home-card-title" className="text-lg font-bold text-slate-900 dark:text-gray-100">{t("home.yourCard")}</h2>
                <p className="text-sm text-slate-500 mt-1">{t("home.cardHint")}</p>
              </div>
              <div className="flex flex-col sm:flex-row md:flex-col lg:flex-row gap-2.5">
                <button
                  className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-gray-800 hover:bg-gray-700 dark:bg-white dark:hover:bg-gray-200 text-white dark:text-black text-sm font-semibold transition disabled:opacity-50"
                  data-purpose="home-show-qr"
                  disabled={!card?.qrSvg}
                  onClick={() => setQrOpen(true)}
                  type="button"
                >
                  <QrCode className="w-4 h-4" aria-hidden />
                  {t("home.showQr")}
                </button>
                <Link
                  className="inline-flex items-center justify-center px-4 py-2.5 rounded-xl border border-slate-200 dark:border-gray-600 hover:bg-slate-50 dark:hover:bg-gray-700 text-slate-700 dark:text-gray-200 text-sm font-semibold transition"
                  data-purpose="home-open-card"
                  href="/health-card"
                >
                  {t("home.openCard")}
                </Link>
              </div>
              {card?.medicalUnavailable && (
                <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-3.5 py-2.5" data-purpose="home-health-unavailable">
                  {t("home.healthDetailsUnavailable")}
                </p>
              )}
            </div>
          </div>
        </section>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
<button type="button" aria-busy={next === undefined} data-purpose="home-next-appointment" onClick={() => onNavigate("appointment")} className="group text-left bg-white dark:bg-gray-800 p-6 rounded-2xl border border-slate-300 shadow-md hover:bg-gray-800 hover:border-gray-800 hover:text-white dark:hover:!bg-gray-700 dark:hover:!border-gray-700 transition cursor-pointer min-h-[112px] flex flex-col justify-between">
            <p className="text-xs font-medium text-slate-400 uppercase tracking-wider group-hover:text-slate-300 dark:group-hover:!text-gray-300">{t("home.nextAppointment")}</p>
            {next === undefined ? (
              <InlineSkeleton label={t("common.loading")}>
                <Bone className="h-5 w-2/3 rounded mt-1.5" />
                <Bone className="h-3.5 w-1/2 rounded mt-1.5" />
              </InlineSkeleton>
            ) : (
              <>
                <h2 className="text-lg font-bold text-slate-900 dark:text-gray-100 mt-1 group-hover:text-white dark:group-hover:!text-white">
                  {next ? formatWhen(next.scheduled_at, locale) : t("home.noneScheduled")}
                </h2>
                {next && <p className="text-sm text-emerald-600 font-medium mt-0.5 group-hover:text-emerald-300 dark:group-hover:!text-emerald-300">{appointmentTitle(next, t)}</p>}
              </>
            )}
          </button>
<button type="button" aria-busy={unread === undefined} data-purpose="home-unread" onClick={() => onNavigate("message")} className="group text-left bg-white dark:bg-gray-800 p-6 rounded-2xl border border-slate-300 shadow-md hover:bg-gray-800 hover:border-gray-800 hover:text-white dark:hover:!bg-gray-700 dark:hover:!border-gray-700 transition cursor-pointer min-h-[112px] flex flex-col justify-between">
            <p className="text-xs font-medium text-slate-400 uppercase tracking-wider group-hover:text-slate-300 dark:group-hover:!text-gray-300">{t("home.notifications")}</p>
            {unread === undefined ? (
              <InlineSkeleton label={t("common.loading")}>
                <Bone className="h-5 w-1/2 rounded mt-1.5" />
              </InlineSkeleton>
            ) : (
              <h2 className="text-lg font-bold text-slate-900 dark:text-gray-100 mt-1 group-hover:text-white dark:group-hover:!text-white">
                {unread === null ? "—" : unread === 0 ? t("home.upToDate") : t("home.unread", { count: unread })}
              </h2>
            )}
          </button>
          {SHORTCUTS.map((s) => (
<button key={s.nav} type="button" data-purpose={`home-shortcut-${s.nav}`} onClick={() => onNavigate(s.nav)} className="group text-left bg-white dark:bg-gray-800 p-6 rounded-2xl border border-slate-300 shadow-md hover:bg-gray-800 hover:border-gray-800 hover:text-white dark:hover:!bg-gray-700 dark:hover:!border-gray-700 transition cursor-pointer min-h-[112px] flex flex-col justify-between">
              <h3 className="text-base font-bold text-slate-900 dark:text-gray-100 group-hover:text-white dark:group-hover:!text-white">{t(s.titleKey)}</h3>
              <p className="text-sm text-slate-500 mt-1 group-hover:text-slate-300 dark:group-hover:!text-gray-300">{t(s.hintKey)}</p>
            </button>
          ))}
        </div>
      </div>
      {qrOpen && card?.qrSvg && <QrScreen card={card} onClose={closeQr} />}
    </div>
  );
}

/** True when the card has any of the emergency details. */
function hasMedical(card: HealthCardInfo): boolean {
  const m = card.medical;
  return Boolean(m && (m.bloodType || m.allergies.length || m.emergencyName || m.emergencyPhone));
}

/**
 * The QR code alone, large, black on white, for a hospital's scanner: the
 * easiest thing to scan from a phone screen. Closes with the button, Escape
 * or a tap outside the code.
 */
function QrScreen({ card, onClose }: { card: HealthCardInfo; onClose: () => void }) {
  const { t } = useI18n();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    // Escape closes; Tab stays on the dialog's only control (focus never
    // wanders to the page hidden behind it).
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab") {
        event.preventDefault();
        closeRef.current?.focus();
      }
    };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [onClose]);

  // Rendered at the end of <body>, above everything (toasts included).
  return createPortal((
    <div
      aria-labelledby="qr-screen-title"
      aria-modal="true"
      className="fixed inset-0 z-[100] bg-white dark:bg-gray-800 flex flex-col items-center justify-center p-6"
      data-purpose="qr-screen"
      onClick={onClose}
      role="dialog"
    >
      <div className="w-full max-w-sm flex flex-col items-center text-center" onClick={(event) => event.stopPropagation()}>
        <p id="qr-screen-title" className="text-sm font-semibold text-slate-500 uppercase tracking-wider">{t("home.qrTitle")}</p>
        <div
          aria-label={t("healthCard.scanToVerify")}
          className="w-full aspect-square max-w-[min(80vw,360px)] my-6"
          role="img"
          dangerouslySetInnerHTML={{ __html: card.qrSvg }}
        />
        <p className="text-2xl font-bold font-serif text-slate-900 dark:text-gray-100">{card.fullName}</p>
        <p className="text-base font-semibold text-emerald-700 mt-1">{card.userId}</p>
        <button
          className="mt-8 px-8 py-3 rounded-full border border-slate-300 text-slate-700 font-semibold hover:bg-slate-50"
          data-purpose="qr-screen-close"
          onClick={onClose}
          ref={closeRef}
          type="button"
        >
          {t("home.closeQr")}
        </button>
      </div>
    </div>
  ), document.body);
}
