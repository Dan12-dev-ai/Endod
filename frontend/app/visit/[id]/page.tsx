"use client";

// A video visit, inside Endod: the call runs on Endod's own Jitsi server and
// is embedded here, so the patient never leaves the app. The backend hands
// out a short-lived token for this patient's own approved visit, around its
// time; the Jitsi server admits only token holders.

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/app/lib/api";
import { useI18n } from "@/app/lib/i18n";

type Join = { domain: string; room: string; jwt: string; url: string };

/* eslint-disable @typescript-eslint/no-explicit-any -- Jitsi's script defines this global at run time */
type JitsiWindow = Window & { JitsiMeetExternalAPI?: any };

const DOMAIN = /^[a-z0-9.-]+$/i;

function loadJitsi(domain: string): Promise<void> {
  const w = window as JitsiWindow;
  if (w.JitsiMeetExternalAPI) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://${domain}/external_api.js`;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("The video service could not be reached."));
    document.head.appendChild(script);
  });
}

export default function VisitPage() {
  const { t, language } = useI18n();
  const box = useRef<HTMLDivElement>(null);
  const call = useRef<any>(null);
  const [error, setError] = useState("");
  const [state, setState] = useState<"connecting" | "in-call" | "ended">("connecting");

  useEffect(() => {
    let cancelled = false;
    const id = decodeURIComponent(window.location.pathname.split("/")[2] ?? "");
    (async () => {
      try {
        const join = await api<Join>(`users/me/appointments/${encodeURIComponent(id)}/video`, { method: "POST" });
        if (!DOMAIN.test(join.domain)) throw new Error("Bad video address.");
        await loadJitsi(join.domain);
        if (cancelled || !box.current) return;
        const JitsiMeetExternalAPI = (window as JitsiWindow).JitsiMeetExternalAPI;
        call.current = new JitsiMeetExternalAPI(join.domain, {
          roomName: join.room,
          jwt: join.jwt,
          parentNode: box.current,
          width: "100%",
          height: "100%",
          lang: language === "am" ? "am" : "en",
          configOverwrite: { prejoinConfig: { enabled: true }, disableDeepLinking: true },
          interfaceConfigOverwrite: { MOBILE_APP_PROMO: false },
        });
        call.current.addListener?.("videoConferenceJoined", () => setState("in-call"));
        call.current.addListener?.("readyToClose", () => {
          setState("ended");
          call.current?.dispose?.();
        });
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError || err instanceof Error ? err.message : t("visit.error"));
      }
    })();
    return () => {
      cancelled = true;
      call.current?.dispose?.();
      call.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- join once
  }, []);

  return (
    <main className="w-full h-screen flex flex-col bg-slate-950 text-white" data-purpose="visit-page">
      <header className="flex items-center justify-between px-4 py-3 border-b border-white/10">
        <p className="text-sm font-semibold">{t("visit.title")}</p>
        <a className="px-3 py-1.5 rounded-lg border border-white/30 text-xs font-semibold hover:bg-white/10" data-purpose="visit-leave" href="/interview">
          {state === "ended" ? t("visit.back") : t("visit.leave")}
        </a>
      </header>
      {error ? (
        <div className="flex-1 flex flex-col items-center justify-center p-6 text-center gap-4" data-purpose="visit-error" role="alert">
          <p className="text-base font-semibold">{error}</p>
          <a className="px-4 py-2 rounded-xl bg-white text-slate-900 text-sm font-semibold" href="/interview">{t("visit.back")}</a>
        </div>
      ) : state === "ended" ? (
        <div className="flex-1 flex items-center justify-center p-6 text-center" data-purpose="visit-ended">
          <p className="text-base font-semibold">{t("visit.ended")}</p>
        </div>
      ) : (
        <div className="flex-1 relative">
          {state === "connecting" && (
            <p className="absolute inset-0 flex items-center justify-center text-sm text-white/70" role="status">{t("visit.connecting")}</p>
          )}
          <div className="absolute inset-0" data-purpose="visit-frame" ref={box} />
        </div>
      )}
    </main>
  );
}
