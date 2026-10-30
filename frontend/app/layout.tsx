import type { Metadata } from "next";
import { I18nProvider, LANGUAGE_INIT_SCRIPT } from "./lib/i18n";
import { ThemeProvider } from "./lib/theme";
import "./globals.css";

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
      className="h-full antialiased"
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
{/* Applies the stored theme to <html> before the first paint. */}
        <script dangerouslySetInnerHTML={{ __html: `(function(){try{var t=localStorage.getItem('theme')||'light';var d=t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);if(d)document.documentElement.classList.add('dark');}catch(e){}})();` }} />
<ThemeProvider>
          <I18nProvider>{children}</I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
