"use client";

import Link from "next/link";
import LanguageSwitcher from "../../components/language-switcher";
import { usePathname, useRouter } from "next/navigation";
import { useI18n } from "../../lib/i18n";

const titleMap: Record<string, string> = {
  "/interview/card-mobile": "Card",
  "/interview/booking-mobile": "Booking",
  "/interview/appointment-mobile": "Appointment",
  "/interview/notification-mobile": "Notification",
  "/interview/setting-mobile": "Setting",
  "/interview/mobile-booking": "Book Appointment",
  "/interview/mobile-appointment": "My Appointments",
  "/interview/mobile-notification": "Notifications",
  "/interview/mobile-setting": "Settings",
  "/interview/mobile-card": "Health Card",
};

export default function MobileLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useI18n();
  const title = titleMap[pathname ?? ""] ?? "Card";
  const navRoutes = [
    "/interview/card-mobile",
    "/interview/booking-mobile",
    "/interview/appointment-mobile",
    "/interview/notification-mobile",
    "/interview/setting-mobile",
  ];
  const isContentPage = !navRoutes.includes(pathname ?? "");

  const navItems = [
    {
      label: t("mobile.nav.card"),
      href: "/interview/mobile-card",
      icon: <svg className="w-5 h-5 stroke-current" fill="none" viewBox="0 0 24 24"><rect x="2" y="5" width="20" height="14" rx="2" strokeWidth="2" /><path d="M2 10h20" strokeWidth="2" /></svg>,
    },
    {
      label: t("mobile.nav.booking"),
      href: "/interview/mobile-booking",
      icon: <svg className="w-5 h-5 stroke-current" fill="none" viewBox="0 0 24 24"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg>,
    },
    {
      label: t("mobile.nav.appointment"),
      href: "/interview/mobile-appointment",
      icon: <svg className="w-5 h-5 stroke-current" fill="none" viewBox="0 0 24 24"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg>,
    },
    {
      label: t("mobile.nav.notification"),
      href: "/interview/mobile-notification",
      icon: <svg className="w-5 h-5 stroke-current" fill="none" viewBox="0 0 24 24"><path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg>,
    },
    {
      label: t("mobile.nav.setting"),
      href: "/interview/mobile-setting",
      icon: <svg className="w-5 h-5 stroke-current" fill="none" viewBox="0 0 24 24"><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg>,
    },
  ];

  return (
    <div className="min-h-screen md:h-screen md:overflow-hidden bg-gray-100 font-sans antialiased text-app-charcoal flex">
      <aside className="hidden md:flex sticky top-0 h-screen w-64 flex-col bg-app-green text-white p-4 pt-4 gap-3">
        <div className="flex items-center gap-2 px-2 pb-3 mb-1 border-b border-white/15">
          <Link href="/" aria-label={t("nav.homeAria")} className="flex items-center gap-2">
            <img alt={t("nav.logoAlt")} className="h-8 w-auto object-contain" src="/endod_logo.png" />
            <span className="text-lg font-black tracking-tight text-white">Endod</span>
          </Link>
        </div>
        {navItems.map((item) => (
          <Link
            key={item.label}
            href={item.href}
            className={`flex items-center gap-4 px-4 py-3 rounded-lg transition ${item.href === pathname ? "bg-white/20 font-bold" : "hover:bg-white/10"}`}
          >
            <span className="w-6 h-6 [&>svg]:w-6 [&>svg]:h-6">{item.icon}</span>
            <span className="text-base">{item.label}</span>
          </Link>
        ))}
      </aside>
      <main className="flex-1 md:h-screen md:overflow-y-auto w-full bg-white min-h-screen flex flex-col">
        {isContentPage ? (
          <section className="sticky top-0 z-50 bg-white px-5 py-3 flex items-center justify-between gap-3 border-b border-gray-100">
            <div className="flex items-center gap-3">
              <Link href="/interview" aria-label="Back" className="text-slate-700 hover:text-black">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 12H5m0 0l7 7m-7-7l7-7" />
                </svg>
              </Link>
              <h1 className="text-lg font-bold text-black">{title}</h1>
            </div>
            <div className="flex items-center gap-2">
              <LanguageSwitcher tone="light" />
              {pathname === "/interview/mobile-appointment" && (
              <button type="button" aria-label="Add" onClick={() => router.push("/interview/mobile-booking")} className="text-slate-700 hover:text-black">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
              </button>
            )}
            </div>
          </section>
        ) : (
          <>
            <section className="bg-white px-5 py-2.5 flex justify-between items-center z-20 border-b border-gray-100">
              <div className="flex items-center space-x-1.5">
                <div className="relative w-8 h-8 flex items-center justify-center">
                  <span className="absolute w-7 h-7 rounded-full border-2 border-emerald-500 border-t-transparent -rotate-45" />
                  <span className="w-4 h-4 bg-sky-500 rounded-full opacity-80" />
                </div>
                <div className="leading-tight">
                  <span className="block text-sm font-black tracking-tight text-slate-800">ethio telecom<span className="text-[9px] align-super">™</span></span>
                  <span className="block text-[9px] text-slate-500 font-medium -mt-0.5">ኢትዮ ቴሌኮም</span>
                </div>
              </div>
              <div className="flex items-center space-x-1">
                <svg className="w-6 h-6 text-app-action-blue" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15h-2v-6h2v6zm4 0h-2v-4h2v4zm-2-8a1.5 1.5 0 110-3 1.5 1.5 0 010 3z" />
                </svg>
                <div className="text-right leading-none">
                  <span className="text-[10px] text-app-action-blue font-bold block">ቴሌብር</span>
                  <span className="text-sm font-extrabold text-app-action-blue">telebirr</span>
                </div>
              </div>
            </section>

            <section
              className="relative pt-3 px-5 text-white overflow-hidden shadow-sm pb-4"
              style={{
                backgroundImage: `radial-gradient(circle at 50% -20%, rgba(255,255,255,0.22) 0%, transparent 45%), radial-gradient(circle at 50% -20%, rgba(255,255,255,0.15) 50%, transparent 70%), repeating-radial-gradient(circle at 50% -10%, transparent 0, transparent 18px, rgba(255,255,255,0.08) 19px, rgba(255,255,255,0.08) 20px), linear-gradient(to bottom, #70C13B, #85CE53)`,
              }}
            >
              <div className="flex justify-between items-center mb-2.5">
                <div>
                  <p className="text-sm font-semibold tracking-wide text-white drop-shadow-sm">{title}</p>
                </div>
                <div className="flex items-center gap-2">
                  <LanguageSwitcher tone="dark" />
                  <Link href="/interview" className="text-white/90 hover:text-white text-xs font-medium">Back</Link>
                </div>
              </div>
              <div className="amber-wave-divider">
                <svg className="w-full h-3.5 fill-[#F39C12]" preserveAspectRatio="none" viewBox="0 0 500 24">
                  <path d="M0,0 C150,22 350,22 500,0 L500,24 L0,24 Z" />
                </svg>
              </div>
            </section>
          </>
        )}

        <div className={`flex-1 px-4 ${isContentPage ? "py-2" : "py-10"}`}>
          {children}
        </div>

        <nav className="md:hidden sticky bottom-0 inset-x-0 bg-app-green border-t border-white/20 shadow-nav px-3 py-2 flex justify-around items-center z-40">
          {navItems.map((item) => (
            <Link
              key={item.label}
              href={item.href}
              className={`flex flex-col items-center space-y-1 focus:outline-none flex-1 ${item.href === pathname ? "text-white" : "text-white/90 hover:text-white"}`}
            >
              {item.icon}
              <span className={`text-[10px] font-medium ${item.href === pathname ? "font-bold" : ""}`}>{item.label}</span>
            </Link>
          ))}
        </nav>
      </main>
    </div>
  );
}
