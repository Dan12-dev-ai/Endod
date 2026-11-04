"use client";

import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import EmergencyPanel from "./emergency-panel";
import LanguageSwitcher from "../components/language-switcher";
import { api, logout } from "../lib/api";
import { isLanguage, useI18n } from "../lib/i18n";
import MobileBottomNav from "./mobile-nav";
import { MOBILE_SECTIONS } from "./mobile-shell";

/** The phone's start screen at /interview: big tiles for every section, and Emergency. */
export default function MobileHome() {
  const { t, language, setLanguage } = useI18n();
  const [emergencyOpen, setEmergencyOpen] = useState(false);
  const closeEmergency = useCallback(() => setEmergencyOpen(false), []);
  const [firstName, setFirstName] = useState("");

  useEffect(() => {
    let cancelled = false;
    api<{ first_name?: string; preferences?: { language?: string } }>("users/me")
      .then((profile) => {
        if (cancelled) return;
        if (profile.first_name) setFirstName(profile.first_name);
        // Signed in, the account's language is the one to show (as on desktop).
        const saved = profile.preferences?.language;
        if (isLanguage(saved) && saved !== language) setLanguage(saved);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // Runs once, on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen bg-white font-sans antialiased text-app-charcoal flex flex-col pb-20" data-purpose="mobile-home">
      <header className="px-5 py-2.5 flex justify-between items-center border-b border-[#DCE4E6]">
        <Link href="/" aria-label={t("nav.homeAria")} className="flex items-center gap-2 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-app-green">
          <Image alt={t("nav.logoAlt")} className="h-8 w-auto object-contain" src="/endod_logo.png" width={32} height={32} />
          <span className="text-lg font-black tracking-tight text-[#25343D]">Endod</span>
        </Link>
        <button
          type="button"
          data-purpose="sign-out"
          onClick={() => void logout()}
          className="px-3 py-1.5 text-xs font-medium text-[#25343D] border border-[#DCE4E6] rounded-lg hover:bg-[#F4F7F7] focus:outline-none focus-visible:ring-2 focus-visible:ring-app-green"
        >
          {t("interview.signOut")}
        </button>
      </header>

      <section
        className="relative pt-3 px-5 text-white shadow-sm pb-5"
        style={{
          backgroundImage: `radial-gradient(circle at 50% -20%, rgba(255,255,255,0.22) 0%, transparent 45%), radial-gradient(circle at 50% -20%, rgba(255,255,255,0.15) 50%, transparent 70%), repeating-radial-gradient(circle at 50% -10%, transparent 0, transparent 18px, rgba(255,255,255,0.08) 19px, rgba(255,255,255,0.08) 20px), linear-gradient(to bottom, #176B65, #72AFA5)`,
        }}
      >
        <div className="flex justify-between items-center gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <svg
              aria-hidden
              className="w-5 h-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
            <h1 className="text-base font-semibold tracking-wide text-white drop-shadow-sm truncate" data-purpose="mobile-greeting">
              {firstName ? t("mobile.dashboard.greeting", { name: firstName }) : t("mobile.dashboard.greetingNoName")}
            </h1>
          </div>
          <LanguageSwitcher tone="mobile" />
        </div>
        <div className="amber-wave-divider" aria-hidden>
          <svg className="w-full h-3.5 fill-[#F39C12]" preserveAspectRatio="none" viewBox="0 0 500 24">
            <path d="M0,0 C150,22 350,22 500,0 L500,24 L0,24 Z" />
          </svg>
        </div>
      </section>

      <nav aria-label={t("mobile.dashboard.servicesLabel")} className="px-4 pt-5 pb-3">
        <ul className="grid grid-cols-2 gap-4">
          {MOBILE_SECTIONS.map((s) => (
            <li key={s.id}>
              <Link
                href={s.href}
                data-purpose={`mobile-tile-${s.id}`}
                className="bg-white rounded-2xl p-4 flex flex-col items-center justify-center text-center border border-[#DCE4E6] active:scale-95 transition min-h-[110px] focus:outline-none focus-visible:ring-2 focus-visible:ring-app-green"
              >
                <span className="w-14 h-14 rounded-2xl text-app-green flex items-center justify-center mb-2 [&>svg]:w-7 [&>svg]:h-7">{s.icon}</span>
                <span className="text-base font-semibold text-app-charcoal leading-tight">{t(s.labelKey)}</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <div className="px-4 pb-6 pt-2">
        <button
          type="button"
          data-purpose="emergency-button"
          onClick={() => setEmergencyOpen(true)}
          className="w-full flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 text-white font-bold py-3.5 px-4 rounded-2xl shadow-card active:scale-95 transition text-base focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-red-600"
        >
          <svg aria-hidden className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" />
          </svg>
          <span>{t("emergency.button")}</span>
        </button>
      </div>

      <MobileBottomNav />
      {emergencyOpen && <EmergencyPanel onClose={closeEmergency} />}
    </div>
  );
}
