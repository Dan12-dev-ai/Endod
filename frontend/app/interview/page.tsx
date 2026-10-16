"use client";

import { useEffect, useRef, useState } from "react";
import { loadHealthCard, type HealthCardInfo } from "../health-card/health-card-data";

// ---------------------------------------------------------------------------
// Booking hospital directory data (new design)
// ---------------------------------------------------------------------------

type BookingHospital = {
  id: string;
  name: string;
  initials: string;
  website: string;
  distance: string;
  wait: string;
  rating: string;
  status: string;
  statusBg: string;
  statusText: string;
  statusBorder: string;
  tags: string[];
  portalText: string;
  iconBg: string;
  iconBorder: string;
  iconText: string;
  linkColor: string;
};

const BOOKING_HOSPITALS: BookingHospital[] = [
  {
    id: "h1",
    name: "St. Jude Metropolitan Hospital",
    initials: "SJ",
    website: "stjude-hospital.health",
    distance: "1.8 miles",
    wait: "~15 mins",
    rating: "4.9 ★ (840)",
    status: "Open 24/7",
    statusBg: "bg-emerald-50",
    statusText: "text-emerald-700",
    statusBorder: "border-emerald-200",
    tags: ["Cardiology", "Emergency Care", "ENDOD FastTrack"],
    portalText: "Instant direct portal",
    iconBg: "bg-emerald-50",
    iconBorder: "border-emerald-100",
    iconText: "text-emerald-600",
    linkColor: "text-emerald-700",
  },
  {
    id: "h2",
    name: "Apex Heart & Health Institute",
    initials: "AH",
    website: "apexhealthcenter.org",
    distance: "3.2 miles",
    wait: "~25 mins",
    rating: "4.8 ★ (1,120)",
    status: "Slots Today",
    statusBg: "bg-blue-50",
    statusText: "text-blue-700",
    statusBorder: "border-blue-200",
    tags: ["Cardiac Specialty", "Diagnostic Lab", "Insurance Accepted"],
    portalText: "Official hospital website portal",
    iconBg: "bg-teal-50",
    iconBorder: "border-teal-100",
    iconText: "text-teal-600",
    linkColor: "text-teal-700",
  },
  {
    id: "h3",
    name: "Providence Memorial Hospital",
    initials: "PM",
    website: "providence-memorial.org",
    distance: "4.1 miles",
    wait: "~10 mins",
    rating: "4.9 ★ (2,450)",
    status: "Open 24/7",
    statusBg: "bg-emerald-50",
    statusText: "text-emerald-700",
    statusBorder: "border-emerald-200",
    tags: ["Pulmonology", "Chest Pain Center", "Full Diagnostics"],
    portalText: "Official hospital website portal",
    iconBg: "bg-indigo-50",
    iconBorder: "border-indigo-100",
    iconText: "text-indigo-600",
    linkColor: "text-indigo-700",
  },
  {
    id: "h4",
    name: "City Care Specialty Clinics",
    initials: "CC",
    website: "citycare-clinics.com",
    distance: "5.0 miles",
    wait: "~20 mins",
    rating: "4.7 ★ (610)",
    status: "Walk-ins Welcome",
    statusBg: "bg-emerald-50",
    statusText: "text-emerald-700",
    statusBorder: "border-emerald-200",
    tags: ["Outpatient Care", "Same-Day Scans", "Telehealth Follow-up"],
    portalText: "Official hospital website portal",
    iconBg: "bg-cyan-50",
    iconBorder: "border-cyan-100",
    iconText: "text-cyan-600",
    linkColor: "text-cyan-700",
  },
];

// ---------------------------------------------------------------------------

type NotifItem = {
  id: string;
  type: string;
  typeClass: string;
  title: string;
  body: string;
  meta: string;
  time: string;
  unread: boolean;
  target?: string;
  tab?: string;
  action: string;
};

type NotifGroup = {
  id: string;
  title: string;
  iconPath: string;
  iconWrap: string;
  iconColor: string;
  nav: string | null;
  items: NotifItem[];
};

