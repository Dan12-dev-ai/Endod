"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, passwordProblem } from "../lib/api";
import { formatPhoneDisplay, type ProfileForCard } from "../health-card/health-card-data";

type Profile = ProfileForCard & {
  email: string | null;
  phone_verified: boolean;
  address_line: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country_code: string | null;
  preferences: {
    email_notifications: boolean;
    sms_notifications: boolean;
    care_search_radius_km: number | null;
  };
  consent: {
    treatment_processing: boolean;
    data_sharing_with_clinicians: boolean;
  };
};

type HealthProfile = {
  blood_type: string | null;
  allergies: string[];
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
};

type Props = {
  onToast: (title: string, message: string) => void;
  /** The profile changed (names, phone): refresh the header and card. */
  onProfileChange: (profile: ProfileForCard) => void;
};

const COUNTRIES = [
  { value: "ET", label: "Ethiopia" },
  { value: "KE", label: "Kenya" },
  { value: "DJ", label: "Djibouti" },
  { value: "ER", label: "Eritrea" },
  { value: "SO", label: "Somalia" },
  { value: "SD", label: "Sudan" },
  { value: "SS", label: "South Sudan" },
  { value: "UG", label: "Uganda" },
  { value: "TZ", label: "Tanzania" },
];
const BLOOD_TYPES = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"];
const DEFAULT_RADIUS_KM = 15;
// The backend accepts 1-200 km.
const RADIUS_MIN_KM = 5;
const RADIUS_MAX_KM = 200;

