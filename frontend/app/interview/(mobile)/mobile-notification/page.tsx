"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import MobileNotificationsView from "../../mobile-notifications-view";

export default function MobileNotificationPage() {
  const router = useRouter();
  const [toast, setToast] = useState<{ title: string; message: string } | null>(null);

  const showToast = (title: string, message: string) => {
    setToast({ title, message });
    setTimeout(() => setToast(null), 3000);
  };

  const onOpen = (nav: string, target: string | null) => {
    if (nav === "booking") router.push("/interview/mobile-booking");
    else if (nav === "appointment") router.push("/interview/mobile-appointment");
    else router.push("/interview");
  };

  return (
    <>
      <MobileNotificationsView onOpen={onOpen} onToast={showToast} />
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