const NOTIF_GROUPS: NotifGroup[] = [
  {
    id: "appointments",
    title: "Appointment updates",
    iconPath: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
    iconWrap: "bg-emerald-50 border border-emerald-100",
    iconColor: "text-emerald-600",
    nav: "appointment",
    items: [
      {
        id: "n1",
        type: "Appointment confirmed",
        typeClass: "text-emerald-700 bg-emerald-50 border-emerald-100",
        title: "Appointment Confirmed with Dr. Marcus Vance, MD",
        body: "Your in-person consultation at Apex Heart & Health Institute is confirmed for Oct 18, 2026 at 10:30 AM.",
        meta: "Dr. Marcus Vance • Apex Heart & Health Institute",
        time: "2 hours ago",
        unread: true,
        target: "appointment-card-1",
        tab: "upcoming",
        action: "View in Appointments",
      },
      {
        id: "n2",
        type: "Appointment rescheduled",
        typeClass: "text-amber-700 bg-amber-50 border-amber-100",
        title: "Telehealth Visit Rescheduled with Dr. Sarah Jenkins",
        body: "Your video consultation has been moved to Oct 20, 2026 at 2:00 PM (30 minutes).",
        meta: "Dr. Sarah Jenkins • ENDOD Telehealth Room",
        time: "5 hours ago",
        unread: true,
        target: "appointment-card-2",
        tab: "upcoming",
        action: "View in Appointments",
      },
      {
        id: "n3",
        type: "Appointment canceled",
        typeClass: "text-rose-700 bg-rose-50 border-rose-100",
        title: "Lab Draw Appointment Canceled",
        body: "Your diagnostic lab appointment at City Care Diagnostics scheduled for Oct 25 has been canceled.",
        meta: "City Care Diagnostics & Pathology Center",
        time: "1 day ago",
        unread: false,
        target: "cancelled-card-1",
        tab: "cancelled",
        action: "View in Appointments",
      },
      {
        id: "n4",
        type: "Upcoming appointment reminder",
        typeClass: "text-teal-700 bg-teal-50 border-teal-100",
        title: "Reminder: Follow-up with Dr. Marcus Vance Tomorrow",
        body: "Your follow-up appointment at Apex Heart & Health Institute is scheduled for tomorrow, Oct 18 at 10:30 AM.",
        meta: "Apex Heart & Health Institute • 3.2 miles",
        time: "1 day ago",
        unread: false,
        target: "appointment-card-1",
        tab: "upcoming",
        action: "View in Appointments",
      },
      {
        id: "n5",
        type: "Doctor or clinic updates",
        typeClass: "text-blue-700 bg-blue-50 border-blue-100",
        title: "City Care Diagnostics Updated Visit Instructions",
        body: "City Care Diagnostics has updated its check-in procedure and parking guidance for your Oct 28 lab draw.",
        meta: "City Care Diagnostics & Pathology Center",
        time: "2 days ago",
        unread: false,
        target: "appointment-card-3",
        tab: "upcoming",
        action: "View in Appointments",
      },
    ],
  },
  {
    id: "records",
    title: "Medical record updates",
    iconPath: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
    iconWrap: "bg-teal-50 border border-teal-100",
    iconColor: "text-teal-600",
    nav: "followup",
    items: [
      {
        id: "n6",
        type: "Lab results available",
        typeClass: "text-teal-700 bg-teal-50 border-teal-100",
        title: "Comprehensive Metabolic Panel Results Available",
        body: "City Care Diagnostics released your blood panel results. All biomarkers are within normal reference ranges.",
        meta: "City Care Diagnostics Center",
        time: "3 hours ago",
        unread: true,
        target: "record-2",
        action: "View in Medical Records",
      },
      {
        id: "n7",
        type: "New medical report uploaded",
        typeClass: "text-indigo-700 bg-indigo-50 border-indigo-100",
        title: "Cardiovascular Stress ECG Report Uploaded",
        body: "Dr. Marcus Vance uploaded your Cardiovascular Checkup & Stress ECG report from your Aug 24, 2026 visit.",
        meta: "Apex Heart & Health Institute",
        time: "1 day ago",
        unread: false,
        target: "record-1",
        action: "View in Medical Records",
      },
      {
        id: "n8",
        type: "Prescription or doctor's notes updated",
        typeClass: "text-purple-700 bg-purple-50 border-purple-100",
        title: "Prescription Notes Updated by Dr. Sarah Jenkins",
        body: "Your Seasonal Bronchitis prescription notes (Azithromycin 500mg) have been updated with new dosage guidance.",
        meta: "Walgreens Pharmacy #4102",
        time: "4 days ago",
        unread: false,
        target: "record-3",
        action: "View in Medical Records",
      },
    ],
  },
  {
    id: "messages",
    title: "Messages and general updates",
    iconPath: "M8 10h.01M12 10h.01M16 10h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z",
    iconWrap: "bg-slate-100 border border-slate-200",
    iconColor: "text-slate-500",
    nav: null,
    items: [
      {
        id: "n9",
        type: "New message from a doctor",
        typeClass: "text-emerald-700 bg-emerald-50 border-emerald-100",
        title: "Message from Dr. Marcus Vance, MD",
        body: "\u201cYour latest results look good. Continue the current medication and we'll review everything at your follow-up.\u201d",
        meta: "Dr. Marcus Vance • Apex Heart & Health Institute",
        time: "30 mins ago",
        unread: true,
        action: "Read Message",
      },
      {
        id: "n10",
        type: "Account or security alert",
        typeClass: "text-rose-700 bg-rose-50 border-rose-100",
        title: "New Device Sign-in Detected",
        body: "Your ENDOD Health account was accessed from a new device (Chrome on Windows). If this wasn't you, secure your account.",
        meta: "ENDOD Health Security",
        time: "6 hours ago",
        unread: false,
        action: "Review Activity",
      },
      {
        id: "n11",
        type: "Important announcement from the clinic",
        typeClass: "text-blue-700 bg-blue-50 border-blue-100",
        title: "Flu Vaccination Drive at Apex Heart Institute",
        body: "Free flu vaccinations available every Saturday in October. Walk-ins welcome, no appointment needed.",
        meta: "Apex Heart & Health Institute",
        time: "3 days ago",
        unread: false,
        action: "Learn More",
      },
    ],
  },
];

// ---------------------------------------------------------------------------