const inputClass = "w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-emerald-500 py-2.5 px-3.5 shadow-xs text-slate-900 border";
const labelClass = "block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5";
const saveClass = "px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white font-semibold text-xs sm:text-sm rounded-xl shadow-sm transition-all";

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function strength(password: string): number {
  let score = 0;
  if (password.length >= 10) score++;
  if (/[A-Z]/.test(password) && /[a-z]/.test(password)) score++;
  if (/[0-9]/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;
  return score;
}

const STRENGTH_LABELS = ["None", "Weak", "Fair", "Good", "Strong"];
const STRENGTH_COLORS = ["text-slate-400", "text-rose-500", "text-amber-500", "text-teal-600", "text-emerald-600"];
const STRENGTH_BARS = ["bg-slate-200", "bg-rose-500", "bg-amber-500", "bg-teal-500", "bg-emerald-500"];

/** Account settings (GET/PATCH /users/me, preferences, consent, health profile; password change). */
export default function SettingsView({ onToast, onProfileChange }: Props) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  // Personal information
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  // Phone: changed only by confirming the new number with an SMS code.
  const [phoneStep, setPhoneStep] = useState<"idle" | "number" | "code">("idle");
  const [newPhone, setNewPhone] = useState("");
  const [phoneCode, setPhoneCode] = useState("");
  const [phoneError, setPhoneError] = useState("");
  // Location
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [region, setRegion] = useState("");
  const [postalCode, setPostalCode] = useState("");
  const [country, setCountry] = useState("ET");
  const [radius, setRadius] = useState(15);
  // Password
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPasswords, setShowPasswords] = useState(false);
  // Health card
  const [health, setHealth] = useState<HealthProfile | null>(null);
  const [healthError, setHealthError] = useState("");
  const [cardVisible, setCardVisible] = useState(false);
  const [bloodType, setBloodType] = useState("");
  const [allergies, setAllergies] = useState("");
  const [emergencyName, setEmergencyName] = useState("");
  const [emergencyPhone, setEmergencyPhone] = useState("");

  // Each section's form is filled from the server separately, so saving one
  // section never discards unsaved edits in another.
  const applyPersonal = useCallback((p: Profile) => {
    setFirstName(p.first_name ?? "");
    setLastName(p.last_name ?? "");
    setEmail(p.email ?? "");
  }, []);
  const applyLocation = useCallback((p: Profile) => {
    setAddress(p.address_line ?? "");
    setCity(p.city ?? "");
    setRegion(p.region ?? "");
    setPostalCode(p.postal_code ?? "");
    setCountry(p.country_code ?? "ET");
    setRadius(p.preferences.care_search_radius_km ?? DEFAULT_RADIUS_KM);
  }, []);
  const applyProfile = useCallback((p: Profile) => {
    setProfile(p);
    applyPersonal(p);
    applyLocation(p);
  }, [applyPersonal, applyLocation]);

  const applyHealth = useCallback((h: HealthProfile) => {
    setHealth(h);
    setBloodType(h.blood_type ?? "");
    setAllergies(h.allergies.join(", "));
    setEmergencyName(h.emergency_contact_name ?? "");
    setEmergencyPhone(h.emergency_contact_phone ?? "");
  }, []);

  const loadHealth = useCallback(async () => {
    try {
      applyHealth(await api<HealthProfile>("users/me/health-profile"));
      setHealthError("");
    } catch (error) {
      setHealth(null);
      // 403 means no consent (the section says so); anything else is a failure.
      setHealthError(error instanceof ApiError && error.status === 403 ? "" : message(error, "Unable to load your health details."));
    }
  }, [applyHealth]);

  useEffect(() => {
    let cancelled = false;
    api<Profile>("users/me")
      .then((p) => {
        if (cancelled) return;
        applyProfile(p);
        if (p.consent.treatment_processing) void loadHealth();
      })
      .catch((error) => {
        if (!cancelled) setLoadError(message(error, "Unable to load your settings."));
      });
    return () => {
      cancelled = true;
    };
  }, [applyProfile, loadHealth]);

  const saveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("profile");
    try {
      const updated = await api<Profile>("users/me", {
        method: "PATCH",
        body: { first_name: firstName.trim(), last_name: lastName.trim(), email: email.trim() || null },
      });
      setProfile(updated);
      applyPersonal(updated);
      onProfileChange(updated);
      onToast("Profile Saved", "Your personal details were saved.");
    } catch (error) {
      onToast("Could not save", message(error, "Please check the details and try again."));
    } finally {
      setBusy(null);
    }
  };

  const saveLocation = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("location");
    try {
      const updated = await api<Profile>("users/me", {
        method: "PATCH",
        body: {
          address_line: address.trim() || null, city: city.trim() || null, region: region.trim() || null,
          postal_code: postalCode.trim() || null, country_code: country,
        },
      });
      setProfile(updated);
      let radiusSaved = true;
      if (radius !== (updated.preferences.care_search_radius_km ?? DEFAULT_RADIUS_KM)) {
        try {
          await api("users/me/preferences", { method: "PATCH", body: { care_search_radius_km: radius } });
          setProfile({ ...updated, preferences: { ...updated.preferences, care_search_radius_km: radius } });
        } catch {
          radiusSaved = false;
        }
      }
      onToast(
        radiusSaved ? "Location Updated" : "Partly saved",
        radiusSaved ? "Your location details were saved." : "Your address was saved, but the care radius was not. Please try again.",
      );
    } catch (error) {
      onToast("Could not save", message(error, "Please check the details and try again."));
    } finally {
      setBusy(null);
    }
  };

  /** POST to an /api/auth route handler; throws ApiError with its message. */
  const authCall = async (path: string, body: Record<string, unknown>) => {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new ApiError(data.error ?? "Something went wrong. Please try again.", response.status);
    return data;
  };

  const sendPhoneCode = async () => {
    setBusy("phone");
    setPhoneError("");
    try {
      await authCall("/api/auth/send-otp", { phone: newPhone.trim() });
      setPhoneCode("");
      setPhoneStep("code");
    } catch (error) {
      setPhoneError(message(error, "Unable to send the code."));
    } finally {
      setBusy(null);
    }
  };

  const confirmPhone = async () => {
    setBusy("phone");
    setPhoneError("");
    try {
      await authCall("/api/auth/verify-otp", { phone: newPhone.trim(), code: phoneCode });
      const linked = await authCall("/api/auth/link-phone", {});
      const updated = linked.profile as Profile;
      setProfile(updated);
      onProfileChange(updated);
      setPhoneStep("idle");
      onToast("Phone Verified", "You can now sign in and get reminders with this number.");
    } catch (error) {
      setPhoneError(message(error, "Unable to confirm the number."));
    } finally {
      setBusy(null);
    }
  };

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    const problem = passwordProblem(newPassword);
    if (problem) {
      onToast("Password Error", problem);
      return;
    }
    if (newPassword !== confirmPassword) {
      onToast("Mismatch", "Passwords do not match. Please re-enter.");
      return;
    }
    setBusy("password");
    try {
      // A route handler, not the proxy: it swaps the session cookie for the
      // new token, since the change signs out every older session.
      const response = await fetch("/api/auth/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ currentPassword, newPassword, newPasswordConfirmation: confirmPassword }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new ApiError(data.error ?? "Unable to change your password.", response.status);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      onToast("Password Updated", "Your password was changed. Other devices were signed out.");
    } catch (error) {
      onToast("Password Error", message(error, "Unable to change your password."));
    } finally {
      setBusy(null);
    }
  };

  // Toggles change at once and go back if the server refuses.
  const setConsent = async (field: "treatment_processing" | "data_sharing_with_clinicians", value: boolean) => {
    if (!profile) return;
    const previous = profile;
    setProfile({ ...profile, consent: { ...profile.consent, [field]: value } });
    setBusy(field);
    try {
      const consent = await api<Profile["consent"]>("users/me/consent", { method: "PATCH", body: { [field]: value } });
      setProfile((p) => (p ? { ...p, consent: { ...p.consent, ...consent } } : p));
      if (field === "treatment_processing") {
        if (value) {
          await loadHealth();
        } else {
          applyHealth({ blood_type: null, allergies: [], emergency_contact_name: null, emergency_contact_phone: null });
          setHealth(null);
          onToast(
            "Consent Withdrawn",
            "Endod won't store new health information. What you already saved is kept; contact support to have it deleted.",
          );
        }
      }
    } catch (error) {
      setProfile(previous);
      onToast("Could not update", message(error, "Please try again."));
    } finally {
      setBusy(null);
    }
  };

  const setNotification = async (field: "email_notifications" | "sms_notifications", value: boolean) => {
    if (!profile) return;
    const previous = profile;
    setProfile({ ...profile, preferences: { ...profile.preferences, [field]: value } });
    setBusy(field);
    try {
      const preferences = await api<Profile["preferences"]>("users/me/preferences", { method: "PATCH", body: { [field]: value } });
      setProfile((p) => (p ? { ...p, preferences: { ...p.preferences, ...preferences } } : p));
    } catch (error) {
      setProfile(previous);
      onToast("Could not update", message(error, "Please try again."));
    } finally {
      setBusy(null);
    }
  };

  const saveCard = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("card");
    try {
      const updated = await api<HealthProfile>("users/me/health-profile", {
        method: "PATCH",
        body: {
          blood_type: bloodType || null,
          allergies: allergies.split(",").map((a) => a.trim()).filter(Boolean),
          emergency_contact_name: emergencyName.trim() || null,
          emergency_contact_phone: emergencyPhone.trim() || null,
        },
      });
      applyHealth(updated);
      onToast("Card Updated", "Your health card details were saved.");
    } catch (error) {
      onToast("Could not save", message(error, "Please check the details and try again."));
    } finally {
      setBusy(null);
    }
  };

  if (!profile) {
    return (
      <div data-purpose="settings-view" className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-5xl mx-auto py-6">
          {loadError ? <p className="text-sm text-red-600" role="alert">{loadError}</p> : <p className="text-sm text-slate-500">Loading your settings...</p>}
        </div>
      </div>
    );
  }

  const score = strength(newPassword);
  const requirements = [
    { id: "req-length", label: "10+ Characters", met: newPassword.length >= 10 },
    { id: "req-upper", label: "Uppercase Letter", met: /[A-Z]/.test(newPassword) },
    { id: "req-lower", label: "Lowercase Letter", met: /[a-z]/.test(newPassword) },
  ];
  const phoneVerified = profile.phone_verified;
  const hasConsent = profile.consent.treatment_processing;

  const toggle = (id: string, checked: boolean, onChange: (value: boolean) => void, label: string, hint: string) => (
    <label key={id} className="flex items-start justify-between gap-4 py-3 border-b border-slate-100 last:border-0 cursor-pointer">
      <span>
        <span className="block text-sm font-semibold text-slate-800">{label}</span>
        <span className="block text-xs text-slate-500">{hint}</span>
      </span>
      <input
        type="checkbox"
        data-purpose={id}
        checked={checked}
        disabled={busy !== null}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1 h-4 w-4 accent-emerald-600 flex-shrink-0"
      />
    </label>
  );

  return (
    <div data-purpose="settings-view" className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-5xl mx-auto space-y-6 py-6">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 pb-2">
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">Account Settings</h1>
            <p className="text-sm text-slate-500 mt-1">Update your personal details, location, privacy choices and password.</p>
          </div>
        </div>

        {/* Personal information */}
        <section data-purpose="user-profile-section" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-4">
            <div>
              <h2 className="text-lg font-bold text-slate-900">Personal Information</h2>
              <p className="text-xs sm:text-sm text-slate-500">Your name, DEDAN ID and contact details.</p>
            </div>
            <span className="self-start sm:self-auto px-3 py-1 bg-emerald-50 text-emerald-700 text-xs font-semibold rounded-full border border-emerald-200">
              {profile.dedan_user_id}
            </span>
          </div>
          <form onSubmit={saveProfile} className="space-y-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label className={labelClass} htmlFor="first-name">First Name</label>
                <input id="first-name" required maxLength={60} type="text" value={firstName} onChange={(e) => setFirstName(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="last-name">Last Name</label>
                <input id="last-name" required maxLength={60} type="text" value={lastName} onChange={(e) => setLastName(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="patient-id-field">DEDAN ID</label>
                <input id="patient-id-field" readOnly type="text" value={profile.dedan_user_id} className="w-full text-sm rounded-xl bg-slate-50 border-slate-200 text-slate-500 py-2.5 px-3.5 cursor-not-allowed border" />
              </div>
              <div>
                <label className={labelClass} htmlFor="email-address">Email Address</label>
                <input id="email-address" type="email" maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="phone-number">Phone Number</label>
                <div className="relative">
                  <input id="phone-number" readOnly type="tel" value={profile.phone ? formatPhoneDisplay(profile.phone) : ""} placeholder="No phone yet" className="w-full text-sm rounded-xl bg-slate-50 border-slate-200 text-slate-600 py-2.5 px-3.5 pr-24 border" />
                  {profile.phone && (
                    <span data-purpose="phone-status" className={`absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] font-semibold px-2 py-0.5 rounded-md ${phoneVerified ? "text-emerald-600 bg-emerald-50" : "text-amber-700 bg-amber-50"}`}>
                      {phoneVerified ? "Verified" : "Not verified"}
                    </span>
                  )}
                </div>
                {phoneStep === "idle" && (
                  <button type="button" data-purpose="change-phone" onClick={() => { setPhoneStep("number"); setNewPhone(""); setPhoneError(""); }} className="mt-1.5 text-[11px] font-semibold text-emerald-700 hover:underline">
                    {profile.phone ? (phoneVerified ? "Change number" : "Verify a number") : "Add a phone number"}
                  </button>
                )}
              </div>
            </div>
            {phoneStep !== "idle" && (
              <div data-purpose="phone-change" className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-3">
                <p className="text-xs text-slate-600">
                  We&apos;ll text a code to the new number. Once confirmed, it replaces your current one for sign-in and reminders.
                </p>
                {phoneStep === "number" ? (
                  <div className="flex gap-2">
                    <input id="new-phone" type="tel" maxLength={32} value={newPhone} onChange={(e) => setNewPhone(e.target.value)} placeholder="09XXXXXXXX" className={inputClass} />
                    <button type="button" disabled={busy !== null || !newPhone.trim()} onClick={() => void sendPhoneCode()} className={saveClass}>Send code</button>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <input id="phone-code" inputMode="numeric" maxLength={6} value={phoneCode} onChange={(e) => setPhoneCode(e.target.value.replace(/\D/g, ""))} placeholder="6-digit code" className={inputClass} />
                    <button type="button" disabled={busy !== null || phoneCode.length !== 6} onClick={() => void confirmPhone()} className={saveClass}>Confirm</button>
                  </div>
                )}
                {phoneError && <p data-purpose="phone-error" className="text-xs text-red-600" role="alert">{phoneError}</p>}
                <button type="button" onClick={() => setPhoneStep("idle")} className="text-[11px] text-slate-500 hover:underline">Cancel</button>
              </div>
            )}
            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
              <button type="submit" disabled={busy !== null} className={saveClass}>Save Changes</button>
            </div>
          </form>
        </section>

        {/* Location */}
        <section data-purpose="location-settings-section" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
          <div className="border-b border-slate-100 pb-4">
            <h2 className="text-lg font-bold text-slate-900">Location &amp; Region</h2>
            <p className="text-xs sm:text-sm text-slate-500">Used to suggest nearby facilities and the right emergency numbers.</p>
          </div>
          <form onSubmit={saveLocation} className="space-y-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div className="md:col-span-2">
                <label className={labelClass} htmlFor="address-line">Street Address</label>
                <input id="address-line" maxLength={200} type="text" value={address} onChange={(e) => setAddress(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="city">City</label>
                <input id="city" maxLength={100} type="text" value={city} onChange={(e) => setCity(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="state">Region</label>
                <input id="state" maxLength={100} type="text" value={region} onChange={(e) => setRegion(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="zipcode">Postal Code</label>
                <input id="zipcode" maxLength={20} type="text" value={postalCode} onChange={(e) => setPostalCode(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="country">Country</label>
                <select id="country" value={country} onChange={(e) => setCountry(e.target.value)} className={inputClass}>
                  {COUNTRIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                  {!COUNTRIES.some((c) => c.value === country) && <option value={country}>{country}</option>}
                </select>
              </div>
            </div>
            <div className="bg-slate-50/80 p-4 rounded-xl border border-slate-200">
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-bold uppercase tracking-wider text-slate-700" htmlFor="radius-slider">Preferred Healthcare Radius</label>
                <span className="text-xs font-semibold text-emerald-700 bg-emerald-100/70 px-2.5 py-0.5 rounded-full">Within {radius} km</span>
              </div>
              <input id="radius-slider" max={RADIUS_MAX_KM} min={RADIUS_MIN_KM} step={5} type="range" value={radius} onChange={(e) => setRadius(Number(e.target.value))} className="w-full accent-emerald-600 h-2 bg-slate-200 rounded-lg cursor-pointer" />
              <div className="flex justify-between text-[11px] text-slate-400 mt-1">
                <span>{RADIUS_MIN_KM} km</span><span>100 km</span><span>{RADIUS_MAX_KM} km</span>
              </div>
            </div>
            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
              <button type="submit" disabled={busy !== null} className={saveClass}>Update Location</button>
            </div>
          </form>
        </section>

        {/* Privacy & notifications */}
        <section data-purpose="privacy-section" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7">
          <div className="border-b border-slate-100 pb-4 mb-2">
            <h2 className="text-lg font-bold text-slate-900">Privacy &amp; Notifications</h2>
            <p className="text-xs sm:text-sm text-slate-500">You decide what Endod stores and how it contacts you. You can change these at any time.</p>
          </div>
          {toggle("consent-health", profile.consent.treatment_processing, (v) => void setConsent("treatment_processing", v),
            "Store my health information", "Needed for your health profile, medical records, AI consultations and the health card details.")}
          {toggle("consent-sharing", profile.consent.data_sharing_with_clinicians, (v) => void setConsent("data_sharing_with_clinicians", v),
            "Share visit summaries with clinicians", "Only summaries you review and approve are ever shared.")}
          {toggle("pref-sms", profile.preferences.sms_notifications, (v) => void setNotification("sms_notifications", v),
            "SMS reminders", "Appointment reminders by text message to your verified phone.")}
        </section>

        {/* Password */}
        <section data-purpose="security-settings-section" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
          <div className="border-b border-slate-100 pb-4">
            <h2 className="text-lg font-bold text-slate-900">Password &amp; Security</h2>
            <p className="text-xs sm:text-sm text-slate-500">Changing your password signs out your other devices.</p>
          </div>
          <form onSubmit={changePassword} className="space-y-5">
            <div>
              <label className={labelClass} htmlFor="current-password">Current Password</label>
              <input id="current-password" autoComplete="current-password" required type={showPasswords ? "text" : "password"} value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} className={inputClass} />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label className={labelClass} htmlFor="new-password">New Password</label>
                <input id="new-password" autoComplete="new-password" required type={showPasswords ? "text" : "password"} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className={inputClass} />
                <div className="mt-2.5">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-slate-500">Strength:</span>
                    <span id="strength-label" className={`font-semibold ${STRENGTH_COLORS[score]}`}>{STRENGTH_LABELS[score]}</span>
                  </div>
                  <div className="grid grid-cols-4 gap-1.5 h-1.5">
                    {[0, 1, 2, 3].map((i) => <div key={i} className={`rounded-full ${i < score ? STRENGTH_BARS[score] : "bg-slate-200"}`} />)}
                  </div>
                </div>
              </div>
              <div>
                <label className={labelClass} htmlFor="confirm-password">Confirm New Password</label>
                <input id="confirm-password" autoComplete="new-password" required type={showPasswords ? "text" : "password"} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className={inputClass} />
                {confirmPassword && (
                  <div id="match-indicator" className={`text-[11px] mt-1.5 font-semibold ${newPassword === confirmPassword ? "text-emerald-600" : "text-rose-500"}`}>
                    {newPassword === confirmPassword ? "✓ Passwords match" : "✕ Passwords do not match"}
                  </div>
                )}
              </div>
            </div>
            <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 text-xs grid grid-cols-1 sm:grid-cols-3 gap-2">
              {requirements.map((req) => (
                <div key={req.id} data-purpose={req.id} className={`flex items-center gap-1.5 ${req.met ? "text-emerald-600" : "text-slate-400"}`}>
                  <span>{req.met ? "✓" : "•"}</span><span>{req.label}</span>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between gap-3 pt-3 border-t border-slate-100">
              <label className="flex items-center gap-2 text-xs text-slate-600">
                <input type="checkbox" checked={showPasswords} onChange={(e) => setShowPasswords(e.target.checked)} className="accent-emerald-600" />
                Show passwords
              </label>
              <button type="submit" disabled={busy !== null} className={saveClass}>Update Password</button>
            </div>
          </form>
        </section>

        {/* Digital health card */}
        <section data-purpose="digital-card-section" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-4">
            <div>
              <h2 className="text-lg font-bold text-slate-900">Digital Health Card</h2>
              <p className="text-xs sm:text-sm text-slate-500">Details shown on your Endod digital health card.</p>
            </div>
            <button type="button" onClick={() => setCardVisible(!cardVisible)} className="self-start sm:self-auto px-3.5 py-1.5 rounded-lg bg-emerald-50 hover:bg-emerald-100 text-emerald-700 text-xs font-semibold border border-emerald-200">
              {cardVisible ? "Hide Card Preview" : "Show Card Preview"}
            </button>
          </div>

          {cardVisible && (
            <div data-purpose="card-preview" className="relative bg-gradient-to-br from-[#1e3a2e] to-[#1e5852] rounded-2xl p-6 text-white overflow-hidden">
              <div className="relative mb-6"><span className="text-2xl font-extrabold tracking-tight">Endod</span></div>
              <div className="relative mb-4"><span className="text-xs font-semibold text-[#94e0c0] uppercase tracking-wider">Digital Health ID</span></div>
              <h3 className="relative text-2xl font-bold font-serif text-white mb-1">{[firstName, lastName].filter(Boolean).join(" ") || "—"}</h3>
              <div className="relative mb-6"><span className="text-base font-semibold text-[#94e0c0]">{profile.dedan_user_id}</span></div>
              <div className="relative grid grid-cols-2 sm:grid-cols-4 gap-4">
                {[
                  ["Phone", profile.phone ? formatPhoneDisplay(profile.phone) : "—"],
                  ["Blood Group", bloodType || "—"],
                  ["Allergies", allergies || "None"],
                  ["Emergency", emergencyName || "—"],
                ].map(([label, value]) => (
                  <div key={label}>
                    <span className="text-[10px] font-semibold text-[#94a3a8] uppercase tracking-wider">{label}</span>
                    <p className="text-sm font-semibold text-white mt-1">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {healthError ? (
            <p data-purpose="card-load-error" className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl p-3" role="alert">{healthError}</p>
          ) : !hasConsent || !health ? (
            <p data-purpose="card-needs-consent" className="text-xs text-slate-600 bg-slate-50 border border-slate-200 rounded-xl p-3">
              Blood group, allergies and emergency contact are health information. Turn on
              &quot;Store my health information&quot; above to add them.
            </p>
          ) : (
            <form onSubmit={saveCard} className="space-y-5">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <div>
                  <label className={labelClass} htmlFor="blood-group">Blood Group</label>
                  <select id="blood-group" value={bloodType} onChange={(e) => setBloodType(e.target.value)} className={inputClass}>
                    <option value="">Not specified</option>
                    {BLOOD_TYPES.map((b) => <option key={b} value={b}>{b}</option>)}
                  </select>
                </div>
                <div>
                  <label className={labelClass} htmlFor="allergies">Known Allergies</label>
                  <input id="allergies" type="text" value={allergies} onChange={(e) => setAllergies(e.target.value)} placeholder="e.g. Penicillin, Latex" className={inputClass} />
                </div>
                <div>
                  <label className={labelClass} htmlFor="emergency-contact">Emergency Contact Name</label>
                  <input id="emergency-contact" maxLength={120} type="text" value={emergencyName} onChange={(e) => setEmergencyName(e.target.value)} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass} htmlFor="emergency-phone">Emergency Contact Phone</label>
                  <input id="emergency-phone" maxLength={32} type="tel" value={emergencyPhone} onChange={(e) => setEmergencyPhone(e.target.value)} placeholder="09XXXXXXXX" className={inputClass} />
                </div>
              </div>
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
                <button type="submit" disabled={busy !== null} className={saveClass}>Save Card Details</button>
              </div>
            </form>
          )}
        </section>
      </div>
    </div>
  );
}
