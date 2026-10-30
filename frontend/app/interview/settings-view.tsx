"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, passwordProblem } from "../lib/api";
import {
  BLOOD_TYPES, formatPhoneDisplay, invalidateHealthCard, splitAllergies, type ProfileForCard,
} from "../health-card/health-card-data";
import { useI18n, type TranslationKey } from "../lib/i18n";
import { Bone, FieldBones, Skeleton } from "../components/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";

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

const COUNTRIES: { value: string; labelKey: TranslationKey }[] = [
  { value: "ET", labelKey: "settings.country.ET" },
  { value: "KE", labelKey: "settings.country.KE" },
  { value: "DJ", labelKey: "settings.country.DJ" },
  { value: "ER", labelKey: "settings.country.ER" },
  { value: "SO", labelKey: "settings.country.SO" },
  { value: "SD", labelKey: "settings.country.SD" },
  { value: "SS", labelKey: "settings.country.SS" },
  { value: "UG", labelKey: "settings.country.UG" },
  { value: "TZ", labelKey: "settings.country.TZ" },
];
const DEFAULT_RADIUS_KM = 15;
// The backend accepts 1-200 km.
const RADIUS_MIN_KM = 5;
const RADIUS_MAX_KM = 200;

const inputClass = "w-full text-sm rounded-xl border-slate-300 focus:border-emerald-500 focus:ring-black py-2.5 px-3.5 shadow-xs text-slate-900 border";
const labelClass = "block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1.5";
const saveClass = "px-5 py-2.5 bg-black hover:bg-gray-800 disabled:opacity-60 text-white font-semibold text-xs sm:text-sm rounded-xl shadow-sm transition-all";

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

/** Strength labels, weakest first; the index is the score. */
const STRENGTH_LABEL_KEYS: TranslationKey[] = [
  "settings.password.strength.none",
  "settings.password.strength.weak",
  "settings.password.strength.fair",
  "settings.password.strength.good",
  "settings.password.strength.strong",
];
const STRENGTH_COLORS = ["text-slate-400", "text-rose-500", "text-amber-500", "text-black", "text-black"];
const STRENGTH_BARS = ["bg-slate-200", "bg-rose-500", "bg-amber-500", "bg-black", "bg-gray-500"];

