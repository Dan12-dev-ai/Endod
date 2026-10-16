"use client";

import { useEffect, useRef, useState } from "react";
import { loadHealthCard, type HealthCardInfo } from "../health-card/health-card-data";
import AppointmentsView from "./appointments-view";
import BookingView from "./booking-view";
import NotificationsView from "./notifications-view";
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

  // ===== Settings page state =====
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

  // Profile form
  const [firstName, setFirstName] = useState("Daniel");
  const [lastName, setLastName] = useState("Everett");
  const [email, setEmail] = useState("daniel.everett@healthmail.com");
  const [phone, setPhone] = useState("+1 (617) 555-0198");

  // Location form
  const [address, setAddress] = useState("742 Evergreen Terrace");
  const [city, setCity] = useState("Boston");
  const [stateRegion, setStateRegion] = useState("MA");
  const [zipcode, setZipcode] = useState("02115");
  const [country, setCountry] = useState("US");
  const [radius, setRadius] = useState(15);

  // Password form
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrentPw, setShowCurrentPw] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);
  const [showConfirmPw, setShowConfirmPw] = useState(false);

  // Digital Health Card
  const [cardVisible, setCardVisible] = useState(false);
  const [cardBloodGroup, setCardBloodGroup] = useState("O+");
  const [cardAllergies, setCardAllergies] = useState("Penicillin");
  const [cardEmergencyContact, setCardEmergencyContact] = useState("");
  const [cardEmergencyPhone, setCardEmergencyPhone] = useState("");

  // Digital Health Card data: the signed-in patient's profile, the same
  // source as the /health-card route.
  const [healthCard, setHealthCard] = useState<HealthCardInfo | null>(null);
  useEffect(() => {
    let cancelled = false;
    loadHealthCard()
      .then((hc) => {
        if (cancelled) return;
        setHealthCard(hc);
        setFirstName(hc.firstName);
        setLastName(hc.lastName);
        setPhone(hc.phone === "—" ? "" : hc.phone);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // Password strength
  const passwordStrength = (val: string) => {
    let score = 0;
    if (val.length >= 8) score++;
    if (/[A-Z]/.test(val)) score++;
    if (/[0-9]/.test(val)) score++;
    if (/[^A-Za-z0-9]/.test(val)) score++;
    return score;
  };

  const handlePasswordUpdate = (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword.length < 8) {
      showToast("Password Error", "Password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      showToast("Mismatch", "Passwords do not match. Please re-enter.");
      return;
    }
    showToast("Security Credentials Updated", "Your account password has been safely updated.");
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
  };

  const autoDetectLocation = () => {
    showToast("Detecting GPS...", "Fetching location from browser geolocation service...");
    setTimeout(() => {
      setAddress("100 Longwood Ave");
      setCity("Boston");
      setStateRegion("MA");
      setZipcode("02115");
      showToast("Location Detected", "Coordinates resolved: Boston Medical District.");
    }, 700);
  };

  const strengthScore = passwordStrength(newPassword);
  const strengthLabels = ["None", "Weak", "Fair", "Good", "Strong"];
  const strengthColors = ["text-slate-400", "text-rose-500", "text-amber-500", "text-teal-600", "text-emerald-600"];
  const strengthBarColors = ["bg-slate-200", "bg-rose-500", "bg-amber-500", "bg-teal-500", "bg-emerald-500"];

  const passwordReqs = [
    { id: "req-length", label: "8+ Characters", met: newPassword.length >= 8 },
    { id: "req-upper", label: "Uppercase Letter", met: /[A-Z]/.test(newPassword) },
    { id: "req-number", label: "One Number", met: /[0-9]/.test(newPassword) },
    { id: "req-symbol", label: "Special Symbol", met: /[^A-Za-z0-9]/.test(newPassword) },
  ];

  // ===== Medical Record page state =====
  // (simplified: static list, no modal state needed)

  // Reset medical record state when navigating away
  const prevActiveNavRef3 = useRef(activeNav);
  useEffect(() => {
    prevActiveNavRef3.current = activeNav;
  }, [activeNav]);

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

  // Reset settings state when navigating away from settings
  const prevActiveNavRef = useRef(activeNav);
  useEffect(() => {
    if (prevActiveNavRef.current !== activeNav && activeNav !== "setting") {
      setFirstName(healthCard?.firstName || "Daniel");
      setLastName(healthCard?.lastName || "Everett");
      setEmail("daniel.everett@healthmail.com");
      setPhone(healthCard?.phone || "+1 (617) 555-0198");
      setAddress("742 Evergreen Terrace");
      setCity("Boston");
      setStateRegion("MA");
      setZipcode("02115");
      setCountry("US");
      setRadius(15);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setCardVisible(false);
      setCardBloodGroup("O+");
      setCardAllergies("Penicillin");
      setCardEmergencyContact("");
      setCardEmergencyPhone("");
      dismissToast();
    }
    prevActiveNavRef.current = activeNav;
  }, [activeNav, healthCard]);

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
                {firstName} {lastName}
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

          {/* ===== Settings View (New Design) ===== */}
          {activeNav === "setting" && (
            <div data-purpose="settings-view" className="flex-1 min-h-0 overflow-y-auto">
              <div className="max-w-5xl mx-auto space-y-6 py-6">
                {/* Page Header */}
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 pb-2">
                  <div>
                    <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">Account Settings</h1>
                    <p className="text-sm text-slate-500 mt-1">Update your personal details, location preferences, and security credentials.</p>
                  </div>
                  <div className="inline-flex items-center gap-2 self-start md:self-auto px-3.5 py-1.5 rounded-full bg-white border border-slate-200 text-xs text-slate-600 shadow-xs">
                    <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                    <span>Account Status: <strong className="text-slate-800">Verified &amp; Secure</strong></span>
                  </div>
                </div>


                {/* Section 1: General Profile */}
                <section data-purpose="user-profile-section" id="general-profile" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-4">
                    <div>
                      <h2 className="text-lg font-bold text-slate-900">Personal Information</h2>
                      <p className="text-xs sm:text-sm text-slate-500">Manage your clinical name, verified Patient ID, and contact points.</p>
                    </div>
                    <span className="self-start sm:self-auto px-3 py-1 bg-emerald-50 text-emerald-700 text-xs font-semibold rounded-full border border-emerald-200">
                      {healthCard?.userId ?? "DE482731"} - Verified Patient
                    </span>
                  </div>

                  {/* Profile Form */}
                  <form onSubmit={(e) => { e.preventDefault(); showToast("Profile Saved", "Personal details saved and synced."); }} className="space-y-5">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="first-name">First Name</label>
                        <input id="first-name" required type="text" value={firstName} onChange={(e) => setFirstName(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border" />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="last-name">Last Name</label>
                        <input id="last-name" required type="text" value={lastName} onChange={(e) => setLastName(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border" />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="patient-id-field">System Patient ID</label>
                        <input id="patient-id-field" readOnly type="text" value={healthCard?.userId ?? "DE482731"} className="w-full text-sm rounded-xl bg-slate-50 border-slate-200 text-slate-500 py-2.5 px-3.5 cursor-not-allowed border" />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="email-address">Email Address</label>
                        <div className="relative">
                          <input id="email-address" required type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 pr-24 shadow-xs text-slate-900 border" />
                          <span className="absolute right-2.5 top-1/2 -translate-y-1/2 inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md">
                            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path clipRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" fillRule="evenodd" /></svg>
                            Verified
                          </span>
                        </div>
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="phone-number">Phone Number</label>
                        <div className="relative">
                          <input id="phone-number" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 pr-24 shadow-xs text-slate-900 border" />
                          <span className="absolute right-2.5 top-1/2 -translate-y-1/2 inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md">
                            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path clipRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" fillRule="evenodd" /></svg>
                            Verified
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
                      <button type="submit" className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs sm:text-sm rounded-xl shadow-sm transition-all focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2">
                        Save Changes
                      </button>
                    </div>
                  </form>
                </section>

                {/* Section 2: Location & Region */}
                <section data-purpose="location-settings-section" id="location-region" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-4">
                    <div>
                      <h2 className="text-lg font-bold text-slate-900">Location &amp; Emergency Region</h2>
                      <p className="text-xs sm:text-sm text-slate-500">Used to match nearby partner hospitals, dispatch emergency triage, and estimate clinic travel time.</p>
                    </div>
                    <button type="button" onClick={autoDetectLocation} className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-50 hover:bg-emerald-50 text-slate-700 hover:text-emerald-700 border border-slate-200 hover:border-emerald-300 text-xs font-semibold transition-all shadow-xs">
                      <svg className="w-4 h-4 text-emerald-600 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} /><path d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} /></svg>
                      <span>Detect Current Location</span>
                    </button>
                  </div>
                  <form onSubmit={(e) => { e.preventDefault(); showToast("Location Updated", "Emergency and partner clinic radius refreshed."); }} className="space-y-5">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                      <div className="md:col-span-2">
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="address-line">Street Address</label>
                        <input id="address-line" required type="text" value={address} onChange={(e) => setAddress(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border" />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="city">City</label>
                        <input id="city" required type="text" value={city} onChange={(e) => setCity(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border" />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="state">State / Province</label>
                        <input id="state" required type="text" value={stateRegion} onChange={(e) => setStateRegion(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border" />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="zipcode">ZIP / Postal Code</label>
                        <input id="zipcode" type="text" value={zipcode} onChange={(e) => setZipcode(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border" />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="country">Country / Region</label>
                        <select id="country" value={country} onChange={(e) => setCountry(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border">
                          <option value="US">United States</option>
                          <option value="CA">Canada</option>
                          <option value="GB">United Kingdom</option>
                          <option value="AU">Australia</option>
                        </select>
                      </div>
                    </div>
                    {/* Radius Slider */}
                    <div className="bg-slate-50/80 p-4 rounded-xl border border-slate-200">
                      <div className="flex items-center justify-between mb-2">
                        <label className="text-xs font-bold uppercase tracking-wider text-slate-700" htmlFor="radius-slider">Preferred Healthcare Radius</label>
                        <span className="text-xs font-semibold text-emerald-700 bg-emerald-100/70 px-2.5 py-0.5 rounded-full">Within {radius} miles</span>
                      </div>
                      <input id="radius-slider" max={50} min={5} step={5} type="range" value={radius} onChange={(e) => setRadius(Number(e.target.value))} className="w-full accent-emerald-600 h-2 bg-slate-200 rounded-lg cursor-pointer" />
                      <div className="flex justify-between text-[11px] text-slate-400 mt-1">
                        <span>5 mi (Strict Local)</span>
                        <span>25 mi</span>
                        <span>50 mi (Regional Support)</span>
                      </div>
                    </div>
                    <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
                      <button type="submit" className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs sm:text-sm rounded-xl shadow-sm transition-all focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2">
                        Update Location
                      </button>
                    </div>
                  </form>
                </section>

                {/* Section 3: Password & Security */}
                <section data-purpose="security-settings-section" id="password-security" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
                  <div className="border-b border-slate-100 pb-4">
                    <h2 className="text-lg font-bold text-slate-900">Password &amp; Security</h2>
                    <p className="text-xs sm:text-sm text-slate-500">Ensure your clinical account is protected with a secure password and multi-factor authentication.</p>
                  </div>
                  <form onSubmit={handlePasswordUpdate} className="space-y-5">
                    <div>
                      <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="current-password">Current Password</label>
                      <div className="relative">
                        <input id="current-password" placeholder="••••••••••••" required type={showCurrentPw ? "text" : "password"} value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 pr-10 shadow-xs text-slate-900 border" />
                        <button type="button" aria-label="Toggle password view" onClick={() => setShowCurrentPw(!showCurrentPw)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 focus:outline-none">
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} /><path d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} /></svg>
                        </button>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="new-password">New Password</label>
                        <div className="relative">
                          <input id="new-password" placeholder="Enter new strong password" required type={showNewPw ? "text" : "password"} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 pr-10 shadow-xs text-slate-900 border" />
                          <button type="button" aria-label="Toggle password view" onClick={() => setShowNewPw(!showNewPw)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 focus:outline-none">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} /><path d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} /></svg>
                          </button>
                        </div>
                        {/* Strength Meter */}
                        <div className="mt-2.5">
                          <div className="flex items-center justify-between text-xs mb-1">
                            <span className="text-slate-500">Strength:</span>
                            <span id="strength-label" className={`font-semibold ${strengthColors[strengthScore]}`}>{strengthLabels[strengthScore]}</span>
                          </div>
                          <div className="grid grid-cols-4 gap-1.5 h-1.5">
                            {[0, 1, 2, 3].map((i) => (
                              <div key={i} className={`rounded-full transition-colors ${i < strengthScore ? strengthBarColors[strengthScore] : "bg-slate-200"}`} />
                            ))}
                          </div>
                        </div>
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="confirm-password">Confirm New Password</label>
                        <div className="relative">
                          <input id="confirm-password" placeholder="Re-type new password" required type={showConfirmPw ? "text" : "password"} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 pr-10 shadow-xs text-slate-900 border" />
                          <button type="button" aria-label="Toggle password view" onClick={() => setShowConfirmPw(!showConfirmPw)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 focus:outline-none">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} /><path d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} /></svg>
                          </button>
                        </div>
                        {confirmPassword && (
                          <div id="match-indicator" className={`text-[11px] mt-1.5 font-semibold ${newPassword === confirmPassword ? "text-emerald-600" : "text-rose-500"}`}>
                            {newPassword === confirmPassword ? "✓ Passwords match" : "✕ Passwords do not match"}
                          </div>
                        )}
                      </div>
                    </div>
                    {/* Requirements Checklist */}
                    <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 text-xs text-slate-600 grid grid-cols-2 sm:grid-cols-4 gap-2">
                      {passwordReqs.map((req) => (
                        <div key={req.id} className={`flex items-center gap-1.5 ${req.met ? "text-emerald-600" : "text-slate-400"}`}>
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} /></svg>
                          <span>{req.label}</span>
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
                      <button type="submit" className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs sm:text-sm rounded-xl shadow-sm transition-all focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2">
                        Update Password
                      </button>
                    </div>
                  </form>
                </section>

                {/* Section 4: Digital Health Card */}
                <section data-purpose="digital-card-section" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-4">
                    <div>
                      <h2 className="text-lg font-bold text-slate-900">Digital Health Card</h2>
                      <p className="text-xs sm:text-sm text-slate-500">Customize the details shown on your ENDOD digital health card.</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setCardVisible(!cardVisible)}
                      className="self-start sm:self-auto px-3.5 py-1.5 rounded-lg bg-emerald-50 hover:bg-emerald-100 text-emerald-700 text-xs font-semibold border border-emerald-200 transition-colors"
                    >
                      {cardVisible ? "Hide Card Preview" : "Show Card Preview"}
                    </button>
                  </div>

                  {cardVisible && (
                    /* Card Preview */
                    <div data-purpose="card-preview" className="relative bg-gradient-to-br from-[#1e3a2e] to-[#1e5852] rounded-2xl p-6 text-white overflow-hidden">
                      <div className="absolute inset-0 opacity-5">
                        <svg className="w-full h-full" viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg">
                          <circle cx="200" cy="200" r="50" stroke="currentColor" strokeWidth="0.5" />
                          <circle cx="200" cy="200" r="120" stroke="currentColor" strokeWidth="0.3" />
                        </svg>
                      </div>
                      <div className="relative mb-6">
                        <span className="text-2xl font-extrabold tracking-tight">al<span className="text-[#6ee7b7]">lia</span></span>
                      </div>
                      <div className="relative mb-4">
                        <span className="text-xs font-semibold text-[#94e0c0] uppercase tracking-wider">Digital Health ID</span>
                      </div>
                      <div className="relative mb-1">
                        <h3 className="text-2xl font-bold font-serif text-white">{healthCard?.fullName ?? `${firstName} ${lastName}`}</h3>
                      </div>
                      <div className="relative mb-6">
                        <span className="text-base font-semibold text-[#94e0c0]">{healthCard?.userId ?? "DE482731"}</span>
                      </div>
                      <div className="relative grid grid-cols-2 sm:grid-cols-4 gap-4">
                        <div>
                          <span className="text-[10px] font-semibold text-[#94a3a8] uppercase tracking-wider">Phone</span>
                          <p className="text-sm font-semibold text-white mt-1">{healthCard?.phone ?? phone}</p>
                        </div>
                        <div>
                          <span className="text-[10px] font-semibold text-[#94a3a8] uppercase tracking-wider">Blood Group</span>
                          <p className="text-sm font-semibold text-white mt-1">{cardBloodGroup || "—"}</p>
                        </div>
                        <div>
                          <span className="text-[10px] font-semibold text-[#94a3a8] uppercase tracking-wider">Allergies</span>
                          <p className="text-sm font-semibold text-white mt-1">{cardAllergies || "None"}</p>
                        </div>
                        <div>
                          <span className="text-[10px] font-semibold text-[#94a3a8] uppercase tracking-wider">Emergency</span>
                          <p className="text-sm font-semibold text-white mt-1">{cardEmergencyContact || "—"}</p>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Card Edit Form */}
                  <form onSubmit={(e) => { e.preventDefault(); showToast("Card Updated", "Digital health card details saved."); }} className="space-y-5">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="blood-group">Blood Group</label>
                        <select id="blood-group" value={cardBloodGroup} onChange={(e) => setCardBloodGroup(e.target.value)} className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border">
                          <option value="">Not specified</option>
                          <option value="A+">A+</option>
                          <option value="A-">A-</option>
                          <option value="B+">B+</option>
                          <option value="B-">B-</option>
                          <option value="O+">O+</option>
                          <option value="O-">O-</option>
                          <option value="AB+">AB+</option>
                          <option value="AB-">AB-</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="allergies">Known Allergies</label>
                        <input id="allergies" type="text" value={cardAllergies} onChange={(e) => setCardAllergies(e.target.value)} placeholder="e.g. Penicillin, Latex..." className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border" />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="emergency-contact">Emergency Contact Name</label>
                        <input id="emergency-contact" type="text" value={cardEmergencyContact} onChange={(e) => setCardEmergencyContact(e.target.value)} placeholder="Full name" className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border" />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5" htmlFor="emergency-phone">Emergency Contact Phone</label>
                        <input id="emergency-phone" type="tel" value={cardEmergencyPhone} onChange={(e) => setCardEmergencyPhone(e.target.value)} placeholder="+1 (617) 555-0199" className="w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border" />
                      </div>
                    </div>
                    <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
                      <button type="submit" className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs sm:text-sm rounded-xl shadow-sm transition-all focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2">
                        Save Card Details
                      </button>
                    </div>
                  </form>
                </section>
              </div>
            </div>
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

          {/* ===== Medical Record View (New Design) ===== */}
          {activeNav === "followup" && (
            <div data-purpose="medical-record-view" className="flex-1 min-h-0 overflow-y-auto">
              <div className="max-w-5xl mx-auto space-y-6 pb-6">

                {/* Page Title */}
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                  <div>
                    <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">Medical Records</h1>
                    <p className="text-sm text-slate-500 mt-1">Your complete treatment history — visits, diagnoses, medications, and follow-up schedules.</p>
                  </div>
                  <span data-purpose="records-count" className="inline-flex items-center gap-2 self-start rounded-full border border-emerald-200 bg-emerald-50 px-3.5 py-1.5 text-xs font-semibold text-emerald-700 shadow-sm">
                    <span className="relative flex h-2 w-2">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500"></span>
                    </span>
                    3 Verified Records
                  </span>
                </div>

                {/* Summary Strip */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
                  <div data-purpose="stat-total-visits" className="bg-white rounded-2xl border border-slate-200 card-shadow p-4">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-slate-100 text-slate-600 flex items-center justify-center flex-shrink-0">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
                          <path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </div>
                      <div>
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Total Visits</p>
                        <p className="text-xl font-bold text-slate-900 leading-tight tabular-nums">3</p>
                      </div>
                    </div>
                  </div>
                  <div data-purpose="stat-hospitals" className="bg-white rounded-2xl border border-slate-200 card-shadow p-4">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-emerald-100 text-emerald-600 flex items-center justify-center flex-shrink-0">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
                          <path d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </div>
                      <div>
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Hospitals Visited</p>
                        <p className="text-xl font-bold text-emerald-700 leading-tight tabular-nums">3</p>
                      </div>
                    </div>
                  </div>
                  <div data-purpose="stat-drugs" className="bg-white rounded-2xl border border-slate-200 card-shadow p-4">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-purple-100 text-purple-600 flex items-center justify-center flex-shrink-0">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
                          <path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z" strokeLinecap="round" strokeLinejoin="round" />
                          <path d="m8.5 8.5 7 7" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </div>
                      <div>
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Drugs Used</p>
                        <p className="text-xl font-bold text-slate-900 leading-tight tabular-nums">2</p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Medical Records Table */}
                <div data-purpose="medical-records-table" className="bg-white rounded-2xl border border-slate-200 card-shadow overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm border-collapse">
                      <thead>
                        <tr className="bg-gradient-to-r from-slate-50 via-slate-50 to-emerald-50/40 border-b-2 border-slate-200">
                          <th className="text-left px-5 py-4 text-[11px] font-bold uppercase tracking-wider text-slate-500 whitespace-nowrap">
                            <span className="inline-flex items-center gap-2">
                              <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                                <path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                              Date
                            </span>
                          </th>
                          <th className="text-left px-5 py-4 text-[11px] font-bold uppercase tracking-wider text-slate-500 whitespace-nowrap">
                            <span className="inline-flex items-center gap-2">
                              <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                                <path d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                              Hospital
                            </span>
                          </th>
                          <th className="text-left px-5 py-4 text-[11px] font-bold uppercase tracking-wider text-slate-500 whitespace-nowrap">
                            <span className="inline-flex items-center gap-2">
                              <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                                <path d="M22 12h-4l-3 9L9 3l-3 9H2" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                              Disease
                            </span>
                          </th>
                          <th className="text-left px-5 py-4 text-[11px] font-bold uppercase tracking-wider text-slate-500 whitespace-nowrap">
                            <span className="inline-flex items-center gap-2">
                              <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                                <path d="m10.5 20.5 10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7Z" strokeLinecap="round" strokeLinejoin="round" />
                                <path d="m8.5 8.5 7 7" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                              Drug
                            </span>
                          </th>
                          <th className="text-left px-5 py-4 text-[11px] font-bold uppercase tracking-wider text-slate-500 whitespace-nowrap">
                            <span className="inline-flex items-center gap-2">
                              <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                                <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                              Followup
                            </span>
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {/* Row 1 */}
                        <tr data-purpose="record-1" className={`group transition-colors even:bg-slate-50/40 hover:bg-emerald-50/60 ${highlightTarget === "record-1" ? "bg-emerald-50 ring-2 ring-inset ring-emerald-300" : ""}`}>
                          <td className="px-5 py-4 align-middle">
                            <div className="font-semibold text-slate-900 whitespace-nowrap">Aug 24, 2026</div>
                            <div className="text-[11px] text-slate-400">9:00 AM</div>
                          </td>
                          <td className="px-5 py-4 align-middle">
                            <div className="font-semibold text-slate-900">Apex Heart &amp; Health Institute</div>
                            <div className="text-[11px] text-emerald-600 font-medium">Cardiology Center</div>
                          </td>
                          <td className="px-5 py-4 align-middle text-slate-700">Chest Discomfort</td>
                          <td className="px-5 py-4 align-middle text-slate-700">Atorvastatin 20mg</td>
                          <td className="px-5 py-4 align-middle">
                            <div className="font-bold text-emerald-700">7 days</div>
                            <div className="text-[11px] text-slate-400">Follow-up in 7 days</div>
                          </td>
                        </tr>

                        {/* Row 2 */}
                        <tr data-purpose="record-2" className={`group transition-colors even:bg-slate-50/40 hover:bg-emerald-50/60 ${highlightTarget === "record-2" ? "bg-emerald-50 ring-2 ring-inset ring-emerald-300" : ""}`}>
                          <td className="px-5 py-4 align-middle">
                            <div className="font-semibold text-slate-900 whitespace-nowrap">May 19, 2026</div>
                            <div className="text-[11px] text-slate-400">8:00 AM</div>
                          </td>
                          <td className="px-5 py-4 align-middle">
                            <div className="font-semibold text-slate-900">City Care Diagnostics Center</div>
                            <div className="text-[11px] text-blue-600 font-medium">Diagnostic Lab</div>
                          </td>
                          <td className="px-5 py-4 align-middle text-slate-700">Blood Panel Screening</td>
                          <td className="px-5 py-4 align-middle text-slate-400">None</td>
                          <td className="px-5 py-4 align-middle">
                            <div className="font-medium text-slate-500">No follow-up</div>
                          </td>
                        </tr>

                        {/* Row 3 */}
                        <tr data-purpose="record-3" className={`group transition-colors even:bg-slate-50/40 hover:bg-emerald-50/60 ${highlightTarget === "record-3" ? "bg-emerald-50 ring-2 ring-inset ring-emerald-300" : ""}`}>
                          <td className="px-5 py-4 align-middle">
                            <div className="font-semibold text-slate-900 whitespace-nowrap">Jan 14, 2026</div>
                            <div className="text-[11px] text-slate-400">10:00 AM</div>
                          </td>
                          <td className="px-5 py-4 align-middle">
                            <div className="font-semibold text-slate-900">Walgreens Pharmacy #4102</div>
                            <div className="text-[11px] text-purple-600 font-medium">Prescription Fulfillment</div>
                          </td>
                          <td className="px-5 py-4 align-middle text-slate-700">Seasonal Bronchitis</td>
                          <td className="px-5 py-4 align-middle text-slate-700">Azithromycin 500mg</td>
                          <td className="px-5 py-4 align-middle">
                            <div className="font-bold text-purple-700">5 days</div>
                            <div className="text-[11px] text-slate-400">Course completed</div>
                          </td>
                        </tr>
                      </tbody>
                      <tfoot>
                        <tr className="bg-slate-50/80 border-t-2 border-slate-200">
                          <td className="px-5 py-3.5 text-[11px] font-bold uppercase tracking-wider text-slate-500" colSpan={4}>
                            3 Records
                          </td>
                          <td className="px-5 py-3.5">
                            <span className="text-xs font-semibold text-emerald-700">
                              1 Active Follow-up
                            </span>
                          </td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                </div>

              </div>
            </div>
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
