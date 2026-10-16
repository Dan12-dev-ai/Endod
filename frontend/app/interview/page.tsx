"use client";

import { useEffect, useRef, useState } from "react";
import { healthCardFromProfile, loadHealthCard, type HealthCardInfo } from "../health-card/health-card-data";
import AppointmentsView from "./appointments-view";
import BookingView from "./booking-view";
import NotificationsView from "./notifications-view";
import RecordsView from "./records-view";
import SettingsView from "./settings-view";
import { logout } from "../lib/api";

export default function Interview() {
  const [toggles, setToggles] = useState({ mic: false, camera: false, speaker: false, pause: false });

  const toggle = (key: "mic" | "camera" | "speaker" | "pause") =>
    setToggles((prev) => ({ ...prev, [key]: !prev[key] }));

  const [activeNav, setActiveNav] = useState("live");
  const [liveStarted, setLiveStarted] = useState(false);
  // Shared: which card/record a notification click should highlight on the target page
  const [highlightTarget, setHighlightTarget] = useState<string | null>(null);

  const navItems = [
    { id: "home", label: "Home", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "live", label: "Live Discussion", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "booking", label: "Booking", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M12 4v16m8-8H4" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "appointment", label: "Appointment", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "followup", label: "Medical Record", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "message", label: "Notification", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "setting", label: "Setting", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" strokeLinecap="round" strokeLinejoin="round" /><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
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
    loadHealthCard()
      .then((hc) => {
        if (!cancelled) setHealthCard(hc);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // ===== Notification page state =====
  // A notification opens another screen and highlights its card there.
  const openNotifTarget = (nav: string, target: string | null) => {
    setHighlightTarget(target);
    setActiveNav(nav);
  };

  // Reset notification state when navigating away
  const prevActiveNavRef4 = useRef(activeNav);
  useEffect(() => {
    if (prevActiveNavRef4.current !== activeNav && activeNav !== "live") {
      setLiveStarted(false);
    }
    // Clear the cross-page notification highlight once we land where it can't apply
    if (prevActiveNavRef4.current !== activeNav && activeNav !== "appointment" && activeNav !== "followup" && activeNav !== "message") {
      setHighlightTarget(null);
    }
    prevActiveNavRef4.current = activeNav;
  }, [activeNav]);

  // ===== Refs for DOM interactions (drawer & fullscreen) =====
  const mobileMenuBtnRef = useRef<HTMLButtonElement>(null);
  const drawerCloseBtnRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const videoStageRef = useRef<HTMLElement>(null);
  const fullscreenBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // --- Responsive drawer: open/close mobile sidebar ---
    const mobileMenuBtn = mobileMenuBtnRef.current;
    const drawerCloseBtn = drawerCloseBtnRef.current;
    const sidebar = sidebarRef.current;
    const backdrop = backdropRef.current;

    function openDrawer() {
      if (!sidebar || !backdrop) return;
      sidebar.classList.remove("-translate-x-full");
      sidebar.classList.add("translate-x-0");
      backdrop.classList.remove("hidden");
      setTimeout(() => {
        backdrop.classList.remove("opacity-0");
        backdrop.classList.add("opacity-100");
      }, 10);
      document.body.classList.add("overflow-hidden");
    }

    function closeDrawer() {
      if (!sidebar || !backdrop) return;
      sidebar.classList.remove("translate-x-0");
      sidebar.classList.add("-translate-x-full");
      backdrop.classList.remove("opacity-100");
      backdrop.classList.add("opacity-0");
      setTimeout(() => {
        backdrop.classList.add("hidden");
      }, 300);
      document.body.classList.remove("overflow-hidden");
    }

    if (mobileMenuBtn) mobileMenuBtn.addEventListener("click", openDrawer);
    if (drawerCloseBtn) drawerCloseBtn.addEventListener("click", closeDrawer);
    if (backdrop) backdrop.addEventListener("click", closeDrawer);

    const handleResize = () => {
      if (window.innerWidth >= 1024) closeDrawer();
    };
    window.addEventListener("resize", handleResize);

    // --- Fullscreen toggle for video stage ---
    const stage = videoStageRef.current;
    const btn = fullscreenBtnRef.current;
    if (stage && btn) {
      const stageEl = stage;
      const btnEl = btn;
      const pathEl = btnEl.querySelector("path");
      const expandPath = "M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4";
      const collapsePath = "M9 9V4.5M9 9H4.5M9 9 3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5 5.25 5.25";

      function setIcon(isFs: boolean) {
        if (pathEl) pathEl.setAttribute("d", isFs ? collapsePath : expandPath);
        btnEl.title = isFs ? "Exit fullscreen" : "Toggle fullscreen";
      }

      function enter() {
        let p: Promise<unknown> | null = null;
        const stageWithWebkit = stageEl as HTMLElement & {
          webkitRequestFullscreen?: () => Promise<unknown>;
        };
        if (stageEl.requestFullscreen) p = stageEl.requestFullscreen();
        else if (stageWithWebkit.webkitRequestFullscreen) p = stageWithWebkit.webkitRequestFullscreen();
        if (p && p.catch) p.catch(function () {});
      }

      function exit() {
        let p: Promise<unknown> | null = null;
        const docWithWebkit = document as Document & {
          webkitExitFullscreen?: () => Promise<unknown>;
        };
        if (document.exitFullscreen) p = document.exitFullscreen();
        else if (docWithWebkit.webkitExitFullscreen) p = docWithWebkit.webkitExitFullscreen();
        if (p && p.catch) p.catch(function () {});
      }

      btnEl.addEventListener("click", function () {
        const docWithWebkit = document as Document & {
          webkitFullscreenElement?: Element | null;
          webkitExitFullscreen?: () => Promise<unknown>;
        };
        const fsEl = document.fullscreenElement || docWithWebkit.webkitFullscreenElement;
        if (!fsEl) enter();
        else exit();
      });

      document.addEventListener("fullscreenchange", function () {
        setIcon(!!document.fullscreenElement);
      });
      document.addEventListener("webkitfullscreenchange", function () {
        const docWithWebkit = document as Document & {
          webkitFullscreenElement?: Element | null;
        };
        setIcon(!!docWithWebkit.webkitFullscreenElement);
      });
    }

    return () => {
      if (mobileMenuBtn) mobileMenuBtn.removeEventListener("click", openDrawer);
      if (drawerCloseBtn) drawerCloseBtn.removeEventListener("click", closeDrawer);
      if (backdrop) backdrop.removeEventListener("click", closeDrawer);
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  return (
    <div className="h-screen bg-[#F6F9FA] text-slate-800 font-sans antialiased flex flex-col overflow-hidden pb-16 lg:pb-0">
      {/* ===== Main Header ===== */}
      <header className="bg-white border-b border-slate-200 px-4 sm:px-6 py-3 flex items-center justify-between sticky top-0 z-40">
        <div className="flex items-center space-x-3 sm:space-x-6">
          <button
            aria-label="Open navigation menu"
            className="lg:hidden p-2 -ml-1 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors focus:outline-none"
            ref={mobileMenuBtnRef}
            type="button"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <div className="flex items-center space-x-2.5 sm:space-x-3">
            <img
              alt="ENDOD Health logo"
              className="h-12 sm:h-14 w-auto object-contain flex-shrink-0"
              src="/endod_logo.png"
            />
          </div>
        </div>
        <div className="flex items-center space-x-1.5 sm:space-x-3">
          <div className="flex items-center space-x-2 pl-1 sm:pl-2 py-1">
            <div className="w-8 h-8 sm:w-9 sm:h-9 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-700 flex-shrink-0">
              <svg className="w-4 h-4 sm:w-5 sm:h-5 text-emerald-700" fill="currentColor" viewBox="0 0 20 20">
                <path clipRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" fillRule="evenodd" />
              </svg>
            </div>
            <div className="text-left text-xs leading-tight hidden xs:block sm:block">
              <div className="font-bold text-slate-800 flex items-center">
                {healthCard?.fullName ?? ""}
                <svg className="w-3.5 h-3.5 text-slate-500 ml-0.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path d="M19 9l-7 7-7-7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div className="text-slate-400 text-[11px]">Patient</div>
            </div>
          </div>
          <button
            type="button"
            data-purpose="sign-out"
            onClick={() => void logout()}
            className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 border border-slate-200 hover:bg-slate-50 rounded-lg transition"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* ===== Drawer Backdrop ===== */}
      <div aria-hidden="true" className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-40 hidden opacity-0 transition-opacity duration-300 lg:hidden" ref={backdropRef}></div>

      {/* ===== Body Content ===== */}
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* ===== Sidebar ===== */}
        <aside ref={sidebarRef} className="fixed inset-y-0 left-0 z-50 w-72 bg-white border-r border-slate-200 transform -translate-x-full transition-transform duration-300 ease-in-out flex flex-col justify-between p-4 flex-shrink-0 lg:static lg:w-64 lg:translate-x-0 lg:flex shadow-2xl lg:shadow-none">
          <div className="flex items-center justify-between pb-3 mb-2 border-b border-slate-100 lg:hidden">
            <div className="flex items-center space-x-2.5">
              <div className="w-8 h-8 rounded-full bg-teal-500 flex items-center justify-center text-white shadow-sm">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2.2} viewBox="0 0 24 24">
                  <path d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div>
                <div className="flex items-baseline space-x-1 leading-none">
                  <span className="text-base font-black tracking-tight text-slate-900">ENDOD</span>
                  <span className="text-base font-bold text-teal-600">Health</span>
                </div>
                <span className="text-[10px] font-medium text-teal-700 block tracking-tight">Your AI Doctor</span>
              </div>
            </div>
            <button ref={drawerCloseBtnRef} aria-label="Close navigation menu" className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition" type="button">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
          <nav className="space-y-1 overflow-y-auto flex-1 min-h-0">
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
                    setActiveNav(item.id);
                  }}
                  className="flex items-center space-x-3 px-3.5 py-2.5 rounded-xl text-slate-600 hover:text-slate-900 hover:bg-slate-50 transition-colors text-sm font-medium cursor-pointer"
                >
                  {item.icon}
                  <span className={isActive ? "text-slate-900 font-semibold" : undefined}>{item.label}</span>
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
              <h4 className="text-xs font-bold text-slate-900 leading-snug">Better Health Through AI</h4>
              <p className="text-[11px] text-slate-500 mt-1 leading-normal">Your health journey, our priority.</p>
            </div>
          </div>
        </aside>

        {/* ===== Main Content Area ===== */}
        <main className="flex-1 min-h-0 flex flex-col overflow-hidden p-3 sm:p-4 md:p-6 gap-4 sm:gap-5">
          {/* ===== Booking View ===== */}
          {activeNav === "booking" && <BookingView patientId={healthCard?.userId ?? ""} onToast={showToast} />}

          {/* ===== Settings View ===== */}
          {activeNav === "setting" && (
            <SettingsView onToast={showToast} onProfileChange={(profile) => setHealthCard(healthCardFromProfile(profile))} />
          )}

          {/* ===== Toast Notification (any screen) ===== */}
          {toast.title && (
            <div data-purpose="toast-notification" className={`fixed top-5 right-5 z-50 flex items-center gap-3 bg-slate-900 text-white px-5 py-3.5 rounded-xl shadow-xl border border-slate-700 ${toast.visible ? "toast-visible" : "toast-hidden"}`} role="alert">
              <div className="w-7 h-7 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} /></svg>
              </div>
              <div>
                <h5 className="text-xs font-semibold text-white tracking-wide uppercase">{toast.title}</h5>
                <p className="text-xs text-slate-300">{toast.message}</p>
              </div>
              <button type="button" aria-label="Close Notification" onClick={dismissToast} className="ml-3 text-slate-400 hover:text-white text-sm focus:outline-none">×</button>
            </div>
          )}

          {/* ===== Appointment View ===== */}
          {activeNav === "appointment" && <AppointmentsView highlightTarget={highlightTarget} onToast={showToast} />}

          {/* ===== Medical Record View ===== */}
          {activeNav === "followup" && (
            <RecordsView
              highlightTarget={highlightTarget}
              onToast={showToast}
              onOpenSettings={() => {
                setHighlightTarget(null);
                setActiveNav("setting");
              }}
            />
          )}

          {/* ===== Notification View ===== */}
          {activeNav === "message" && <NotificationsView onOpen={openNotifTarget} onToast={showToast} />}

          {activeNav !== "booking" && activeNav !== "setting" && activeNav !== "appointment" && activeNav !== "followup" && activeNav !== "message" && (
          <>
          {!liveStarted ? (
            /* ===== Start Screen ===== */
            <div data-purpose="live-start-screen" className="flex-1 min-h-0 flex flex-col items-center justify-center bg-[#F6F9FA] rounded-2xl p-8">
              <div className="text-center max-w-md">
                <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-emerald-100 flex items-center justify-center">
                  <svg className="w-10 h-10 text-emerald-600" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
                    <path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <h2 className="text-2xl font-bold text-slate-900 mb-2">Live Consultation</h2>
                <p className="text-sm text-slate-500 mb-8">Connect with ENDOD AI for real-time medical consultation, symptom analysis, and health guidance.</p>
                <button
                  type="button"
                  data-purpose="start-live-btn"
                  onClick={() => setLiveStarted(true)}
                  className="inline-flex items-center space-x-2 px-8 py-3.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-sm rounded-full shadow-md transition"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" strokeLinecap="round" strokeLinejoin="round" />
                    <path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span>Start Live Discussion</span>
                </button>
              </div>
            </div>
          ) : (
          <>
          {/* ===== Center Video Stage ===== */}

          <section ref={videoStageRef} className="relative flex-1 min-h-0 w-full rounded-2xl overflow-hidden border border-slate-200 bg-white flex items-center justify-center text-slate-400" data-purpose="video-consultation-stage">

            {/* AI Speaking Sound Wave Signal */}
            <div className={`${toggles.pause ? "paused" : "speaking"} absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20 flex items-center justify-center`} id="vocalVisualizer">
              <div className="relative flex items-center justify-center">
                {/* soft signal glow */}
                <span aria-hidden="true" className="absolute -inset-10 rounded-full bg-cyan-400/10 blur-3xl"></span>
                <div className="relative flex items-center justify-center gap-[3px] sm:gap-1 h-20 sm:h-24" id="vocalBarsContainer">
                  {Array.from({ length: 33 }).map((_, i) => {
                    const envelope = Math.sin((i / 32) * Math.PI);
                    const height = Math.max(8, Math.round(8 + envelope * 72));
                    return (
                      <span
                        key={i}
                        className="wave-bar w-[3px] sm:w-1 rounded-full bg-gradient-to-t from-teal-500 via-cyan-400 to-emerald-300 shadow-[0_0_6px_rgba(34,211,238,0.35)]"
                        style={{ height: `${height}px`, animationDelay: `${(i * 0.045).toFixed(3)}s` }}
                      ></span>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Top-right: HD quality + Fullscreen (zoom) */}
            <div className="absolute top-3 sm:top-4 right-3 sm:right-4 flex items-center space-x-1.5 sm:space-x-2">
              <span className="bg-slate-100 text-slate-700 text-[10px] sm:text-[11px] font-bold px-1.5 sm:px-2 py-0.5 sm:py-1 rounded">HD</span>
              <button ref={fullscreenBtnRef} className="bg-slate-100 p-1.5 rounded text-slate-600 hover:text-emerald-600 transition" title="Toggle fullscreen" type="button">
                <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          </section>

          {/* ===== Call Control Bar ===== */}
          <section className="flex-shrink-0 bg-white border border-slate-200 text-slate-800 rounded-2xl py-3 px-4 sm:px-6 shadow-md flex items-center justify-between" data-purpose="call-controls">
            <div className="flex items-center space-x-3 sm:space-x-6 mx-auto md:mx-0">
              {/* Mic */}
              <button type="button" aria-pressed={toggles.mic} onClick={() => toggle("mic")} className="flex flex-col items-center group">
                <div className={`w-9 h-9 sm:w-10 sm:h-10 rounded-full flex items-center justify-center transition ${toggles.mic ? "bg-emerald-500 text-white" : "bg-slate-100 text-slate-600 group-hover:bg-slate-200"}`}>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <span className={`text-[10px] sm:text-[11px] mt-1 ${toggles.mic ? "text-emerald-600" : "text-slate-500"}`}>Mic</span>
              </button>
              {/* Speaker */}
              <button type="button" aria-pressed={toggles.speaker} onClick={() => toggle("speaker")} className="flex flex-col items-center group">
                <div className={`w-9 h-9 sm:w-10 sm:h-10 rounded-full flex items-center justify-center transition ${toggles.speaker ? "bg-emerald-500 text-white" : "bg-slate-100 text-slate-600 group-hover:bg-slate-200"}`}>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <span className={`text-[10px] sm:text-[11px] mt-1 ${toggles.speaker ? "text-emerald-600" : "text-slate-500"}`}>Speaker</span>
              </button>
              {/* Pause */}
              <button type="button" aria-pressed={toggles.pause} onClick={() => toggle("pause")} className="flex flex-col items-center group">
                <div className={`w-9 h-9 sm:w-10 sm:h-10 rounded-full flex items-center justify-center transition ${toggles.pause ? "bg-emerald-500 text-white" : "bg-slate-100 text-slate-600 group-hover:bg-slate-200"}`}>
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M6 4h4v16H6zM14 4h4v16h-4z" />
                  </svg>
                </div>
                <span className={`text-[10px] sm:text-[11px] mt-1 ${toggles.pause ? "text-emerald-600" : "text-slate-500"}`}>Pause</span>
              </button>
            </div>
            <button className="flex items-center space-x-2 bg-[#D92D20] hover:bg-red-700 text-white font-semibold px-4 sm:px-6 py-2.5 rounded-full transition shadow-md">
              <svg className="w-4 h-4 transform rotate-[135deg]" fill="currentColor" viewBox="0 0 20 20">
                <path d="M2 3a1 1 0 011-1h2.153a1 1 0 01.986.836l.74 4.435a1 1 0 01-.54 1.06l-1.548.773a11.037 11.037 0 006.105 6.105l.774-1.548a1 1 0 011.059-.54l4.435.74a1 1 0 01.836.986V17a1 1 0 01-1 1h-2C7.82 18 2 12.18 2 4V3z" />
              </svg>
              <span className="text-xs hidden sm:inline">End Consultation</span>
              <span className="text-xs sm:hidden">End</span>
            </button>
          </section>
          </>
          )}
          </>
          )}
        </main>
      </div>

      {/* ===== Mobile Quick-Nav Bottom Bar (Full Menu, Scrollable) ===== */}
      <nav aria-label="Mobile Navigation" className="fixed bottom-0 inset-x-0 z-30 bg-white/95 backdrop-blur-md border-t border-slate-200 lg:hidden shadow-lg">
        <div className="flex items-center justify-around gap-1 overflow-x-auto px-3 py-2 whitespace-nowrap [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <a className="flex flex-col items-center justify-center text-slate-500 hover:text-slate-800 transition py-0.5 px-3 rounded-lg flex-1 min-w-[64px]" href="#">
            <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
              <path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-[10px] font-medium mt-1">Home</span>
          </a>
          <a className="flex flex-col items-center justify-center text-teal-700 font-semibold py-0.5 px-3 rounded-lg flex-1 min-w-[64px]" href="#">
            <div className="w-6 h-6 rounded-md bg-teal-600 text-white flex items-center justify-center shadow-xs">
              <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                <path d="M2 6a2 2 0 012-2h6a2 2 0 012 2v8a2 2 0 01-2 2H4a2 2 0 01-2-2V6zM14.553 7.106A1 1 0 0014 8v4a1 1 0 00.553.894l2 1A1 1 0 0018 13V7a1 1 0 00-1.447-.894l-2 1z" />
              </svg>
            </div>
            <span className="text-[10px] text-teal-800 mt-0.5">Live</span>
          </a>
          <a className="flex flex-col items-center justify-center text-slate-500 hover:text-slate-800 transition py-0.5 px-3 rounded-lg flex-1 min-w-[64px]" href="#">
            <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
              <path d="M12 4v16m8-8H4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-[10px] font-medium mt-1">Booking</span>
          </a>
          <a className="flex flex-col items-center justify-center text-slate-500 hover:text-slate-800 transition py-0.5 px-3 rounded-lg flex-1 min-w-[64px]" href="#">
            <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
              <path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-[10px] font-medium mt-1">Appointment</span>
          </a>
          <a className="flex flex-col items-center justify-center text-slate-500 hover:text-slate-800 transition py-0.5 px-3 rounded-lg flex-1 min-w-[64px]" href="#">
            <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
              <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-[10px] font-medium mt-1">Medical Record</span>
          </a>
          <a className="flex flex-col items-center justify-center text-slate-500 hover:text-slate-800 transition py-0.5 px-3 rounded-lg flex-1 min-w-[64px]" href="#">
            <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
              <path d="M8 10h.01M12 10h.01M16 10h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-[10px] font-medium mt-1">Notification</span>
          </a>
          <a className="flex flex-col items-center justify-center text-slate-500 hover:text-slate-800 transition py-0.5 px-3 rounded-lg flex-1 min-w-[64px]" href="#">
            <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
              <path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-[10px] font-medium mt-1">Setting</span>
          </a>
        </div>
      </nav>

    </div>
  );
}
