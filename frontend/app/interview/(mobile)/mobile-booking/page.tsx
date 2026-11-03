"use client";

import { useState } from "react";
import { useSession } from "../../../lib/session";
import BookingView from "../../mobile-booking-view";

export default function MobileBookingPage() {
  const session = useSession();
  const [toast, setToast] = useState<{ title: string; message: string } | null>(null);

  const showToast = (title: string, message: string) => {
    setToast({ title, message });
    setTimeout(() => setToast(null), 3000);
  };

  if (session.status === "loading") {
    return <p className="text-sm text-slate-500">Loading…</p>;
  }

  const patientId = session.status === "signed-in" ? session.profile.dedan_user_id : "";

  return (
    <>
      <BookingView patientId={patientId} onToast={showToast} hideTitle />
      {toast && (
        <div className="fixed top-5 right-5 z-50 flex items-center gap-3 bg-black text-white px-5 py-3.5 rounded-xl shadow-xl border border-black" role="alert">
          <div>
            <h5 className="text-xs font-semibold text-white tracking-wide uppercase">{toast.title}</h5>
            <p className="text-xs text-slate-300">{toast.message}</p>
          </div>
        </div>
      )}
    </>
  );
}
