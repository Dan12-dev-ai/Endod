"use client";

// The English / አማርኛ switch, on the landing page (dark bar) and in the
// dashboard (white bar). Signed-in callers pass `onChange` to also save the
// choice to the account, so it follows the patient to other devices.

import { useEffect, useRef, useState } from "react";
import { LANGUAGES, useI18n, type Language } from "../lib/i18n";

/** What the button shows on a phone, where the full name does not fit. */
const SHORT: Record<Language, string> = { en: "EN", am: "አማ" };

const TONES = {
  dark: {
    button: "border-neutral-400 text-white hover:bg-white hover:text-black",
    chevron: "text-neutral-400",
  },
  light: {
    button: "border-slate-200 text-slate-700 hover:bg-slate-50 hover:text-slate-900",
    chevron: "text-slate-400",
  },
} as const;

export default function LanguageSwitcher({
  tone = "dark",
  onChange,
}: {
  tone?: keyof typeof TONES;
  onChange?: (language: Language) => void;
}) {
  const { t, language, setLanguage } = useI18n();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const styles = TONES[tone];
  const current = LANGUAGES.find((l) => l.code === language) ?? LANGUAGES[0];

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <div className="relative" ref={rootRef}>
      <button
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={t("nav.selectLanguage")}
        className={`inline-flex items-center gap-1.5 px-3 sm:px-4 py-2 rounded-md border transition-all text-[13px] font-medium tracking-wide focus:outline-none cursor-pointer ${styles.button}`}
        data-purpose="language-select"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
          <path d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10m-1.314-3H9.314" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className={tone === "light" ? "hidden sm:inline" : undefined}>{current.label}</span>
        {tone === "light" && <span className="sm:hidden" lang={current.code}>{SHORT[current.code]}</span>}
        <svg className={`w-3.5 h-3.5 transition-transform ${styles.chevron} ${open ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path d="M19 9l-7 7-7-7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-2 w-40 bg-white text-slate-800 rounded-md shadow-2xl py-1.5 border border-slate-100 flex flex-col text-[14px] z-50"
          data-purpose="language-menu"
          role="listbox"
        >
          {LANGUAGES.map((lang) => (
            <button
              aria-selected={language === lang.code}
              className={`text-left px-4 py-2 transition-colors cursor-pointer ${language === lang.code ? "bg-slate-100 text-black font-semibold" : "hover:bg-slate-100 hover:text-black"}`}
              data-purpose={`language-option-${lang.code}`}
              key={lang.code}
              lang={lang.code}
              onClick={() => {
                setLanguage(lang.code);
                setOpen(false);
                if (lang.code !== language) onChange?.(lang.code);
              }}
              role="option"
              type="button"
            >
              {lang.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Save the choice to the signed-in patient's account. Best effort: the
 * choice already applies on this device, so a failed save only means other
 * devices keep their own.
 */
export function saveAccountLanguage(language: Language): void {
  void fetch("/api/backend/users/me/preferences", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language }),
  }).catch(() => undefined);
}
