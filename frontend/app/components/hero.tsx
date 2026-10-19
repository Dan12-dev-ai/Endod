"use client";

import Link from "next/link";
import { useI18n } from "../lib/i18n";
import { homeFor, useSession } from "../lib/session";

export default function Hero() {
  const { t } = useI18n();
  const session = useSession();
  // A signed-in patient goes straight to their dashboard (proxy.ts would
  // redirect /signup there anyway; this also says so on the button).
  const signedIn = session.status === "signed-in";
  return (
    <section className="relative w-full min-h-screen bg-slate-900 text-white overflow-hidden flex items-center" data-purpose="hero-banner">
      {/* Hero Background Image with Overlay */}
      <div className="absolute inset-0 z-0">
        <img
          alt={t("hero.imageAlt")}
          className="w-full h-full object-cover object-center brightness-75"
          src="/hero-background.jpg"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-black/90 via-black/70 to-black/20" />
        <div className="absolute inset-x-0 bottom-0 h-48 bg-gradient-to-t from-black via-black/50 to-transparent" />
      </div>

      {/* Hero Content Overlay */}
      <div className="relative z-10 max-w-7xl mx-auto px-6 sm:px-12 py-16 w-full">
        <div className="max-w-2xl lg:max-w-3xl">
          <h1 className="text-4xl sm:text-6xl lg:text-[76px] font-serif font-light text-white tracking-tight leading-[1.08] mb-6">
            {t("hero.title")}
          </h1>
          <p className="text-neutral-200 text-base sm:text-lg lg:text-[19px] leading-relaxed max-w-2xl mb-9 font-normal">
            {t("hero.body")}
          </p>
          {/* CTA Pill Button */}
          <div>
            <Link data-purpose="hero-cta" className="inline-flex items-center gap-3.5 px-6 py-2.5 rounded-full border border-white/80 bg-black/40 hover:bg-white hover:text-black text-white transition-all duration-200 text-[15px] font-medium group" href={signedIn ? homeFor(session.profile) : "/signup"}>
              <span>{signedIn ? t("hero.ctaSignedIn") : t("hero.cta")}</span>
              <span className="w-6 h-6 rounded-full bg-white text-black flex items-center justify-center group-hover:bg-black group-hover:text-white transition-colors">
                <svg className="w-3.5 h-3.5 ml-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M9 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" />
                </svg>
              </span>
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
