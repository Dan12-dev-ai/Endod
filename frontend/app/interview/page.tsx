"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { healthCardFromProfile, type HealthCardInfo, type ProfileForCard } from "../health-card/health-card-data";
import LanguageSwitcher from "../components/language-switcher";
import AppointmentsView from "./appointments-view";
import BookingView from "./booking-view";
import HomeView from "./home-view";
import NotificationsView from "./notifications-view";
import HistoryView from "./history-view";
import type { BookingPreset } from "./history-data";
import SettingsView from "./settings-view";
import EmergencyPanel from "./emergency-panel";
import { api, logout } from "../lib/api";
import { Home, CalendarPlus, Calendar, FileText, Bell, Settings } from "lucide-react";
import { isLanguage, useI18n, type TranslationKey, LANGUAGES } from "../lib/i18n";
import { useTheme } from "../lib/theme";
import { rememberLanguageChoice } from "../components/language-switcher";

export default function Interview() {
  const { t, language, setLanguage } = useI18n();
  const { theme, setTheme } = useTheme();
  const setAccountLanguage = (saved: Parameters<typeof setLanguage>[0]) => {
    if (saved !== language) setLanguage(saved);
  };
  const [activeNav, setActiveNav] = useState("home");
  const restoredNavRef = useRef(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(true);
  const [emergencyOpen, setEmergencyOpen] = useState(false);
  const closeEmergency = useCallback(() => setEmergencyOpen(false), []);
  // Synchronously persist + reflect the active section in the URL/sessionStorage.
  // Using a helper (instead of an effect) guarantees the address bar updates the
  // moment a section is chosen, so refreshes never fall back to Home.
  const navigateTo = useCallback((nav: string) => {
    setActiveNav(nav);
    try {
      window.sessionStorage.setItem("dedan:interview:activeNav", nav);
    } catch {
      // ignore
    }
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("section", nav);
      window.history.replaceState({}, "", url);
    } catch {
      // ignore
    }
  }, []);
  // Restore the active section on first load (URL first, then sessionStorage).
  useEffect(() => {
    if (restoredNavRef.current) return;
    restoredNavRef.current = true;
    const section = new URLSearchParams(window.location.search).get("section");
    const valid = new Set(["home", "booking", "appointment", "followup", "message", "setting"]);
    let restored: string | null = null;
    if (section && valid.has(section)) restored = section;
    else {
      try {
        const saved = window.sessionStorage.getItem("dedan:interview:activeNav");
        if (saved && valid.has(saved)) restored = saved;
      } catch {
        // ignore
      }
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (restored) navigateTo(restored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Shared: which card/record a notification click should highlight on the target page
  const [highlightTarget, setHighlightTarget] = useState<string | null>(null);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  // "Book now" on a follow-up: booking opens at that hospital on that day.
  const [bookingPreset, setBookingPreset] = useState<BookingPreset | null>(null);
  const bookFollowUp = (preset: BookingPreset) => {
    setHighlightTarget(null);
    setBookingPreset(preset);
    navigateTo("booking");
  };

  const navItems: { id: string; labelKey: TranslationKey; icon: React.ReactNode }[] = [
    { id: "home", labelKey: "interview.nav.home", icon: <Home className="w-5 h-5" /> },
    { id: "booking", labelKey: "interview.nav.booking", icon: <CalendarPlus className="w-5 h-5" /> },
    { id: "appointment", labelKey: "interview.nav.appointment", icon: <Calendar className="w-5 h-5" /> },
    { id: "followup", labelKey: "interview.nav.medicalRecord", icon: <FileText className="w-5 h-5" /> },
    { id: "message", labelKey: "interview.nav.notification", icon: <Bell className="w-5 h-5" /> },
    { id: "setting", labelKey: "interview.nav.setting", icon: <Settings className="w-5 h-5" /> },
  ];

  // ===== Toast (any screen) =====
  const [toast, setToast] = useState<{ visible: boolean; title: string; message: string }>({
    visible: false,
    title: "",
    message: "",
  });
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = (title: string, message: string) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast({ visible: true, title, message });
    toastTimerRef.current = setTimeout(() => {
      setToast((prev) => ({ ...prev, visible: false }));
    }, 4000);
  };

  const dismissToast = () => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast((prev) => ({ ...prev, visible: false }));
  };

  // Digital Health Card data: the signed-in patient's profile, the same
  // source as the /health-card route.
  const [healthCard, setHealthCard] = useState<HealthCardInfo | null>(null);
  useEffect(() => {
    let cancelled = false;
    api<ProfileForCard & { preferences?: { language?: string } }>("users/me")
      .then((profile) => {
        if (cancelled) return;
        setHealthCard(healthCardFromProfile(profile));
        // Signed in, the account's language is the one to show: every choice
        // made in the switcher while signed in is saved there, on any device.
        const saved = profile.preferences?.language;
        if (isLanguage(saved)) setAccountLanguage(saved);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // Runs once, on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ===== Notification page state =====
  // A notification opens another screen and highlights its card there.
  const openNotifTarget = (nav: string, target: string | null) => {
    setHighlightTarget(target);
    navigateTo(nav);
  };

  // Reset notification state when navigating away
  const prevActiveNavRef4 = useRef(activeNav);
  useEffect(() => {
    // Clear the cross-page notification highlight once we land where it can't apply
    if (prevActiveNavRef4.current !== activeNav && activeNav !== "appointment" && activeNav !== "followup" && activeNav !== "message") {
      setHighlightTarget(null);
    }
    prevActiveNavRef4.current = activeNav;
  }, [activeNav]);

  useEffect(() => {
    if (mobileSidebarOpen) {
      document.body.classList.add("overflow-hidden");
    } else {
      document.body.classList.remove("overflow-hidden");
    }
  }, [mobileSidebarOpen]);

  useEffect(() => {
    const handleResize = () => {
      setMobileSidebarOpen(false);
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return (
    <div className="h-screen bg-[#F6F9FA] text-slate-800 font-sans antialiased flex flex-col overflow-hidden pb-16 lg:pb-0">
      {/* ===== Main Header ===== */}
      <header className="bg-white dark:bg-gray-800 border-b border-slate-200 px-4 sm:px-6 py-3 flex items-center justify-between sticky top-0 z-40">
        <div className="flex items-center space-x-3 sm:space-x-6">
          <button
            type="button"
            aria-label={t("interview.openMenu")}
            onClick={() => {
              if (typeof window !== "undefined" && window.innerWidth >= 1024) {
                setDesktopSidebarOpen((prev) => !prev);
              }
            }}
            className="flex items-center space-x-2.5 sm:space-x-3 focus:outline-none"
          >
            <img
              alt={t("nav.logoAlt")}
              className="h-12 sm:h-14 w-auto object-contain flex-shrink-0"
              src="/endod_logo.png"
            />
          </button>
        </div>
        <div className="flex items-center space-x-1.5 sm:space-x-3">
          <button
            aria-label={t("emergency.open")}
            className="inline-flex items-center gap-1.5 px-2.5 sm:px-3 py-2 rounded-md bg-red-600 hover:bg-red-700 text-white text-[13px] font-bold"
            data-purpose="emergency-button"
            onClick={() => setEmergencyOpen(true)}
            type="button"
          >
            <svg aria-hidden className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
              <path d="M6.6 10.8a15.1 15.1 0 006.6 6.6l2.2-2.2a1 1 0 011-.25 11.4 11.4 0 003.6.57 1 1 0 011 1V20a1 1 0 01-1 1A17 17 0 013 4a1 1 0 011-1h3.5a1 1 0 011 1 11.4 11.4 0 00.57 3.6 1 1 0 01-.25 1z" />
            </svg>
            <span className="hidden sm:inline">{t("emergency.button")}</span>
          </button>
          <LanguageSwitcher tone="light" />
          <div className="hidden lg:flex items-center space-x-2 pl-1 sm:pl-2 py-1">
            <div className="hidden lg:flex w-8 h-8 sm:w-9 sm:h-9 rounded-full bg-emerald-100 items-center justify-center text-emerald-700 flex-shrink-0">
              <svg className="w-4 h-4 sm:w-5 sm:h-5 text-emerald-700" fill="currentColor" viewBox="0 0 20 20">
                <path clipRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" fillRule="evenodd" />
              </svg>
            </div>
            <div className="text-left text-xs leading-tight hidden lg:block">
              <div className="font-bold text-slate-800 flex items-center">
                {healthCard?.fullName ?? ""}
                <svg className="w-3.5 h-3.5 text-slate-500 dark:text-gray-400 ml-0.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path d="M19 9l-7 7-7-7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div className="text-slate-500 dark:text-gray-400 text-[11px]">{t("interview.patient")}</div>
            </div>
          </div>
          <button
            type="button"
            data-purpose="sign-out"
            onClick={() => void logout()}
            className="whitespace-nowrap px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 dark:text-gray-100 border border-slate-200 hover:bg-slate-50 dark:hover:bg-gray-700 dark:hover:text-white rounded-lg transition"
          >
            {t("interview.signOut")}
          </button>
        </div>
      </header>

      {emergencyOpen && <EmergencyPanel onClose={closeEmergency} />}

{mobileSidebarOpen && (
        <div
          aria-hidden="true"
          className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-40 opacity-100 transition-opacity duration-300 lg:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* ===== Body Content ===== */}
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* ===== Sidebar ===== */}
<aside className={`hidden fixed inset-y-0 left-0 z-50 w-72 bg-white dark:bg-gray-800 border-r border-slate-200 transform transition-transform duration-300 ease-in-out flex-col justify-between p-4 flex-shrink-0 shadow-2xl ${mobileSidebarOpen ? "translate-x-0" : "-translate-x-full"} ${desktopSidebarOpen ? "lg:static lg:w-64 lg:translate-x-0 lg:flex lg:shadow-none" : "lg:hidden"}`}>
          <div className="flex items-center justify-between pb-3 mb-2 border-b border-slate-100 lg:hidden">
            <div className="flex items-center space-x-2.5">
              <div className="w-8 h-8 rounded-full bg-teal-500 flex items-center justify-center text-white shadow-sm">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2.2} viewBox="0 0 24 24">
                  <path d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div>
                <div className="flex items-baseline space-x-1 leading-none">
                  <span className="text-base font-black tracking-tight text-slate-900 dark:text-gray-100">ENDOD</span>
                  <span className="text-base font-bold text-teal-600">Health</span>
                </div>
                <span className="text-[10px] font-medium text-teal-700 block tracking-tight">{t("interview.yourAiDoctor")}</span>
              </div>
            </div>
<button aria-label={t("interview.closeMenu")} className="p-1.5 text-slate-500 dark:text-gray-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition" onClick={() => setMobileSidebarOpen(false)} type="button">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
          <nav className="space-y-1 overflow-hidden flex-1 min-h-0">
            {navItems.map((item) => {
              const isActive = activeNav === item.id;
              return (
                <a
                  key={item.id}
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    // Sidebar navigation never carries a notification highlight.
                    setHighlightTarget(null);
                    navigateTo(item.id);
                  }}
                  className="flex items-center space-x-3 px-3.5 py-2.5 rounded-xl text-slate-700 dark:text-gray-200 hover:text-black dark:hover:text-white hover:bg-slate-50 dark:hover:bg-gray-700 transition-colors text-sm font-medium cursor-pointer"
                >
                  {item.icon}
                  <span className={isActive ? "text-slate-900 dark:text-gray-100 font-semibold" : undefined}>{t(item.labelKey)}</span>
                </a>
              );
            })}
          </nav>
          <div className="mt-auto pt-4">
            <div className="p-4 rounded-2xl bg-[#E6F8F3] border border-teal-100 text-left relative">
              <div className="w-7 h-7 rounded-full bg-teal-100 text-teal-700 flex items-center justify-center mb-2.5">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <h4 className="text-xs font-bold text-slate-900 dark:text-gray-100 leading-snug">{t("interview.betterHealth")}</h4>
              <p className="text-[11px] text-slate-500 dark:text-gray-400 mt-1 leading-normal">{t("interview.betterHealthBody")}</p>
            </div>
          </div>
        </aside>

        {/* ===== Main Content Area ===== */}
        <main className="flex-1 min-h-0 flex flex-col overflow-hidden p-3 sm:p-4 md:p-6 gap-4 sm:gap-5">
          {/* ===== Booking View ===== */}
          {activeNav === "booking" && (
            <BookingView
              onPresetUsed={() => setBookingPreset(null)}
              onToast={showToast}
              patientId={healthCard?.userId ?? ""}
              preset={bookingPreset}
            />
          )}

          {/* ===== Settings View ===== */}
          {activeNav === "setting" && (
            <SettingsView onToast={showToast} onProfileChange={(profile) => setHealthCard(healthCardFromProfile(profile))} />
          )}

          {/* ===== Toast Notification (any screen) ===== */}
          {toast.title && (
            <div data-purpose="toast-notification" className={`fixed top-5 right-5 z-50 flex items-center gap-3 bg-black text-white px-5 py-3.5 rounded-xl shadow-xl border border-black ${toast.visible ? "toast-visible" : "toast-hidden"}`} role="alert">
              <div className="w-7 h-7 rounded-full bg-white/20 text-white flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} /></svg>
              </div>
              <div>
                <h5 className="text-xs font-semibold text-white tracking-wide uppercase">{toast.title}</h5>
                <p className="text-xs text-slate-300">{toast.message}</p>
              </div>
              <button type="button" aria-label={t("common.close")} onClick={dismissToast} className="ml-3 text-slate-500 dark:text-gray-400 hover:text-white text-sm focus:outline-none">×</button>
            </div>
          )}

          {/* ===== Appointment View ===== */}
          {activeNav === "appointment" && <AppointmentsView highlightTarget={highlightTarget} onToast={showToast} />}

          {/* ===== Medical Record View ===== */}
          {activeNav === "followup" && (
            <HistoryView
              highlightTarget={highlightTarget}
              onBook={bookFollowUp}
              onToast={showToast}
              onOpenSettings={() => {
                setHighlightTarget(null);
                navigateTo("setting");
              }}
              recordId={selectedRecordId ?? undefined}
              onBack={() => setSelectedRecordId(null)}
              onSelectRecord={setSelectedRecordId}
            />
          )}

          {/* ===== Notification View ===== */}
          {activeNav === "message" && <NotificationsView onOpen={openNotifTarget} onToast={showToast} />}

          {/* ===== Home ===== */}
          {activeNav === "home" && (
            <HomeView
              firstName={healthCard?.firstName ?? ""}
              onBook={bookFollowUp}
              onNavigate={(nav) => {
                setHighlightTarget(null);
                navigateTo(nav);
              }}
            />
          )}
        </main>
      </div>

      {/* ===== Mobile bottom bar: the same sections as the sidebar ===== */}
      <nav aria-label={t("interview.mobileNav")} className="fixed bottom-0 inset-x-0 z-30 bg-white/95 dark:bg-gray-800 backdrop-blur-md border-t border-slate-200 dark:border-gray-700 lg:hidden shadow-lg">
        <div className="flex items-stretch px-1 py-1.5" data-purpose="mobile-nav">
          {navItems.map((item) => {
            const isActive = activeNav === item.id;
            return (
              <button
                aria-current={isActive ? "page" : undefined}
                className={`flex-1 min-w-0 flex flex-col items-center justify-center py-1 px-0.5 rounded-lg transition-colors ${
                  isActive ? "text-black dark:text-white bg-gray-100 dark:bg-gray-700" : "text-slate-500 dark:text-gray-300 hover:text-black dark:hover:text-white hover:bg-slate-50 dark:hover:bg-gray-700"
                }`}
                data-purpose={`mobile-nav-${item.id}`}
                key={item.id}
                onClick={() => {
                  setHighlightTarget(null);
                  navigateTo(item.id);
                }}
                type="button"
              >
                {item.icon}
                <span className={`text-[10px] mt-1 w-full truncate text-center ${isActive ? "font-semibold" : "font-medium"}`}>
                  {t(item.labelKey)}
                </span>
              </button>
            );
          })}
        </div>
      </nav>

    </div>
  );
}
