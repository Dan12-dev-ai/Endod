"use client";

// Emergency: call an ambulance first, then the nearest hospitals that have
// one. Everything here is a phone call or a directions link, so it works on
// any phone, with or without the map.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { RowBones, Skeleton } from "../components/skeleton";
import HospitalMap, { type MapPoint } from "./hospital-map";

type National = { service: "ambulance" | "police" | "fire"; number: string; label: string };
type EmergencyHospital = {
  hospital_id: string; name: string; name_am: string | null; city: string | null; address: string | null;
  ambulance_phone: string | null; phone: string | null; emergency: boolean;
  latitude: number; longitude: number; distance_km: number | null;
};
type Emergency = { national: National[]; hospitals: EmergencyHospital[]; location_used: boolean };

/** A phone number as a tel: link (digits and a leading +). */
export function telHref(number: string): string {
  return `tel:${number.replace(/[^\d+]/g, "")}`;
}

/** Google Maps directions to a place; works on any phone without an API key. */
export function directionsHref(latitude: number, longitude: number): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${latitude},${longitude}`;
}

export default function EmergencyPanel({ onClose }: { onClose: () => void }) {
  const { t, language } = useI18n();
  const [data, setData] = useState<Emergency | null>(null);
  const [error, setError] = useState("");
  const [locating, setLocating] = useState(false);
  const [here, setHere] = useState<{ latitude: number; longitude: number } | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const latest = useRef(0);

  const load = useCallback(async (coords?: { latitude: number; longitude: number }) => {
    const request = ++latest.current;
    try {
      const result = await api<Emergency>("users/me/care/emergency", { query: coords ?? {} });
      if (request !== latest.current) return; // a newer request (with a location) is under way
      setData(result);
      setError("");
    } catch (err) {
      if (request !== latest.current) return;
      setError(err instanceof ApiError ? err.message : t("emergency.error"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is stable per language
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void load();
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab" || !dialogRef.current) return;
      // Keep Tab inside the dialog.
      const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
      ));
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const inside = dialogRef.current.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || !inside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !inside)) {
        event.preventDefault();
        first.focus();
      }
    };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      opener?.focus(); // back to the Emergency button
    };
  }, [load, onClose]);

  const locate = () => {
    if (!navigator.geolocation) {
      setError(t("emergency.noLocation"));
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const coords = { latitude: position.coords.latitude, longitude: position.coords.longitude };
        setHere(coords);
        setLocating(false);
        void load(coords);
      },
      () => {
        setLocating(false);
        setError(t("emergency.locationDenied"));
      },
      { timeout: 10_000, maximumAge: 60_000, enableHighAccuracy: true },
    );
  };

  const ambulance = data?.national.find((n) => n.service === "ambulance");
  const points: MapPoint[] = useMemo(() => (data?.hospitals ?? []).map((h) => ({
    id: h.hospital_id, latitude: h.latitude, longitude: h.longitude, label: h.name,
  })), [data]);

  return createPortal(
    <div
      aria-labelledby="emergency-title"
      aria-modal="true"
      className="fixed inset-0 z-[90] bg-slate-900/60 backdrop-blur-sm flex items-end sm:items-center justify-center"
      data-purpose="emergency-panel"
      onClick={onClose}
      role="dialog"
    >
      <div
        className="bg-white w-full sm:max-w-lg max-h-[92vh] overflow-y-auto rounded-t-3xl sm:rounded-3xl p-5 sm:p-6 space-y-5"
        onClick={(event) => event.stopPropagation()}
        ref={dialogRef}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-extrabold text-red-700" id="emergency-title">{t("emergency.title")}</h2>
            <p className="text-xs text-slate-500 mt-1">{t("emergency.subtitle")}</p>
          </div>
          <button
            aria-label={t("common.close")}
            className="p-2 rounded-lg text-slate-500 hover:bg-slate-100"
            onClick={onClose}
            ref={closeRef}
            type="button"
          >
            <svg aria-hidden className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>

        {/* The one thing to do first. */}
        <a
          className="flex items-center justify-center gap-3 w-full rounded-2xl bg-red-600 hover:bg-red-700 text-white py-4 text-lg font-extrabold shadow-lg"
          data-purpose="call-ambulance"
          href={telHref(ambulance?.number ?? "907")}
        >
          <svg aria-hidden className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
            <path d="M6.6 10.8a15.1 15.1 0 006.6 6.6l2.2-2.2a1 1 0 011-.25 11.4 11.4 0 003.6.57 1 1 0 011 1V20a1 1 0 01-1 1A17 17 0 013 4a1 1 0 011-1h3.5a1 1 0 011 1 11.4 11.4 0 00.57 3.6 1 1 0 01-.25 1z" />
          </svg>
          {t("emergency.callAmbulance", { number: ambulance?.number ?? "907" })}
        </a>

        <div className="grid grid-cols-2 gap-2">
          {(data?.national ?? []).filter((n) => n.service !== "ambulance").map((n) => (
            <a
              className="rounded-xl border border-slate-200 py-2.5 text-center text-sm font-semibold text-slate-700 hover:bg-slate-50"
              data-purpose={`call-${n.service}`}
              href={telHref(n.number)}
              key={n.service}
            >
              {t(n.service === "police" ? "emergency.police" : "emergency.fire")} · {n.number}
            </a>
          ))}
        </div>

        <section className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-bold text-slate-900">{t("emergency.nearby")}</h3>
            <button
              className="text-xs font-semibold text-emerald-700 hover:underline disabled:opacity-60"
              data-purpose="emergency-locate"
              disabled={locating}
              onClick={locate}
              type="button"
            >
              {locating ? t("emergency.locating") : data?.location_used ? t("emergency.updateLocation") : t("emergency.useLocation")}
            </button>
          </div>
          {error && <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">{error}</p>}
          <HospitalMap points={points} here={here} />
          {!data && !error && (
            <Skeleton className="space-y-2" label={t("common.loading")}>
              <RowBones />
              <RowBones />
            </Skeleton>
          )}
          {data && data.hospitals.length === 0 && (
            <p className="text-xs text-slate-500" data-purpose="emergency-none">{t("emergency.noHospitals")}</p>
          )}
          {data?.hospitals.map((h) => (
            <div className="rounded-2xl border border-slate-200 p-3.5" data-purpose={`emergency-hospital-${h.hospital_id}`} key={h.hospital_id}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-bold text-slate-900">{language === "am" && h.name_am ? h.name_am : h.name}</p>
                  <p className="text-xs text-slate-500">
                    {[h.address, h.city].filter(Boolean).join(", ")}
                    {h.distance_km !== null ? ` · ${h.distance_km} km` : ""}
                  </p>
                </div>
                {h.emergency && <span className="text-[10px] font-bold text-red-700 bg-red-50 rounded px-1.5 py-0.5">{t("emergency.er24")}</span>}
              </div>
              <div className="flex flex-wrap gap-2 mt-3">
                {h.ambulance_phone && (
                  <a className="px-3 py-1.5 rounded-lg bg-red-50 text-red-700 text-xs font-bold border border-red-100" href={telHref(h.ambulance_phone)}>
                    {t("emergency.callTheirAmbulance")} · {h.ambulance_phone}
                  </a>
                )}
                {h.phone && (
                  <a className="px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-semibold text-slate-700" href={telHref(h.phone)}>
                    {t("emergency.callHospital")}
                  </a>
                )}
                <a
                  className="px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-semibold text-slate-700"
                  href={directionsHref(h.latitude, h.longitude)}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  {t("emergency.directions")}
                </a>
              </div>
            </div>
          ))}
        </section>
      </div>
    </div>,
    document.body,
  );
}
