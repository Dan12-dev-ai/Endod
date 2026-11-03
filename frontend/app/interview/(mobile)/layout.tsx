"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import LanguageSwitcher from "../../components/language-switcher";
import { useI18n } from "../../lib/i18n";
import MobileBottomNav from "../mobile-nav";
import { MOBILE_SECTIONS, MobileToastProvider } from "../mobile-shell";

/**
 * The frame of every mobile section screen (/interview/mobile-*): a header with
 * the way back to the dashboard and the screen's title, the bottom bar on a
 * phone, a sidebar when the same link is opened on a wider screen.
 */
export default function MobileLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { t } = useI18n();
  const current = MOBILE_SECTIONS.find((s) => s.href === pathname);

  return (
    <MobileToastProvider closeLabel={t("common.close")}>
      <div className="min-h-screen md:h-screen md:overflow-hidden bg-gray-100 font-sans antialiased text-app-charcoal flex">
        <aside className="hidden md:flex sticky top-0 h-screen w-64 flex-col bg-app-green text-white p-4 gap-1">
          <div className="flex items-center gap-2 px-2 pb-3 mb-2 border-b border-white/15">
            <Link href="/interview" aria-label={t("nav.homeAria")} className="flex items-center gap-2 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-white">
              <Image alt={t("nav.logoAlt")} className="h-8 w-auto object-contain" src="/endod_logo.png" width={32} height={32} />
              <span className="text-lg font-black tracking-tight text-white">Endod</span>
            </Link>
          </div>
          <nav aria-label={t("interview.mobileNav")}>
            <ul className="space-y-1">
              {MOBILE_SECTIONS.map((s) => {
                const active = s.href === pathname;
                return (
                  <li key={s.id}>
                    <Link
                      href={s.href}
                      aria-current={active ? "page" : undefined}
                      className={`flex items-center gap-4 px-4 py-3 rounded-lg transition focus:outline-none focus-visible:ring-2 focus-visible:ring-white ${active ? "bg-white/20 font-bold" : "hover:bg-white/10"}`}
                    >
                      {s.icon}
                      <span className="text-base">{t(s.labelKey)}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        </aside>
        <main className="flex-1 md:h-screen md:overflow-y-auto w-full bg-white min-h-screen flex flex-col pb-20 md:pb-0">
          <header className="sticky top-0 z-30 bg-white px-3 py-2 flex items-center justify-between gap-2 border-b border-gray-100">
            <div className="flex items-center gap-1 min-w-0">
              <Link
                href="/interview"
                aria-label={t("common.back")}
                data-purpose="mobile-back"
                className="p-2 rounded-lg text-slate-700 hover:text-black hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-app-green"
              >
                <svg aria-hidden className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 12H5m0 0l7 7m-7-7l7-7" />
                </svg>
              </Link>
              {/* The screen's own <h1> (visually hidden in the views) names the page for screen readers. */}
              <p aria-hidden className="text-lg font-bold text-black truncate" data-purpose="mobile-title">
                {current ? t(current.titleKey) : ""}
              </p>
            </div>
            <div className="flex items-center gap-1">
              <LanguageSwitcher tone="light" />
              {current?.id === "appointment" && (
                <Link
                  href="/interview/mobile-booking"
                  aria-label={t("appointments.scheduleVisit")}
                  className="p-2 rounded-lg text-slate-700 hover:text-black hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-app-green"
                >
                  <svg aria-hidden className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                  </svg>
                </Link>
              )}
            </div>
          </header>

          <div className="flex-1 px-4 py-3">{children}</div>

          <MobileBottomNav />
        </main>
      </div>
    </MobileToastProvider>
  );
}
