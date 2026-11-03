"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { TranslationKey } from "../lib/i18n";

/**
 * The phone layout of the patient app: a tile dashboard at /interview and one
 * screen per section under /interview/mobile-*. Every screen renders the same
 * view the desktop app uses (booking-view, appointments-view, ...), so there is
 * one copy of each screen's behaviour.
 */

/** Phone widths get the mobile layout; wider screens keep the sidebar app. */
export const PHONE_QUERY = "(max-width: 767px)";

export type MobileSection = {
  id: string;
  /** The desktop app's `?section=` for the same screen, if it has one. */
  section: string | null;
  href: string;
  labelKey: TranslationKey;
  titleKey: TranslationKey;
  /** Shown in the phone's bottom bar (five fit); every section has a dashboard tile. */
  bottomNav: boolean;
  icon: ReactNode;
};

const iconProps = {
  "aria-hidden": true,
  className: "w-6 h-6",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  viewBox: "0 0 24 24",
} as const;
const line = { strokeLinecap: "round", strokeLinejoin: "round" } as const;

export const MOBILE_SECTIONS: MobileSection[] = [
  {
    id: "card",
    section: null,
    href: "/interview/mobile-card",
    labelKey: "mobile.nav.card",
    titleKey: "mobile.title.card",
    bottomNav: true,
    icon: (
      <svg {...iconProps}>
        <rect x="2" y="5" width="20" height="14" rx="2" />
        <path d="M2 10h20" />
      </svg>
    ),
  },
  {
    id: "booking",
    section: "booking",
    href: "/interview/mobile-booking",
    labelKey: "mobile.nav.booking",
    titleKey: "booking.title",
    bottomNav: true,
    icon: (
      <svg {...iconProps}>
        <path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" {...line} />
      </svg>
    ),
  },
  {
    id: "appointment",
    section: "appointment",
    href: "/interview/mobile-appointment",
    labelKey: "mobile.nav.appointment",
    titleKey: "appointments.title",
    bottomNav: true,
    icon: (
      <svg {...iconProps}>
        <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" {...line} />
      </svg>
    ),
  },
  {
    id: "bills",
    section: "bills",
    href: "/interview/mobile-bills",
    labelKey: "interview.nav.bills",
    titleKey: "bills.title",
    bottomNav: false,
    icon: (
      <svg {...iconProps}>
        <path d="M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2z" {...line} />
      </svg>
    ),
  },
  {
    id: "records",
    section: "followup",
    href: "/interview/mobile-records",
    labelKey: "interview.nav.medicalRecord",
    titleKey: "interview.nav.medicalRecord",
    bottomNav: false,
    icon: (
      <svg {...iconProps}>
        <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" {...line} />
      </svg>
    ),
  },
  {
    id: "notification",
    section: "message",
    href: "/interview/mobile-notification",
    labelKey: "mobile.nav.notification",
    titleKey: "notifications.title",
    bottomNav: true,
    icon: (
      <svg {...iconProps}>
        <path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" {...line} />
      </svg>
    ),
  },
  {
    id: "setting",
    section: "setting",
    href: "/interview/mobile-setting",
    labelKey: "mobile.nav.setting",
    titleKey: "settings.title",
    bottomNav: true,
    icon: (
      <svg {...iconProps}>
        <path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" {...line} />
        <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" {...line} />
      </svg>
    ),
  },
];

/** The mobile screen for a desktop `?section=` (null: the dashboard). */
export function mobileHref(section: string | null, highlight?: string | null): string | null {
  const found = MOBILE_SECTIONS.find((s) => s.section !== null && s.section === section);
  if (!found) return null;
  return highlight ? `${found.href}?highlight=${encodeURIComponent(highlight)}` : found.href;
}

/** "Book now" on a follow-up carries the hospital and day to the booking screen. */
export const BOOKING_PRESET_KEY = "dedan:mobile:bookingPreset";

/**
 * Whether this is a phone, decided once when the page mounts (null until then).
 * Fixed for the page's life, so turning the phone never swaps the layout and
 * loses what the patient was typing.
 */
export function useIsPhone(): boolean | null {
  const [isPhone, setIsPhone] = useState<boolean | null>(null);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- matchMedia only exists in the browser
    setIsPhone(window.matchMedia(PHONE_QUERY).matches);
  }, []);
  return isPhone;
}

// ===== Toast: one for every mobile screen, shown by the mobile layout =====

type ShowToast = (title: string, message: string) => void;
const ToastContext = createContext<ShowToast>(() => undefined);

export function useMobileToast(): ShowToast {
  return useContext(ToastContext);
}

export function MobileToastProvider({ children, closeLabel }: { children: ReactNode; closeLabel: string }) {
  const [toast, setToast] = useState<{ title: string; message: string } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const show = useCallback<ShowToast>((title, message) => {
    if (timer.current) clearTimeout(timer.current);
    setToast({ title, message });
    timer.current = setTimeout(() => setToast(null), 4000);
  }, []);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div aria-live="polite" className="fixed top-4 inset-x-4 z-[60] flex justify-center pointer-events-none">
        {toast && (
          <div data-purpose="toast-notification" role="status" className="pointer-events-auto flex items-start gap-3 bg-black text-white px-4 py-3 rounded-xl shadow-xl max-w-md w-full">
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold tracking-wide uppercase">{toast.title}</p>
              <p className="text-xs text-slate-300">{toast.message}</p>
            </div>
            <button type="button" aria-label={closeLabel} onClick={() => setToast(null)} className="text-slate-300 hover:text-white text-base leading-none px-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-white rounded">
              ×
            </button>
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}
