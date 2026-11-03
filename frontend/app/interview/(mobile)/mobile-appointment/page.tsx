"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import MobileAppointmentsView from "../../mobile-appointments-view";

export default function MobileAppointmentPage() {
  const router = useRouter();
  const [toast, setToast] = useState<{ title: string; message: string } | null>(null);

  const showToast = (title: string, message: string) => {
    setToast({ title, message });
    setTimeout(() => setToast(null), 3000);
  };

  return (
    <>
      <MobileAppointmentsView
        highlightTarget={null}
        onToast={showToast}
        onBook={() => router.push("/interview/mobile-booking")}
      />
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
