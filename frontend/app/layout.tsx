import type { Metadata } from "next";
import { Suspense } from "react";
import { Newsreader, Plus_Jakarta_Sans } from "next/font/google";
import { I18nProvider, LANGUAGE_INIT_SCRIPT } from "./lib/i18n";
import "./globals.css";
import PwaInstallButton from "./components/pwa-install";


const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  display: "swap",
});

const plusJakartaSans = Plus_Jakarta_Sans({
  variable: "--font-plus-jakarta-sans",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Endod Health OS | Patients & Hospitals, Connected",
  description:
    "Endod Health OS — understand your symptoms, reach the right hospital faster, and arrive with a clear record. You stay in control of your health data.",
  manifest: "/manifest.webmanifest",
  themeColor: "#000000",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Endod Health",
  },
  icons: {
    icon: "/favicon.ico",
    apple: "/apple-touch-icon.png",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${newsreader.variable} ${plusJakartaSans.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        {/* Captures the PWA install prompt as early as possible, before React hydrates. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              `(function(){if(typeof window==="undefined")return;window.addEventListener("beforeinstallprompt",function(e){try{e.preventDefault();}catch(_){}window.__pwaDeferredPrompt=e;});})();`,
          }}
        />
        {/* Applies the stored language to <html lang> before the first paint. */}
        <script dangerouslySetInnerHTML={{ __html: LANGUAGE_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">
        <I18nProvider>{children}</I18nProvider>
        {/* It reads the path: outside Suspense, pages like /card/[id] cannot be prerendered. */}
        <Suspense fallback={null}>
          <PwaInstallButton />
        </Suspense>
      </body>
    </html>
  );
}
