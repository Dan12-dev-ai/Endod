"use client";

// The English / አማርኛ switch, on the landing page (dark bar) and in the
// dashboard (white bar). A choice applies to this device at once and is also
// kept with the account (see rememberLanguageChoice), so it follows the
// patient to every device they sign in to.

import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { isLanguage, LANGUAGES, useI18n, type Language } from "../lib/i18n";
import { fetchSession } from "../lib/session";

/** What the button shows on a phone, where the full name does not fit. */
const SHORT: Record<Language, string> = { en: "EN", am: "አማ" };

const menuId = "language-menu";

const TONES = {
  dark: {
    button: "border-neutral-400 text-white hover:bg-white dark:bg-gray-800 hover:text-black",
    chevron: "text-neutral-400",
  },
  light: {
    button: "border-slate-200 text-slate-700 hover:bg-slate-50 hover:text-slate-900 dark:text-gray-100",
    chevron: "text-slate-400",
  },
} as const;

export default function LanguageSwitcher({ tone = "dark" }: { tone?: keyof typeof TONES }) {
  const { t, language, setLanguage } = useI18n();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const styles = TONES[tone];
  const current = LANGUAGES.find((l) => l.code === language) ?? LANGUAGES[0];

  // Open: focus the current language. Closed by a click outside or by focus
  // leaving the menu (Tab).
  useEffect(() => {
    if (!open) return;
    const selected = Math.max(0, LANGUAGES.findIndex((l) => l.code === language));
    optionRefs.current[selected]?.focus();
    const onPointer = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onFocus = (event: FocusEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("focusin", onFocus);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("focusin", onFocus);
    };
  }, [open, language]);

  const close = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };

  const choose = (code: Language) => {
    close();
    if (code === language) return;
    setLanguage(code);
    void rememberLanguageChoice(code);
  };

  // Arrow keys, Home and End move between the options; Escape closes.
  const onMenuKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const items = optionRefs.current.filter(Boolean) as HTMLButtonElement[];
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    const move: Record<string, number> = {
      ArrowDown: (at + 1) % items.length,
      ArrowUp: (at - 1 + items.length) % items.length,
      Home: 0,
      End: items.length - 1,
    };
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key in move) {
      event.preventDefault();
      items[move[event.key]]?.focus();
    }
  };

  return (
    <div className="relative" ref={rootRef}>
      <button
        aria-controls={open ? menuId : undefined}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={`${t("nav.selectLanguage")}: ${current.label}`}
        className={`inline-flex items-center gap-1.5 px-3 sm:px-4 py-2 rounded-md border transition-all text-[13px] font-medium tracking-wide focus:outline-none focus-visible:ring-2 focus-visible:ring-current cursor-pointer ${styles.button}`}
        data-purpose="language-select"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
          }
        }}
        ref={buttonRef}
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
          className="absolute right-0 top-full mt-2 w-40 bg-white dark:bg-gray-800 text-slate-800 rounded-md shadow-2xl py-1.5 border border-slate-100 flex flex-col text-[14px] z-50"
          aria-label={t("nav.selectLanguage")}
          data-purpose="language-menu"
          id={menuId}
          onKeyDown={onMenuKey}
          role="listbox"
        >
          {LANGUAGES.map((lang, index) => (
            <button
              aria-selected={language === lang.code}
              className={`text-left px-4 py-2 transition-colors cursor-pointer ${language === lang.code ? "bg-slate-100 text-black font-semibold" : "hover:bg-slate-100 hover:text-black"}`}
              data-purpose={`language-option-${lang.code}`}
              key={lang.code}
              lang={lang.code}
              onClick={() => choose(lang.code)}
              ref={(element) => {
                optionRefs.current[index] = element;
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

/** A choice made while signed out, waiting to be copied to the account at sign-in. */
const UNSYNCED_KEY = "endod_language_unsynced";

/**
 * Where a choice made in the switcher goes besides this device. Signed in,
 * the account (the source of truth on every device the patient signs in to);
 * signed out, kept until the next sign-in or sign-up copies it over.
 * Decided when the choice is made, not when the page rendered.
 */
export async function rememberLanguageChoice(language: Language): Promise<void> {
  const session = await fetchSession();
  if (session.status === "signed-in") {
    await saveToAccount(language);
    return;
  }
  try {
    window.localStorage.setItem(UNSYNCED_KEY, language);
  } catch {
    // Without storage the choice still applies on this device.
  }
}

/** After signing in or up: copy a choice made while signed out to the account. */
export async function syncLanguageAfterSignIn(): Promise<void> {
  let language: string | null = null;
  try {
    language = window.localStorage.getItem(UNSYNCED_KEY);
  } catch {
    return;
  }
  if (!isLanguage(language)) return;
  if (await saveToAccount(language)) {
    try {
      window.localStorage.removeItem(UNSYNCED_KEY);
    } catch {
      // Harmless: the next sign-in copies the same value again.
    }
  }
}

async function saveToAccount(language: Language): Promise<boolean> {
  try {
    const response = await fetch("/api/backend/users/me/preferences", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language }),
    });
    return response.ok;
  } catch {
    return false;
  }
}
