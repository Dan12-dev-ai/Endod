"use client";

import { useState } from "react";
import { useSession } from "../../../lib/session";
import BookingView from "../../booking-view";
import type { BookingPreset } from "../../history-data";
import { BOOKING_PRESET_KEY, useMobileToast } from "../../mobile-shell";

/** "Book now" on a follow-up (Medical records) leaves the hospital and day here. */
function readPreset(): BookingPreset | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(BOOKING_PRESET_KEY);
    const preset = raw ? (JSON.parse(raw) as BookingPreset) : null;
    return preset && typeof preset.hospitalId === "string" && typeof preset.date === "string" ? preset : null;
  } catch {
    return null;
  }
}

export default function MobileBookingPage() {
  const session = useSession();
  const onToast = useMobileToast();
  const [preset, setPreset] = useState<BookingPreset | null>(readPreset);
  const presetUsed = () => {
    setPreset(null);
    try {
      window.sessionStorage.removeItem(BOOKING_PRESET_KEY);
    } catch {
      // ignore
    }
  };
  const patientId = session.status === "signed-in" ? session.profile.dedan_user_id : "";
  return <BookingView hideTitle onPresetUsed={presetUsed} onToast={onToast} patientId={patientId} preset={preset} />;
}