/** Account settings (GET/PATCH /users/me, preferences, consent, health profile; password change). */
export default function SettingsView({ onToast, onProfileChange }: Props) {
  const { t } = useI18n();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  // Personal information
  const [firstName, setFirstName] = useState("");
  const [middleName, setMiddleName] = useState("");
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
    setMiddleName(p.middle_name ?? "");
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
      setHealthError(error instanceof ApiError && error.status === 403 ? "" : message(error, t("settings.card.loadError")));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is stable per language
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
        if (!cancelled) setLoadError(message(error, t("settings.error.load")));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is stable per language
  }, [applyProfile, loadHealth]);

  const saveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("profile");
    try {
      const updated = await api<Profile>("users/me", {
        method: "PATCH",
        body: { first_name: firstName.trim(), middle_name: middleName.trim() || null, last_name: lastName.trim(), email: email.trim() || null },
      });
      setProfile(updated);
      applyPersonal(updated);
      onProfileChange(updated);
      invalidateHealthCard();
      onToast(t("settings.toast.profileSavedTitle"), t("settings.toast.profileSaved"));
    } catch (error) {
      onToast(t("common.couldNotSave"), message(error, t("settings.toast.checkDetails")));
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
        radiusSaved ? t("settings.toast.locationUpdatedTitle") : t("settings.toast.partlySavedTitle"),
        radiusSaved ? t("settings.toast.locationUpdated") : t("settings.toast.partlySaved"),
      );
    } catch (error) {
      onToast(t("common.couldNotSave"), message(error, t("settings.toast.checkDetails")));
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
    if (!response.ok || !data.ok) throw new ApiError(data.error ?? t("common.somethingWrong"), response.status);
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
      setPhoneError(message(error, t("settings.toast.sendCodeFailed")));
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
      invalidateHealthCard();
      setPhoneStep("idle");
      onToast(t("settings.toast.phoneVerifiedTitle"), t("settings.toast.phoneVerified"));
    } catch (error) {
      setPhoneError(message(error, t("settings.toast.confirmFailed")));
    } finally {
      setBusy(null);
    }
  };

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    const problem = passwordProblem(newPassword);
    if (problem) {
      onToast(t("settings.toast.passwordErrorTitle"), problem);
      return;
    }
    if (newPassword !== confirmPassword) {
      onToast(t("settings.toast.mismatchTitle"), t("settings.toast.mismatch"));
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
      if (!response.ok || !data.ok) throw new ApiError(data.error ?? t("settings.toast.changePasswordFailed"), response.status);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      onToast(t("settings.toast.passwordUpdatedTitle"), t("settings.toast.passwordUpdated"));
    } catch (error) {
      onToast(t("settings.toast.passwordErrorTitle"), message(error, t("settings.toast.changePasswordFailed")));
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
      invalidateHealthCard();
      setProfile((p) => (p ? { ...p, consent: { ...p.consent, ...consent } } : p));
      if (field === "treatment_processing") {
        if (value) {
          await loadHealth();
        } else {
          applyHealth({ blood_type: null, allergies: [], emergency_contact_name: null, emergency_contact_phone: null });
          setHealth(null);
          onToast(
            t("settings.toast.consentWithdrawnTitle"),
            t("settings.toast.consentWithdrawn"),
          );
        }
      }
    } catch (error) {
      setProfile(previous);
      onToast(t("common.couldNotUpdate"), message(error, t("common.pleaseTryAgain")));
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
      onToast(t("common.couldNotUpdate"), message(error, t("common.pleaseTryAgain")));
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
          allergies: splitAllergies(allergies),
          emergency_contact_name: emergencyName.trim() || null,
          emergency_contact_phone: emergencyPhone.trim() || null,
        },
      });
      applyHealth(updated);
      invalidateHealthCard();
      onToast(t("settings.toast.cardUpdatedTitle"), t("settings.toast.cardUpdated"));
    } catch (error) {
      onToast(t("common.couldNotSave"), message(error, t("settings.toast.checkDetails")));
    } finally {
      setBusy(null);
    }
  };

  if (!profile) {
    return (
      <div data-purpose="settings-view" className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
        <div className="max-w-5xl mx-auto py-6">
          {loadError ? <p className="text-sm text-red-600" role="alert">{loadError}</p> : (
            <Skeleton className="space-y-6" label={t("settings.loading")}>
              {[3, 2, 2].map((fields, section) => (
                <div className="bg-white rounded-2xl border border-slate-200 p-5 sm:p-7 space-y-5" key={section}>
                  <Bone className="h-4 w-40 rounded" />
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                    {Array.from({ length: fields }, (_, i) => <FieldBones key={i} />)}
                  </div>
                </div>
              ))}
            </Skeleton>
          )}
        </div>
      </div>
    );
  }

  const score = strength(newPassword);
  const requirements = [
    { id: "req-length", label: t("settings.password.req.length"), met: newPassword.length >= 10 },
    { id: "req-upper", label: t("settings.password.req.upper"), met: /[A-Z]/.test(newPassword) },
    { id: "req-lower", label: t("settings.password.req.lower"), met: /[a-z]/.test(newPassword) },
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
        className="mt-1 h-4 w-4 accent-black flex-shrink-0"
      />
    </label>
  );

  return (
    <div data-purpose="settings-view" className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
      <div className="max-w-5xl mx-auto space-y-6 py-6">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 pb-2">
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">{t("settings.title")}</h1>
            </div>
        </div>

        {/* Personal information */}
        <section data-purpose="user-profile-section" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-4">
            <div>
              <h2 className="text-lg font-bold text-slate-900">{t("settings.personal.title")}</h2>
              <p className="text-xs sm:text-sm text-slate-500">{t("settings.personal.subtitle")}</p>
            </div>
            <span className="self-start sm:self-auto px-3 py-1 bg-gray-50 text-gray-900 text-xs font-semibold rounded-full border border-gray-200">
              {profile.dedan_user_id}
            </span>
          </div>
          <form onSubmit={saveProfile} className="space-y-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label className={labelClass} htmlFor="first-name">{t("settings.personal.firstName")}</label>
                <input id="first-name" required maxLength={60} type="text" value={firstName} onChange={(e) => setFirstName(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="middle-name">{t("settings.personal.middleName")}</label>
                <input id="middle-name" maxLength={60} type="text" value={middleName} onChange={(e) => setMiddleName(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="last-name">{t("settings.personal.lastName")}</label>
                <input id="last-name" required maxLength={60} type="text" value={lastName} onChange={(e) => setLastName(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="patient-id-field">{t("settings.personal.dedanId")}</label>
                <input id="patient-id-field" readOnly type="text" value={profile.dedan_user_id} className="w-full text-sm rounded-xl bg-slate-50 border-slate-200 text-slate-500 py-2.5 px-3.5 cursor-not-allowed border" />
              </div>
              <div>
                <label className={labelClass} htmlFor="email-address">{t("settings.personal.email")}</label>
                <input id="email-address" type="email" maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="phone-number">{t("settings.personal.phone")}</label>
                <div className="relative">
                  <input id="phone-number" readOnly type="tel" value={profile.phone ? formatPhoneDisplay(profile.phone) : ""} placeholder={t("settings.personal.noPhone")} className="w-full text-sm rounded-xl bg-slate-50 border-slate-200 text-slate-600 py-2.5 px-3.5 pr-24 border" />
                  {profile.phone && (
                    <span data-purpose="phone-status" className={`absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] font-semibold px-2 py-0.5 rounded-md ${phoneVerified ? "text-black bg-gray-50" : "text-amber-700 bg-amber-50"}`}>
                      {phoneVerified ? t("settings.personal.verified") : t("settings.personal.notVerified")}
                    </span>
                  )}
                </div>
                {phoneStep === "idle" && (
                  <button type="button" data-purpose="change-phone" onClick={() => { setPhoneStep("number"); setNewPhone(""); setPhoneError(""); }} className="mt-1.5 text-[11px] font-semibold text-gray-900 hover:underline">
                    {profile.phone ? (phoneVerified ? t("settings.personal.changeNumber") : t("settings.personal.verifyNumber")) : t("settings.personal.addPhone")}
                  </button>
                )}
              </div>
            </div>
            {phoneStep !== "idle" && (
              <div data-purpose="phone-change" className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-3">
                <p className="text-xs text-slate-600">
                  {t("settings.personal.phoneHint")}
                </p>
                {phoneStep === "number" ? (
                  <div className="flex gap-2">
                    <input id="new-phone" type="tel" maxLength={32} value={newPhone} onChange={(e) => setNewPhone(e.target.value)} placeholder="09XXXXXXXX" className={inputClass} />
                    <button type="button" disabled={busy !== null || !newPhone.trim()} onClick={() => void sendPhoneCode()} className={saveClass}>{t("settings.personal.sendCode")}</button>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <input id="phone-code" inputMode="numeric" maxLength={6} value={phoneCode} onChange={(e) => setPhoneCode(e.target.value.replace(/\D/g, ""))} placeholder={t("settings.personal.codePlaceholder")} className={inputClass} />
                    <button type="button" disabled={busy !== null || phoneCode.length !== 6} onClick={() => void confirmPhone()} className={saveClass}>{t("common.confirm")}</button>
                  </div>
                )}
                {phoneError && <p data-purpose="phone-error" className="text-xs text-red-600" role="alert">{phoneError}</p>}
                <button type="button" onClick={() => setPhoneStep("idle")} className="text-[11px] text-slate-500 hover:underline">{t("common.cancel")}</button>
              </div>
            )}
            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
              <button type="submit" disabled={busy !== null} className={saveClass}>{t("settings.personal.saveChanges")}</button>
            </div>
          </form>
        </section>

        {/* Location */}
        <section data-purpose="location-settings-section" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
          <div className="border-b border-slate-100 pb-4">
            <h2 className="text-lg font-bold text-slate-900">{t("settings.location.title")}</h2>
            <p className="text-xs sm:text-sm text-slate-500">{t("settings.location.subtitle")}</p>
          </div>
          <form onSubmit={saveLocation} className="space-y-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div className="md:col-span-2">
                <label className={labelClass} htmlFor="address-line">{t("settings.location.address")}</label>
                <input id="address-line" maxLength={200} type="text" value={address} onChange={(e) => setAddress(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="city">{t("settings.location.city")}</label>
                <input id="city" maxLength={100} type="text" value={city} onChange={(e) => setCity(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="state">{t("settings.location.region")}</label>
                <input id="state" maxLength={100} type="text" value={region} onChange={(e) => setRegion(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="zipcode">{t("settings.location.postalCode")}</label>
                <input id="zipcode" maxLength={20} type="text" value={postalCode} onChange={(e) => setPostalCode(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass} htmlFor="country">{t("settings.location.country")}</label>
                <Select value={country} onValueChange={setCountry}>
                  <SelectTrigger className="w-full text-lg" id="country">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {COUNTRIES.map((c) => (
                      <SelectItem key={c.value} value={c.value}>
                        {t(c.labelKey)}
                      </SelectItem>
                    ))}
                    {!COUNTRIES.some((c) => c.value === country) && (
                      <SelectItem value={country}>{country}</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="bg-slate-50/80 p-4 rounded-xl border border-slate-200">
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-bold uppercase tracking-wider text-slate-700" htmlFor="radius-slider">{t("settings.location.radius")}</label>
                <span className="text-xs font-semibold text-gray-900 bg-gray-100/70 px-2.5 py-0.5 rounded-full">{t("settings.location.within", { km: radius })}</span>
              </div>
              <input id="radius-slider" max={RADIUS_MAX_KM} min={RADIUS_MIN_KM} step={5} type="range" value={radius} onChange={(e) => setRadius(Number(e.target.value))} className="w-full accent-black h-2 bg-slate-200 rounded-lg cursor-pointer" />
              <div className="flex justify-between text-[11px] text-slate-400 mt-1">
                <span>{t("settings.location.within", { km: RADIUS_MIN_KM })}</span>
                <span>{t("settings.location.within", { km: 100 })}</span>
                <span>{t("settings.location.within", { km: RADIUS_MAX_KM })}</span>
              </div>
            </div>
            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
              <button type="submit" disabled={busy !== null} className={saveClass}>{t("settings.location.update")}</button>
            </div>
          </form>
        </section>

        {/* Privacy & notifications */}
        <section data-purpose="privacy-section" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7">
          <div className="border-b border-slate-100 pb-4 mb-2">
            <h2 className="text-lg font-bold text-slate-900">{t("settings.privacy.title")}</h2>
            <p className="text-xs sm:text-sm text-slate-500">{t("settings.privacy.subtitle")}</p>
          </div>
          {toggle("consent-health", profile.consent.treatment_processing, (v) => void setConsent("treatment_processing", v),
            t("settings.privacy.consentHealth.label"), t("settings.privacy.consentHealth.hint"))}
          {toggle("consent-sharing", profile.consent.data_sharing_with_clinicians, (v) => void setConsent("data_sharing_with_clinicians", v),
            t("settings.privacy.consentSharing.label"), t("settings.privacy.consentSharing.hint"))}
          {toggle("pref-sms", profile.preferences.sms_notifications, (v) => void setNotification("sms_notifications", v),
            t("settings.privacy.sms.label"), t("settings.privacy.sms.hint"))}
        </section>

        {/* Password */}
        <section data-purpose="security-settings-section" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
          <div className="border-b border-slate-100 pb-4">
            <h2 className="text-lg font-bold text-slate-900">{t("settings.password.title")}</h2>
            <p className="text-xs sm:text-sm text-slate-500">{t("settings.password.subtitle")}</p>
          </div>
          <form onSubmit={changePassword} className="space-y-5">
            <div>
              <label className={labelClass} htmlFor="current-password">{t("settings.password.current")}</label>
              <input id="current-password" autoComplete="current-password" required type={showPasswords ? "text" : "password"} value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} className={inputClass} />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label className={labelClass} htmlFor="new-password">{t("settings.password.new")}</label>
                <input id="new-password" autoComplete="new-password" required type={showPasswords ? "text" : "password"} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className={inputClass} />
                <div className="mt-2.5">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-slate-500">{t("settings.password.strength")}</span>
                    <span id="strength-label" className={`font-semibold ${STRENGTH_COLORS[score]}`}>{t(STRENGTH_LABEL_KEYS[score])}</span>
                  </div>
                  <div className="grid grid-cols-4 gap-1.5 h-1.5">
                    {[0, 1, 2, 3].map((i) => <div key={i} className={`rounded-full ${i < score ? STRENGTH_BARS[score] : "bg-slate-200"}`} />)}
                  </div>
                </div>
              </div>
              <div>
                <label className={labelClass} htmlFor="confirm-password">{t("settings.password.confirm")}</label>
                <input id="confirm-password" autoComplete="new-password" required type={showPasswords ? "text" : "password"} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className={inputClass} />
                {confirmPassword && (
                  <div id="match-indicator" className={`text-[11px] mt-1.5 font-semibold ${newPassword === confirmPassword ? "text-black" : "text-rose-500"}`}>
                    {newPassword === confirmPassword ? t("settings.password.match") : t("settings.password.noMatch")}
                  </div>
                )}
              </div>
            </div>
            <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 text-xs grid grid-cols-1 sm:grid-cols-3 gap-2">
              {requirements.map((req) => (
                <div key={req.id} data-purpose={req.id} data-met={req.met} className={`flex items-center gap-1.5 ${req.met ? "text-black" : "text-slate-400"}`}>
                  <span>{req.met ? "✓" : "•"}</span><span>{req.label}</span>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between gap-3 pt-3 border-t border-slate-100">
              <label className="flex items-center gap-2 text-xs text-slate-600">
                <input type="checkbox" checked={showPasswords} onChange={(e) => setShowPasswords(e.target.checked)} className="accent-black" />
                {t("settings.password.show")}
              </label>
              <button type="submit" disabled={busy !== null} className={saveClass}>{t("settings.password.update")}</button>
            </div>
          </form>
        </section>

        {/* Digital health card */}
        <section data-purpose="digital-card-section" className="bg-white rounded-2xl border border-slate-200 shadow-xs p-5 sm:p-7 space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-4">
            <div>
              <h2 className="text-lg font-bold text-slate-900">{t("settings.card.title")}</h2>
              <p className="text-xs sm:text-sm text-slate-500">{t("settings.card.subtitle")}</p>
            </div>
            <div className="flex gap-2 self-start sm:self-auto">
              <button type="button" onClick={() => setCardVisible(!cardVisible)} className="px-3.5 py-1.5 rounded-lg bg-gray-50 hover:bg-gray-100 text-gray-900 text-xs font-semibold border border-gray-200">
                {cardVisible ? t("settings.card.hidePreview") : t("settings.card.showPreview")}
              </button>
              <Link data-purpose="open-health-card" href="/health-card" className="px-3.5 py-1.5 rounded-lg bg-[#000000] hover:bg-[#174640] text-white text-xs font-semibold">
                {t("settings.card.open")}
              </Link>
            </div>
          </div>

          {cardVisible && (
            <div data-purpose="card-preview" className="relative bg-gradient-to-br from-[#1e3a2e] to-[#000000] rounded-2xl p-6 text-white overflow-hidden">
              <div className="relative mb-6"><span className="text-2xl font-extrabold tracking-tight">{t("common.endod")}</span></div>
              <div className="relative mb-4"><span className="text-xs font-semibold text-[#94e0c0] uppercase tracking-wider">{t("healthCard.digitalId")}</span></div>
              <h3 className="relative text-2xl font-bold font-serif text-white mb-1">{[firstName, lastName].filter(Boolean).join(" ") || "—"}</h3>
              <div className="relative mb-6"><span className="text-base font-semibold text-[#94e0c0]">{profile.dedan_user_id}</span></div>
              <div className="relative grid grid-cols-2 sm:grid-cols-4 gap-4">
                {[
                  [t("settings.card.phone"), profile.phone ? formatPhoneDisplay(profile.phone) : "—"],
                  [t("settings.card.bloodGroup"), bloodType || "—"],
                  [t("settings.card.allergies"), allergies || "—"],
                  [t("settings.card.emergency"), emergencyName || "—"],
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
              {t("settings.card.needsConsent")}
            </p>
          ) : (
            <form onSubmit={saveCard} className="space-y-5">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <div>
                  <label className={labelClass} htmlFor="blood-group">{t("settings.card.bloodGroupLabel")}</label>
                  <Select value={bloodType === "" ? "none" : bloodType} onValueChange={(v) => setBloodType(v === "none" ? "" : v)}>
                    <SelectTrigger className="w-full text-lg" id="blood-group">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">{t("settings.card.notSpecified")}</SelectItem>
                      {BLOOD_TYPES.map((b) => (
                        <SelectItem key={b} value={b}>{b}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className={labelClass} htmlFor="allergies">{t("settings.card.allergiesLabel")}</label>
                  <input id="allergies" type="text" maxLength={300} value={allergies} onChange={(e) => setAllergies(e.target.value)} placeholder={t("settings.card.allergiesPlaceholder")} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass} htmlFor="emergency-contact">{t("settings.card.emergencyName")}</label>
                  <input id="emergency-contact" maxLength={120} type="text" value={emergencyName} onChange={(e) => setEmergencyName(e.target.value)} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass} htmlFor="emergency-phone">{t("settings.card.emergencyPhone")}</label>
                  <input id="emergency-phone" maxLength={32} type="tel" value={emergencyPhone} onChange={(e) => setEmergencyPhone(e.target.value)} placeholder="09XXXXXXXX" className={inputClass} />
                </div>
              </div>
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
                <button type="submit" disabled={busy !== null} className={saveClass}>{t("settings.card.save")}</button>
              </div>
            </form>
          )}
        </section>
      </div>
    </div>
  );
}