export default function Interview() {
  const [toggles, setToggles] = useState({ mic: false, camera: false, speaker: false, pause: false });

  const toggle = (key: "mic" | "camera" | "speaker" | "pause") =>
    setToggles((prev) => ({ ...prev, [key]: !prev[key] }));

  const [activeNav, setActiveNav] = useState("live");
  const [liveStarted, setLiveStarted] = useState(false);
  // Shared: which card/record a notification click should highlight on the target page
  const [highlightTarget, setHighlightTarget] = useState<string | null>(null);

  // Booking page state (new design)
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedHospital, setSelectedHospital] = useState<BookingHospital | null>(null);
  const [showBookingModal, setShowBookingModal] = useState(false);
  const [showSuccessModal, setShowSuccessModal] = useState(false);

  // Booking form fields (lazy init to avoid setState-in-effect)
  const [bookingDate, setBookingDate] = useState(() => new Date().toISOString().split("T")[0]);
  const [bookingTime, setBookingTime] = useState("10:30");
  const [timeWindow, setTimeWindow] = useState("Exact Arrival Time");
  const [department, setDepartment] = useState("Cardiology & Chest Consultation");
  const [bookingNote, setBookingNote] = useState("");

  const navItems = [
    { id: "home", label: "Home", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "live", label: "Live Discussion", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "booking", label: "Booking", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M12 4v16m8-8H4" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "appointment", label: "Appointment", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "followup", label: "Medical Record", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "message", label: "Notification", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
    { id: "setting", label: "Setting", icon: (<svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24"><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" strokeLinecap="round" strokeLinejoin="round" /><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" strokeLinecap="round" strokeLinejoin="round" /></svg>) },
  ];

  // ===== Booking handlers =====
  const openBookingModal = (hospital: BookingHospital) => {
    setSelectedHospital(hospital);
    setShowBookingModal(true);
  };

  const closeBookingModal = () => {
    setShowBookingModal(false);
  };

  const handleSubmitBooking = (e: React.FormEvent) => {
    e.preventDefault();
    closeBookingModal();
    setShowSuccessModal(true);
  };

  const closeSuccessModal = () => {
    setShowSuccessModal(false);
    setSelectedHospital(null);
  };

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

  // ===== Appointment page state =====
  const [appointmentTab, setAppointmentTab] = useState<"upcoming" | "past" | "cancelled">("upcoming");
  const [showAppointmentModal, setShowAppointmentModal] = useState(false);
  const [appointmentModalMode, setAppointmentModalMode] = useState<"book" | "reschedule">("book");
  const [appointmentModalProvider, setAppointmentModalProvider] = useState("");
  const [appointmentFormDate, setAppointmentFormDate] = useState("2026-10-15");
  const [appointmentFormTime, setAppointmentFormTime] = useState("02:00 PM – 02:45 PM");
  const [appointmentFormType, setAppointmentFormType] = useState<"in-person" | "telehealth">("in-person");
  const [appointmentFormNotes, setAppointmentFormNotes] = useState("");
  const [appointmentFormProvider, setAppointmentFormProvider] = useState("Dr. Marcus Vance, MD (Cardiology) • Apex Heart");
  const [showAppointmentSuccess, setShowAppointmentSuccess] = useState(false);

  // Reset appointment state when navigating away
  const prevActiveNavRef2 = useRef(activeNav);
  useEffect(() => {
    if (prevActiveNavRef2.current !== activeNav && activeNav !== "appointment") {
      setAppointmentTab("upcoming");
      setShowAppointmentModal(false);
      setShowAppointmentSuccess(false);
    }
    prevActiveNavRef2.current = activeNav;
  }, [activeNav]);

  const openAppointmentModal = (mode: "book" | "reschedule", provider?: string) => {
    setAppointmentModalMode(mode);
    setAppointmentModalProvider(provider ?? "");
    setShowAppointmentSuccess(false);
    setShowAppointmentModal(true);
  };

  const closeAppointmentModal = () => {
    setShowAppointmentModal(false);
    setShowAppointmentSuccess(false);
  };

  const handleAppointmentSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setShowAppointmentSuccess(true);
    setTimeout(() => {
      closeAppointmentModal();
    }, 1800);
  };

  // ===== Medical Record page state =====
  // (simplified: static list, no modal state needed)

  // Reset medical record state when navigating away
  const prevActiveNavRef3 = useRef(activeNav);
  useEffect(() => {
    prevActiveNavRef3.current = activeNav;
  }, [activeNav]);

  // ===== Notification page state =====
  const [notifFilter, setNotifFilter] = useState<"all" | "appointments" | "records" | "messages">("all");
  const [dismissedNotifs, setDismissedNotifs] = useState<string[]>([]);
  const [allRead, setAllRead] = useState(false);

  const dismissNotification = (id: string) => {
    setDismissedNotifs((prev) => [...prev, id]);
  };

  const markAllRead = () => {
    setAllRead(true);
  };

  // Click a notification -> jump to the relevant page (and highlight the target card/record)
  const openNotifTarget = (nav: string, item?: NotifItem) => {
    setHighlightTarget(item?.target ?? null);
    if (nav === "appointment" && item?.tab) {
      setAppointmentTab(item.tab as "upcoming" | "past" | "cancelled");
    }
    setActiveNav(nav);
  };

  // Reset notification state when navigating away
  const prevActiveNavRef4 = useRef(activeNav);
  useEffect(() => {
    if (prevActiveNavRef4.current !== activeNav && activeNav !== "message") {
      setNotifFilter("all");
      setDismissedNotifs([]);
      setAllRead(false);
    }
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
          {/* ===== Booking View (New Design) ===== */}
          {activeNav === "booking" && (
            <div data-purpose="booking-view" className="flex-1 min-h-0 overflow-y-auto">
              {/* Breadcrumbs & Welcome Hero */}
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
                <div>
                  <div className="flex items-center space-x-2 text-xs text-slate-400 mb-1">
                    <span>ENDOD Care</span>
                    <span>/</span>
                    <span className="text-emerald-700 font-medium">Hospital Booking</span>
                  </div>
                  <h1 className="text-xl md:text-2xl font-extrabold text-slate-900 tracking-tight">Hospital &amp; Clinic Reservation</h1>
                  <p className="text-xs md:text-sm text-slate-500 mt-0.5">Select how you&apos;d like to book your medical facility appointment.</p>
                </div>
                <div className="flex items-center space-x-2 text-xs text-slate-600 bg-white border border-slate-200 px-3 py-1.5 rounded-xl shadow-xs self-start sm:self-auto">
                  <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                  <span>Verified Partner Network (48 Hospitals)</span>
                </div>
              </div>

              {/* MANUAL BOOKING HOSPITAL WEBSITES LIST */}
              <section data-purpose="manual-booking-section" className="space-y-4 pb-6">
                {/* Search and Filters Bar */}
                <div className="bg-white p-4 rounded-2xl border border-slate-200 card-shadow flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                  <div className="flex-1 relative">
                    <svg className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                    <input
                      id="hospital-search"
                      data-purpose="hospital-search"
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search hospitals by name, specialty, or location..."
                      className="w-full pl-9 pr-4 py-2 text-xs md:text-sm rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-slate-800 placeholder-slate-400"
                    />
                  </div>
                  <div className="flex items-center space-x-2">
                    <select className="text-xs border border-slate-200 rounded-xl px-3 py-2 bg-white text-slate-600 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                      <option>All Specialties</option>
                      <option>Cardiology</option>
                      <option>General Medicine</option>
                      <option>Emergency &amp; Trauma</option>
                      <option>Pediatrics</option>
                    </select>
                    <select className="text-xs border border-slate-200 rounded-xl px-3 py-2 bg-white text-slate-600 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                      <option>Distance: Nearest</option>
                      <option>Highest Rated</option>
                      <option>Shortest Wait Time</option>
                    </select>
                  </div>
                </div>

                {/* Directory Subhead */}
                <div className="flex items-center justify-between px-1">
                  <h3 className="text-sm font-bold text-slate-900 flex items-center space-x-2">
                    <span>Verified Hospital Websites &amp; Centers</span>
                    <span className="text-xs font-normal text-slate-400">({BOOKING_HOSPITALS.length} hospitals available near you)</span>
                  </h3>
                </div>

                {/* Hospital Grid */}
                <div id="hospital-grid" data-purpose="hospital-grid" className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {BOOKING_HOSPITALS
                    .filter((h) => {
                      if (!searchQuery) return true;
                      const q = searchQuery.toLowerCase();
                      return (
                        h.name.toLowerCase().includes(q) ||
                        h.tags.some((t) => t.toLowerCase().includes(q)) ||
                        h.website.toLowerCase().includes(q)
                      );
                    })
                    .map((hospital) => (
                      <div
                        key={hospital.id}
                        data-purpose={`hospital-${hospital.id}`}
                        className="hospital-card bg-white rounded-2xl p-4 border border-slate-200 card-shadow hover:border-emerald-300 transition-all flex items-center justify-between"
                      >
                        <div className="flex items-center space-x-4">
                          <div className={`w-10 h-10 rounded-xl ${hospital.iconBg} border ${hospital.iconBorder} ${hospital.iconText} flex items-center justify-center font-bold text-sm flex-shrink-0`}>
                            {hospital.initials}
                          </div>
                          <div>
                            <h4 className="text-sm font-bold text-slate-900">{hospital.name}</h4>
                            <div className="flex items-center space-x-4 mt-0.5 text-xs text-slate-500">
                              <span>{hospital.distance}</span>
                              <span className="text-emerald-600 font-medium">{hospital.wait}</span>
                            </div>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => openBookingModal(hospital)}
                          className="inline-flex items-center space-x-1.5 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition shadow-sm flex-shrink-0"
                        >
                          <span>Book Now</span>
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                          </svg>
                        </button>
                      </div>
                    ))}
                </div>
              </section>
            </div>
          )}

          {/* ===== Booking Time & Submit Modal ===== */}
          {showBookingModal && selectedHospital && (
            <div id="booking-modal" data-purpose="booking-modal" className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
              <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200">
                {/* Modal Header */}
                <div className="flex items-start justify-between pb-4 border-b border-slate-100">
                  <div>
                    <span className="text-[11px] font-semibold text-emerald-600 uppercase tracking-wider">Hospital Website Booking</span>
                    <h3 className="text-lg font-bold text-slate-900 mt-0.5">{selectedHospital.name}</h3>
                    <p className="text-xs text-slate-500 mt-0.5">{selectedHospital.website} • {selectedHospital.distance}</p>
                  </div>
                  <button type="button" onClick={closeBookingModal} className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100 transition">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                {/* Booking Form */}
                <form onSubmit={handleSubmitBooking} className="space-y-4 mt-4">
                  {/* Patient Information Read-only Banner */}
                  <div className="bg-slate-50 rounded-xl p-3 border border-slate-100 flex items-center justify-between text-xs">
                    <div className="flex items-center space-x-2">
                      <div className="w-6 h-6 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center font-bold text-[10px]">P</div>
                      <span className="font-medium text-slate-700">Patient: DE482731</span>
                    </div>
                    <span className="text-emerald-700 font-medium">Referral summary attached</span>
                  </div>

                  {/* Date Input */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="booking-date">Select Visit Date</label>
                    <input type="date" id="booking-date" required value={bookingDate} onChange={(e) => setBookingDate(e.target.value)} className="w-full text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
                  </div>

                  {/* Visit Time */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">Enter Time Where You Will Go (Visit Time) *</label>
                    <div className="grid grid-cols-2 gap-2 mb-2">
                      <input type="time" id="booking-time" required value={bookingTime} onChange={(e) => setBookingTime(e.target.value)} className="w-full text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
                      <select value={timeWindow} onChange={(e) => setTimeWindow(e.target.value)} className="text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        <option>Exact Arrival Time</option>
                        <option>Morning (08:00 - 12:00)</option>
                        <option>Afternoon (12:00 - 17:00)</option>
                        <option>Evening (17:00 - 21:00)</option>
                      </select>
                    </div>
                    <p className="text-[11px] text-slate-400">Specifying your exact arrival time reserves your dedicated triage window.</p>
                  </div>

                  {/* Department / Specialty */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">Department / Clinic</label>
                    <select value={department} onChange={(e) => setDepartment(e.target.value)} className="w-full text-xs md:text-sm rounded-xl border border-slate-200 px-3 py-2 text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500">
                      <option>Cardiology &amp; Chest Consultation</option>
                      <option>General Emergency &amp; Acute Care</option>
                      <option>Outpatient Diagnostic Scan</option>
                      <option>Specialist Follow-up</option>
                    </select>
                  </div>

                  {/* Additional Notes */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">Reason for Visit / Note (Optional)</label>
                    <textarea id="booking-note" rows={2} value={bookingNote} onChange={(e) => setBookingNote(e.target.value)} placeholder="e.g. Chest pain follow-up from ENDOD live consultation..." className="w-full text-xs rounded-xl border border-slate-200 px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500" />
                  </div>

                  {/* Submit and Cancel Buttons */}
                  <div className="pt-3 border-t border-slate-100 flex items-center justify-end space-x-3">
                    <button type="button" onClick={closeBookingModal} className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-50 transition">
                      Cancel
                    </button>
                    <button type="submit" className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold transition shadow-sm flex items-center space-x-1.5">
                      <span>Submit Booking</span>
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* ===== Success Confirmation Modal ===== */}
          {showSuccessModal && selectedHospital && (
            <div id="success-modal" data-purpose="success-modal" className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
              <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-slate-200 text-center">
                <div className="w-14 h-14 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center mx-auto mb-4">
                  <svg className="w-8 h-8" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <h3 className="text-lg font-bold text-slate-900">Hospital Appointment Confirmed!</h3>
                <p className="text-xs text-slate-500 mt-1">Your reservation has been transmitted to the hospital portal.</p>

                <div className="bg-slate-50 rounded-xl p-4 my-4 text-left border border-slate-100 space-y-2 text-xs">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Hospital:</span>
                    <span className="font-bold text-slate-800">{selectedHospital.name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Scheduled Visit Time:</span>
                    <span className="font-bold text-emerald-600">{bookingDate || "Today"} at {bookingTime || "10:30 AM"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Booking Reference:</span>
                    <span className="font-mono font-bold text-slate-800">DH-BK-98421</span>
                  </div>
                </div>

                <button type="button" onClick={closeSuccessModal} className="w-full py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs transition">
                  Done &amp; Return to Overview
                </button>
              </div>
            </div>
          )}

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

          {/* ===== Toast Notification ===== */}
          {activeNav === "setting" && (
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

          {/* ===== Appointment View (New Design) ===== */}
          {activeNav === "appointment" && (
            <div data-purpose="appointment-view" className="flex-1 min-h-0 overflow-y-auto">
              <div className="space-y-6 pb-6">

                {/* Top Title & Quick Metrics Banner */}
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-slate-200">
                  <div>
                    <div className="flex items-center space-x-3">
                      <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">Appointments</h1>
                      <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200">
                        3 Scheduled
                      </span>
                    </div>
                    <p className="text-xs sm:text-sm text-slate-500 mt-1">
                      Review scheduled consultations, prepare for visits, and sync with your calendar.
                    </p>
                  </div>
                  <div className="flex items-center space-x-3">
                    <button type="button" className="inline-flex items-center space-x-2 px-3.5 py-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-medium shadow-xs transition">
                      <svg className="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      <span>Sync iCal / Google</span>
                    </button>
                    <button type="button" onClick={() => openAppointmentModal("book")} className="inline-flex items-center space-x-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold shadow-sm transition">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2.2} viewBox="0 0 24 24">
                        <path d="M12 4v16m8-8H4" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      <span>Schedule Visit</span>
                    </button>
                  </div>
                </div>

                {/* Metric Overview Stat Cards */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {/* Next Visit */}
                  <div className="bg-white p-4 rounded-2xl border border-slate-200/90 card-shadow flex items-center space-x-3.5">
                    <div className="w-12 h-12 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center flex-shrink-0">
                      <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    <div>
                      <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Next Appointment</p>
                      <h4 className="text-base font-bold text-slate-900 mt-0.5">Tomorrow, 10:30 AM</h4>
                      <span className="text-[11px] text-emerald-600 font-medium">In-Person • Apex Heart</span>
                    </div>
                  </div>

                  {/* Telehealth */}
                  <div className="bg-white p-4 rounded-2xl border border-slate-200/90 card-shadow flex items-center space-x-3.5">
                    <div className="w-12 h-12 rounded-xl bg-teal-50 text-teal-600 flex items-center justify-center flex-shrink-0">
                      <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    <div>
                      <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Virtual Follow-up</p>
                      <h4 className="text-base font-bold text-slate-900 mt-0.5">Oct 18, 2:00 PM</h4>
                      <span className="text-[11px] text-teal-600 font-medium">Video Call • Dr. S. Jenkins</span>
                    </div>
                  </div>
                </div>

                {/* Main Layout: 2 Columns */}
                <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">

                  {/* Left: Tabs & Appointment Cards */}
                  <div className="xl:col-span-2 space-y-5">

                    {/* Tabs & Filters */}
                    <div className="bg-white p-3.5 rounded-2xl border border-slate-200/90 card-shadow flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div className="flex items-center space-x-1 p-1 bg-slate-100 rounded-xl overflow-x-auto">
                        {([
                          { id: "upcoming" as const, label: "Upcoming (3)" },
                          { id: "past" as const, label: "Past (8)" },
                          { id: "cancelled" as const, label: "Cancelled" },
                        ]).map((tab) => (
                          <button
                            key={tab.id}
                            type="button"
                            data-purpose={`appointment-tab-${tab.id}`}
                            onClick={() => setAppointmentTab(tab.id)}
                            className={`px-3.5 py-1.5 rounded-lg text-xs whitespace-nowrap transition ${appointmentTab === tab.id ? "font-semibold bg-white text-slate-800 shadow-xs" : "font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-200/60"}`}
                          >
                            {tab.label}
                          </button>
                        ))}
                      </div>
                      <div className="flex items-center space-x-2">
                        <select className="text-xs bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1.5 text-slate-700 focus:ring-emerald-500 focus:border-emerald-500 font-medium">
                          <option>All Types (Virtual &amp; In-Person)</option>
                          <option>In-Person Hospital</option>
                          <option>AI / Video Telehealth</option>
                          <option>Diagnostic &amp; Labs</option>
                        </select>
                        <select className="text-xs bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1.5 text-slate-700 focus:ring-emerald-500 focus:border-emerald-500 font-medium">
                          <option>Sort by: Earliest</option>
                          <option>Sort by: Latest</option>
                          <option>Doctor Name</option>
                        </select>
                      </div>
                    </div>

                    {appointmentTab === "upcoming" && (
                      <>
                        {/* Card 1: Dr. Marcus Vance */}
                        <div data-purpose="appointment-card-1" className={`bg-white rounded-2xl border p-4 card-shadow flex items-center justify-between ${highlightTarget === "appointment-card-1" ? "border-emerald-500 ring-2 ring-emerald-200" : "border-slate-200"}`}>
                          <div className="flex items-center space-x-4">
                            <div className="w-10 h-10 rounded-xl bg-emerald-50 border border-emerald-100 text-emerald-600 flex items-center justify-center font-bold text-sm flex-shrink-0">DR</div>
                            <div>
                              <h4 className="text-sm font-bold text-slate-900">Dr. Marcus Vance, MD</h4>
                              <p className="text-xs text-slate-500 mt-0.5">Apex Heart &amp; Health Institute</p>
                              <div className="flex items-center space-x-4 mt-1 text-xs text-slate-500">
                                <span>Tomorrow, 10:30 AM</span>
                                <span>3.2 miles</span>
                                <span>Est. 12 min drive</span>
                              </div>
                            </div>
                          </div>
                          <button type="button" onClick={() => openAppointmentModal("reschedule", "Dr. Marcus Vance")} className="px-3.5 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-lg transition flex-shrink-0">
                            Reschedule
                          </button>
                        </div>

                        {/* Card 2: Dr. Sarah Jenkins */}
                        <div data-purpose="appointment-card-2" className={`bg-white rounded-2xl border p-4 card-shadow flex items-center justify-between ${highlightTarget === "appointment-card-2" ? "border-emerald-500 ring-2 ring-emerald-200" : "border-slate-200"}`}>
                          <div className="flex items-center space-x-4">
                            <div className="w-10 h-10 rounded-xl bg-teal-50 border border-teal-100 text-teal-600 flex items-center justify-center font-bold text-sm flex-shrink-0">SJ</div>
                            <div>
                              <h4 className="text-sm font-bold text-slate-900">Dr. Sarah Jenkins, MD</h4>
                              <p className="text-xs text-slate-500 mt-0.5">ENDOD Secure Telehealth Video Room</p>
                              <div className="flex items-center space-x-4 mt-1 text-xs text-slate-500">
                                <span>Oct 18, 2:00 PM</span>
                                <span>Virtual</span>
                                <span>No travel needed</span>
                              </div>
                            </div>
                          </div>
                          <button type="button" onClick={() => openAppointmentModal("reschedule", "Dr. Sarah Jenkins")} className="px-3.5 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-lg transition flex-shrink-0">
                            Reschedule
                          </button>
                        </div>

                        {/* Card 3: City Care Diagnostics */}
                        <div data-purpose="appointment-card-3" className={`bg-white rounded-2xl border p-4 card-shadow flex items-center justify-between ${highlightTarget === "appointment-card-3" ? "border-emerald-500 ring-2 ring-emerald-200" : "border-slate-200"}`}>
                          <div className="flex items-center space-x-4">
                            <div className="w-10 h-10 rounded-xl bg-blue-50 border border-blue-100 text-blue-600 flex items-center justify-center font-bold text-sm flex-shrink-0">CC</div>
                            <div>
                              <h4 className="text-sm font-bold text-slate-900">City Care Diagnostics &amp; Pathology Center</h4>
                              <p className="text-xs text-slate-500 mt-0.5">Suite 200, Metro Health Tower, 450 Medical Blvd</p>
                              <div className="flex items-center space-x-4 mt-1 text-xs text-slate-500">
                                <span>Oct 28, 8:00 AM</span>
                                <span>5.0 miles</span>
                                <span>Est. 18 min drive</span>
                              </div>
                            </div>
                          </div>
                          <button type="button" onClick={() => openAppointmentModal("reschedule", "City Care Diagnostics")} className="px-3.5 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-lg transition flex-shrink-0">
                            Reschedule
                          </button>
                        </div>
                      </>
                    )}

                    {appointmentTab === "past" && (
                      <div data-purpose="appointment-past-list" className="space-y-3">
                        <div data-purpose="past-card-1" className="bg-white rounded-2xl border border-slate-200 p-4 card-shadow flex items-center justify-between">
                          <div className="flex items-center space-x-4">
                            <div className="w-10 h-10 rounded-xl bg-emerald-50 border border-emerald-100 text-emerald-600 flex items-center justify-center font-bold text-sm flex-shrink-0">AI</div>
                            <div>
                              <h4 className="text-sm font-bold text-slate-900">ENDOD AI Emergency Live Consultation</h4>
                              <p className="text-xs text-slate-500 mt-0.5">Virtual • ENDOD Telehealth Room</p>
                              <div className="flex items-center space-x-4 mt-1 text-xs text-slate-500">
                                <span>Oct 11, 10:24 AM</span>
                                <span>Virtual</span>
                                <span>No travel needed</span>
                              </div>
                            </div>
                          </div>
                          <span className="px-3 py-1 text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg flex-shrink-0">Completed</span>
                        </div>
                        <div data-purpose="past-card-2" className="bg-white rounded-2xl border border-slate-200 p-4 card-shadow flex items-center justify-between">
                          <div className="flex items-center space-x-4">
                            <div className="w-10 h-10 rounded-xl bg-emerald-50 border border-emerald-100 text-emerald-600 flex items-center justify-center font-bold text-sm flex-shrink-0">DR</div>
                            <div>
                              <h4 className="text-sm font-bold text-slate-900">Dr. Marcus Vance, MD</h4>
                              <p className="text-xs text-slate-500 mt-0.5">Apex Heart &amp; Health Institute</p>
                              <div className="flex items-center space-x-4 mt-1 text-xs text-slate-500">
                                <span>Aug 24, 9:00 AM</span>
                                <span>3.2 miles</span>
                                <span>Est. 12 min drive</span>
                              </div>
                            </div>
                          </div>
                          <span className="px-3 py-1 text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg flex-shrink-0">Completed</span>
                        </div>
                      </div>
                    )}

                    {appointmentTab === "cancelled" && (
                      <div data-purpose="appointment-cancelled-list" className="space-y-3">
                        <div data-purpose="cancelled-card-1" className={`bg-white rounded-2xl border p-4 card-shadow flex items-center justify-between opacity-60 ${highlightTarget === "cancelled-card-1" ? "border-emerald-500 ring-2 ring-emerald-200" : "border-slate-200"}`}>
                          <div className="flex items-center space-x-4">
                            <div className="w-10 h-10 rounded-xl bg-slate-50 border border-slate-200 text-slate-400 flex items-center justify-center font-bold text-sm flex-shrink-0">SJ</div>
                            <div>
                              <h4 className="text-sm font-bold text-slate-900">Dr. Sarah Jenkins, MD</h4>
                              <p className="text-xs text-slate-500 mt-0.5">ENDOD Secure Telehealth Video Room</p>
                              <div className="flex items-center space-x-4 mt-1 text-xs text-slate-500">
                                <span>Oct 10, 2:00 PM</span>
                                <span>Virtual</span>
                                <span>No travel needed</span>
                              </div>
                            </div>
                          </div>
                          <span className="px-3 py-1 text-xs font-semibold text-rose-700 bg-rose-50 border border-rose-200 rounded-lg flex-shrink-0">Cancelled</span>
                        </div>
                      </div>
                    )}

                  </div>

                  {/* Right: Calendar & Widgets */}
                  <div className="space-y-5">

                    {/* Mini Calendar */}
                    <div className="bg-white rounded-2xl border border-slate-200/90 p-5 card-shadow">
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-sm font-bold text-slate-900">October 2026</h3>
                        <div className="flex items-center space-x-1">
                          <button type="button" className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d="M15 19l-7-7 7-7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                          </button>
                          <button type="button" className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                          </button>
                        </div>
                      </div>

                      <div className="grid grid-cols-7 text-center text-[11px] font-semibold text-slate-400 mb-2">
                        <div>Su</div><div>Mo</div><div>Tu</div><div>We</div><div>Th</div><div>Fr</div><div>Sa</div>
                      </div>

                      <div className="grid grid-cols-7 gap-1 text-center text-xs">
                        {["27","28","29","30"].map(d => <span key={d} className="text-slate-300 p-2">{d}</span>)}
                        {Array.from({length: 31}, (_, i) => i + 1).map((d) => {
                          const isToday = d === 12;
                          const isTelehealth = d === 18;
                          const isLab = d === 28;
                          const isPast = d === 11;
                          let cls = "p-2 text-slate-700 hover:bg-slate-100 rounded-lg cursor-pointer";
                          if (isToday) cls = "p-2 rounded-lg bg-emerald-600 text-white font-bold relative shadow-xs cursor-pointer ring-2 ring-emerald-300 ring-offset-1";
                          else if (isTelehealth) cls = "p-2 rounded-lg bg-teal-100 text-teal-800 font-bold relative cursor-pointer";
                          else if (isLab) cls = "p-2 rounded-lg bg-blue-100 text-blue-800 font-bold relative cursor-pointer";
                          else if (isPast) cls = "p-2 rounded-lg bg-slate-100 text-slate-600 font-bold relative cursor-pointer";
                          return (
                            <span key={d} className={cls}>
                              {d}
                              {(isToday || isTelehealth || isLab) && <span className="absolute -bottom-1 left-1/2 transform -translate-x-1/2 w-1 h-1 bg-white rounded-full"></span>}
                            </span>
                          );
                        })}
                      </div>

                      <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
                        <div className="flex items-center space-x-1.5">
                          <span className="w-2.5 h-2.5 rounded-full bg-emerald-600"></span>
                          <span>In-Person</span>
                        </div>
                        <div className="flex items-center space-x-1.5">
                          <span className="w-2.5 h-2.5 rounded-full bg-teal-500"></span>
                          <span>Telehealth</span>
                        </div>
                        <div className="flex items-center space-x-1.5">
                          <span className="w-2.5 h-2.5 rounded-full bg-blue-500"></span>
                          <span>Diagnostics</span>
                        </div>
                      </div>
                    </div>

                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ===== Appointment Booking Modal ===== */}
          {showAppointmentModal && (
            <div data-purpose="appointment-modal" className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
              <div className="bg-white rounded-3xl max-w-lg w-full p-6 shadow-2xl border border-slate-200">
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div className="flex items-center space-x-2.5">
                    <div className="w-9 h-9 rounded-xl bg-emerald-100 text-emerald-700 flex items-center justify-center">
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="text-base font-bold text-slate-900">
                        {appointmentModalMode === "reschedule" ? `Reschedule with ${appointmentModalProvider}` : "Schedule an Appointment"}
                      </h3>
                      <p className="text-xs text-slate-500">Select date, time, and preferred care format</p>
                    </div>
                  </div>
                  <button type="button" onClick={closeAppointmentModal} className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                </div>

                {showAppointmentSuccess ? (
                  <div data-purpose="appointment-modal-success" className="mt-4 p-4 rounded-2xl bg-emerald-50 border border-emerald-200 text-center">
                    <div className="w-10 h-10 rounded-full bg-emerald-600 text-white flex items-center justify-center mx-auto mb-2">
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                        <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    <h4 className="text-sm font-bold text-emerald-900">Appointment Confirmed!</h4>
                    <p className="text-xs text-emerald-700 mt-1">Calendar invitation sent to everett@healthmail.com</p>
                  </div>
                ) : (
                  <form onSubmit={handleAppointmentSubmit} className="mt-4 space-y-4">
                    <div>
                      <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Provider / Specialty</label>
                      <select value={appointmentFormProvider} onChange={(e) => setAppointmentFormProvider(e.target.value)} className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800 focus:bg-white focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 font-medium">
                        <option>Dr. Marcus Vance, MD (Cardiology) • Apex Heart</option>
                        <option>Dr. Sarah Jenkins, MD (Internal Medicine) • Primary Care</option>
                        <option>City Care Diagnostics (Lab &amp; Imaging)</option>
                        <option>Dr. Elena Rostova (Pulmonology)</option>
                      </select>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Date</label>
                        <input type="date" value={appointmentFormDate} onChange={(e) => setAppointmentFormDate(e.target.value)} className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800 focus:bg-white focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 font-medium" />
                      </div>
                      <div>
                        <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Time Slot</label>
                        <select value={appointmentFormTime} onChange={(e) => setAppointmentFormTime(e.target.value)} className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800 focus:bg-white focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 font-medium">
                          <option>09:30 AM – 10:15 AM</option>
                          <option>11:00 AM – 11:45 AM</option>
                          <option>02:00 PM – 02:45 PM</option>
                          <option>04:15 PM – 05:00 PM</option>
                        </select>
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Appointment Type</label>
                      <div className="grid grid-cols-2 gap-2">
                        <label className={`flex items-center space-x-2 p-2.5 rounded-xl border cursor-pointer ${appointmentFormType === "in-person" ? "border-emerald-500 bg-emerald-50/50" : "border-slate-200 hover:bg-slate-50"}`}>
                          <input type="radio" name="apptVisitType" checked={appointmentFormType === "in-person"} onChange={() => setAppointmentFormType("in-person")} className="text-emerald-600 focus:ring-emerald-500" />
                          <span className="text-xs font-bold text-emerald-900">In-Person Facility</span>
                        </label>
                        <label className={`flex items-center space-x-2 p-2.5 rounded-xl border cursor-pointer ${appointmentFormType === "telehealth" ? "border-emerald-500 bg-emerald-50/50" : "border-slate-200 hover:bg-slate-50"}`}>
                          <input type="radio" name="apptVisitType" checked={appointmentFormType === "telehealth"} onChange={() => setAppointmentFormType("telehealth")} className="text-emerald-600 focus:ring-emerald-500" />
                          <span className="text-xs font-medium text-slate-700">Video Telehealth</span>
                        </label>
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Symptoms or Visit Notes</label>
                      <textarea rows={2} value={appointmentFormNotes} onChange={(e) => setAppointmentFormNotes(e.target.value)} placeholder="Briefly describe what you'd like to discuss or check..." className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-800 focus:bg-white focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500" />
                    </div>

                    <div className="pt-2 flex items-center justify-end space-x-3">
                      <button type="button" onClick={closeAppointmentModal} className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl transition">
                        Cancel
                      </button>
                      <button type="submit" className="px-5 py-2 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-xl shadow-sm transition">
                        {appointmentModalMode === "reschedule" ? "Confirm Reschedule" : "Confirm Booking"}
                      </button>
                    </div>
                  </form>
                )}
              </div>
            </div>
          )}

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

          {/* ===== Notification View (New Design) ===== */}
          {activeNav === "message" && (
            <div data-purpose="notification-view" className="flex-1 min-h-0 overflow-y-auto">
              <div className="max-w-5xl mx-auto w-full space-y-6 pb-6">

                {/* Page Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-6 border-b border-slate-200/80 gap-4">
                  <div>
                    <div className="flex items-center space-x-2">
                      <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">Notifications</h1>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${allRead ? "bg-slate-100 text-slate-500 border-slate-200" : "bg-emerald-50 text-emerald-700 border-emerald-200"}`}>
                        {allRead ? "0 unread" : "4 unread"}
                      </span>
                    </div>
                    <p className="text-xs sm:text-sm text-slate-500 mt-1">Appointment updates, medical record releases, and messages from your care team.</p>
                  </div>
                  <div className="flex items-center space-x-2.5">
                    <button type="button" onClick={markAllRead} className="inline-flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg transition-colors shadow-xs">
                      <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      <span>Mark all as read</span>
                    </button>
                  </div>
                </div>

                {/* Category Filter Pills */}
                <div className="flex items-center space-x-2 overflow-x-auto pb-2">
                  {([
                    { id: "all" as const, label: "All (11)" },
                    { id: "appointments" as const, label: "Appointments (5)" },
                    { id: "records" as const, label: "Medical Records (3)" },
                    { id: "messages" as const, label: "Messages (3)" },
                  ]).map((pill) => (
                    <button
                      key={pill.id}
                      type="button"
                      data-purpose={`notif-filter-${pill.id}`}
                      onClick={() => setNotifFilter(pill.id)}
                      className={`px-3.5 py-1.5 rounded-full text-xs whitespace-nowrap transition flex items-center space-x-1.5 ${notifFilter === pill.id ? "font-semibold bg-emerald-600 text-white shadow-xs" : "font-medium bg-white text-slate-600 hover:bg-slate-50 border border-slate-200"}`}
                    >
                      <span>{pill.label}</span>
                    </button>
                  ))}
                </div>

                {/* Grouped Notification Sections */}
                {NOTIF_GROUPS.filter((g) => notifFilter === "all" || notifFilter === g.id).map((group) => {
                  const visible = group.items.filter((n) => !dismissedNotifs.includes(n.id));
                  return (
                    <section key={group.id} data-purpose={`notif-group-${group.id}`} className="space-y-3">
                      <div className="flex items-center justify-between text-xs font-semibold text-slate-400 uppercase tracking-wider px-1">
                        <span className="flex items-center space-x-2 text-slate-500">
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                            <path d={group.iconPath} strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                          <span>{group.title}</span>
                        </span>
                        <span className="text-[11px] font-normal lowercase">{visible.length} notification{visible.length === 1 ? "" : "s"}</span>
                      </div>

                      <div className="space-y-2.5">
                        {visible.map((n) => (
                          <article
                            key={n.id}
                            data-purpose={`notif-${n.id}`}
                            onClick={() => group.nav && openNotifTarget(group.nav, n)}
                            className={`bg-white rounded-xl border p-4 sm:p-5 card-shadow transition relative ${group.nav ? "cursor-pointer hover:border-emerald-300 hover:shadow-md" : "hover:border-slate-300"} ${n.unread && !allRead ? "border-slate-300" : "border-slate-200/90"}`}
                          >
                            <div className="flex items-start space-x-3 sm:space-x-4">
                              <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 ${group.iconWrap}`}>
                                <svg className={`w-5 h-5 ${group.iconColor}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d={group.iconPath} strokeLinecap="round" strokeLinejoin="round" /></svg>
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="flex items-center space-x-2 flex-wrap">
                                    <span className={`text-xs font-medium px-2 py-0.5 rounded border ${n.typeClass}`}>{n.type}</span>
                                    <h3 className="text-xs sm:text-sm font-semibold text-slate-900">{n.title}</h3>
                                  </div>
                                  <div className="flex items-center space-x-2 flex-shrink-0">
                                    <time className="text-[11px] text-slate-400">{n.time}</time>
                                    {n.unread && !allRead && <span className="w-2 h-2 rounded-full bg-emerald-600" title="Unread"></span>}
                                  </div>
                                </div>
                                <p className="text-xs sm:text-sm text-slate-600 mt-1.5 leading-relaxed">{n.body}</p>
                                <div className="mt-3 pt-3 border-t border-slate-100 flex flex-wrap items-center justify-between gap-2.5">
                                  <div className="flex items-center space-x-3 text-xs text-slate-500">
                                    <span className="inline-flex items-center text-slate-600">{n.meta}</span>
                                  </div>
                                  <div className="flex items-center space-x-2">
                                    <button type="button" onClick={(e) => { e.stopPropagation(); dismissNotification(n.id); }} className="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded transition">Dismiss</button>
                                    {group.nav && (
                                      <span className="inline-flex items-center space-x-1 px-3 py-1.5 text-xs font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 rounded-lg transition">
                                        <span>{n.action}</span>
                                        <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2.2} viewBox="0 0 24 24"><path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                                      </span>
                                    )}
                                  </div>
                                </div>
                              </div>
                            </div>
                          </article>
                        ))}
                      </div>
                    </section>
                  );
                })}
              </div>
            </div>
          )}

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
