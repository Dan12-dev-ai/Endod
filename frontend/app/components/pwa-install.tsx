"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useEffect, useState, useSyncExternalStore } from "react";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
};

function isIosSafari() {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  const isIos = /iPad|iPhone|iPod/.test(ua);
  const isStandalone = (navigator as any).standalone === true;
  return isIos && !isStandalone;
}

function isStandaloneMode() {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    (window.navigator as any).standalone === true
  );
}

export default function PwaInstallButton() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(() =>
    typeof window === "undefined"
      ? null
      : ((window as any).__pwaDeferredPrompt as BeforeInstallPromptEvent | null) ?? null,
  );
  const isClient = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const [bottomMode, setBottomMode] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.sessionStorage.getItem("pwa-install-bottom") === "1";
  });

  const dismissFloating = () => {
    setBottomMode(true);
    try {
      window.sessionStorage.setItem("pwa-install-bottom", "1");
    } catch {
      // ignore
    }
  };
  const [installed, setInstalled] = useState<boolean>(() => isStandaloneMode());
  const [open, setOpen] = useState(false);

  const [ios] = useState<boolean>(() => isIosSafari());

  useEffect(() => {
    if (typeof window === "undefined") return;

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }

    if (typeof navigator !== "undefined" && "getInstalledRelatedApps" in navigator) {
      (navigator as any)
        .getInstalledRelatedApps()
        .then((apps: any[]) => {
          if (Array.isArray(apps) && apps.length > 0) setInstalled(true);
        })
        .catch(() => undefined);
    }

    const onBeforeInstallPrompt = (event: Event) => {
      event.preventDefault();
      (window as any).__pwaDeferredPrompt = event;
      setDeferred(event as BeforeInstallPromptEvent);
    };
    const onAppInstalled = () => {
      setInstalled(true);
      setDeferred(null);
      (window as any).__pwaDeferredPrompt = null;
      setOpen(false);
    };

    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt);
    window.addEventListener("appinstalled", onAppInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt);
      window.removeEventListener("appinstalled", onAppInstalled);
    };
  }, []);

  if (!isClient || installed) return null;

  const handleInstall = async () => {
    const promptEvent =
      deferred ?? ((window as any).__pwaDeferredPrompt as BeforeInstallPromptEvent | null);
    if (promptEvent) {
      try {
        await promptEvent.prompt();
        await promptEvent.userChoice;
      } finally {
        setDeferred(null);
        (window as any).__pwaDeferredPrompt = null;
        setOpen(false);
      }
      return;
    }
    setOpen(true);
  };

  return (
    <>
      {!open && !installed && (
        <div className={bottomMode ? "fixed bottom-4 right-4 z-[60]" : "fixed top-4 inset-x-0 z-[60] flex justify-center px-4"}>
        <div className="inline-flex items-center gap-1 rounded-full bg-orange-500 text-white pl-4 pr-2 py-2 text-sm font-semibold shadow-lg">
          <button
            type="button"
            onClick={() => {
              if (deferred || (window as any).__pwaDeferredPrompt) {
                void handleInstall();
              } else {
                setOpen(true);
              }
            }}
            className="inline-flex items-center gap-2 hover:opacity-80 transition-opacity"
            aria-label="Install app"
            data-purpose="pwa-install"
            data-testid="install-app"
            id="pwa-install-button"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14" />
            </svg>
            Install app
          </button>
          {!bottomMode && (
            <button
              type="button"
              onClick={dismissFloating}
            aria-label="Dismiss install prompt"
            className="p-1 text-white/70 hover:text-white rounded-full hover:bg-white/10 transition"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          )}
        </div>
        </div>
      )}

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="pwa-install-popup-title"
          data-purpose="pwa-install-popup"
          data-testid="pwa-install-popup"
          id="pwa-install-popup"
          className="fixed inset-0 z-[70] flex items-end sm:items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs"
          onClick={() => setOpen(false)}
        >
          <div
            className="bg-white rounded-2xl max-w-sm w-full p-6 shadow-2xl border border-slate-200"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 mb-3">
              <h3 id="pwa-install-popup-title" className="text-lg font-bold text-slate-900">
                Install Endod Health
              </h3>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setOpen(false)}
                className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path d="M6 18L18 6M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
            <p className="text-sm text-slate-600 mb-5">
              {deferred
                ? "Install the app for faster access and offline support."
                : ios
                ? 'On iPhone/iPad: tap the Share button, then choose "Add to Home Screen".'
                : "If Endod Health is already installed, open it from your home screen. Otherwise, use your browser menu to install or add this app."}
            </p>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition"
              >
                Not now
              </button>
              {deferred ? (
                <button
                  type="button"
                  onClick={handleInstall}
                  className="px-4 py-2 text-sm font-semibold text-white bg-orange-500 hover:bg-orange-600 rounded-lg transition"
                  data-purpose="pwa-install"
                  data-testid="install-app"
                  id="pwa-install-button"
                >
                  Install app
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="px-4 py-2 text-sm font-semibold text-white bg-orange-500 hover:bg-orange-600 rounded-lg transition"
                >
                  Got it
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
