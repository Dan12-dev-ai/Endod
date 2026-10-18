"use client";

// Language preference for the whole app: English ("en") and Amharic ("am").
//
// The choice is kept in a cookie (readable by the inline script in the root
// layout) and mirrored into localStorage. Copy is read through
// `useI18n().t(key)`.
//
// Why client-side and not a [lang] route segment: the app has twelve fixed
// routes whose paths are hard-coded in links, bookmarks and Playwright specs,
// so a language prefix on every path would be a far larger and riskier change
// than this feature warrants. The trade-off is a one-frame switch of visible
// copy on a hard reload (never on client-side navigation, where the provider
// stays mounted); the inline script in the root layout sets <html lang> before
// the first paint, so assistive tech and :lang() styling are correct from the
// first byte.
//
// The stored choice is read with useSyncExternalStore rather than copied into
// state by an effect: it is an external store, so React gets the server
// snapshot ("en") for hydration and the real value straight after, with no
// cascading render and no hydration mismatch.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { DICTIONARIES, type Dictionary, type TranslationKey } from "./translations";

// Re-exported so callers import both the hook and the key type from one place.
export type { TranslationKey, Dictionary } from "./translations";

export type Language = "en" | "am";

export const DEFAULT_LANGUAGE: Language = "en";

export const LANGUAGES: { code: Language; label: string; englishLabel: string }[] = [
  { code: "en", label: "English", englishLabel: "English" },
  { code: "am", label: "አማርኛ", englishLabel: "Amharic" },
];

export const LANGUAGE_COOKIE = "endod_language";
export const LANGUAGE_STORAGE_KEY = "endod_language";

/** Fired on this tab when the choice changes (the `storage` event is cross-tab only). */
const LANGUAGE_EVENT = "endod:language-change";

/** Values interpolated into a translation: t("home.welcomeNamed", { name: "Abebe" }). */
export type TranslationValues = Record<string, string | number>;

export function isLanguage(value: unknown): value is Language {
  return value === "en" || value === "am";
}

/** Reads the language out of a raw cookie string. Null when unset or invalid. */
export function languageFromCookieString(cookieString: string | undefined | null): Language | null {
  if (!cookieString) return null;
  for (const part of cookieString.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === LANGUAGE_COOKIE) {
      const value = decodeURIComponent(rest.join("="));
      if (isLanguage(value)) return value;
    }
  }
  return null;
}

/**
 * The language to start with on the client: the cookie first, then
 * localStorage. Null when nothing has been chosen yet.
 */
export function readStoredLanguage(): Language | null {
  if (typeof window === "undefined") return null;
  const fromCookie = languageFromCookieString(document.cookie);
  if (fromCookie) return fromCookie;
  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return isLanguage(stored) ? stored : null;
  } catch {
    return null;
  }
}

// ===== The store useSyncExternalStore subscribes to =====
// getSnapshot returns a primitive, so a freshly computed equal value is still
// `Object.is`-equal and cannot loop.

function subscribeToLanguage(onStoreChange: () => void): () => void {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(LANGUAGE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(LANGUAGE_EVENT, onStoreChange);
  };
}

function getLanguageSnapshot(): Language {
  return readStoredLanguage() ?? DEFAULT_LANGUAGE;
}

function getServerLanguageSnapshot(): Language {
  return DEFAULT_LANGUAGE;
}

/** Persists the choice and wakes every subscriber on this tab. */
function persistLanguage(language: Language): void {
  // A year, site-wide, so the inline script sees it on the next hard load.
  document.cookie = `${LANGUAGE_COOKIE}=${language}; path=/; max-age=31536000; samesite=lax`;
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Not fatal: the cookie already carries the choice.
  }
  window.dispatchEvent(new Event(LANGUAGE_EVENT));
}

/** Replaces {placeholders} with their values; unknown ones are left as-is. */
function interpolate(template: string, values?: TranslationValues): string {
  if (!values) return template;
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : match,
  );
}

/** The translation function every component uses. */
export type Translate = (key: TranslationKey, values?: TranslationValues) => string;

type I18nValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  t: Translate;
  /** BCP-47 tag for Intl/date formatting. */
  locale: string;
};

const I18nContext = createContext<I18nValue | null>(null);

/**
 * The script the root layout inlines in <head>: it applies the stored choice to
 * <html lang> before the first paint. Kept here so the cookie name and the
 * script can never drift apart.
 */
export const LANGUAGE_INIT_SCRIPT = `(function(){try{var m=document.cookie.match(/(?:^|;\\s*)${LANGUAGE_COOKIE}=([^;]*)/);var v=m?decodeURIComponent(m[1]):null;if(v!=="en"&&v!=="am"){v=localStorage.getItem("${LANGUAGE_STORAGE_KEY}")}if(v==="am"||v==="en"){document.documentElement.lang=v;document.documentElement.setAttribute("data-language",v)}}catch(e){}})();`;

export function I18nProvider({ children }: { children: ReactNode }) {
  const language = useSyncExternalStore(
    subscribeToLanguage,
    getLanguageSnapshot,
    getServerLanguageSnapshot,
  );

  // Keep <html lang> in step with the choice (the inline script covers the
  // first paint; this covers changes made while the app is open).
  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.setAttribute("data-language", language);
  }, [language]);

  const setLanguage = useCallback((next: Language) => {
    persistLanguage(next);
  }, []);

  const t = useCallback<Translate>(
    (key, values) => {
      const dictionary: Dictionary = DICTIONARIES[language];
      const template = dictionary[key] ?? DICTIONARIES.en[key] ?? key;
      return interpolate(template, values);
    },
    [language],
  );

  const value = useMemo<I18nValue>(
    () => ({ language, setLanguage, t, locale: language === "am" ? "am-ET" : "en-US" }),
    [language, setLanguage, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

/** Copy, the current language and the setter. Throws outside the provider. */
export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside <I18nProvider>");
  return value;
}

/** Shorthand when only the translator is needed. */
export function useTranslation(): Translate {
  return useI18n().t;
}

/** A count-aware key: pick the _one/_other form the language needs. */
export function plural(
  t: Translate,
  keyOne: TranslationKey,
  keyOther: TranslationKey,
  count: number,
): string {
  return t(count === 1 ? keyOne : keyOther, { count });
}
