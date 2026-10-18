"use client";

import { useI18n } from "../lib/i18n";

export default function BuildLab() {
  const { t } = useI18n();
  return (
    <section className="relative min-h-[580px] lg:h-[640px] w-full flex items-center overflow-hidden" data-purpose="build-own-lab-card" id="build-own-lab">
      {/* Background Image */}
      <div className="absolute inset-0 z-0">
        <img
          alt={t("buildLab.imageAlt")}
          className="w-full h-full object-cover object-center"
          src="/medicine_background.jpg"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/20 to-black/40" />
      </div>

      {/* Frosted Glass Card Left Overlay — White, blurred, transparent */}
      <div className="relative z-10 max-w-7xl mx-auto px-6 sm:px-12 w-full py-12">
        <div className="glass-morphism rounded-3xl p-8 sm:p-12 max-w-lg lg:max-w-xl shadow-xl border border-white/40 backdrop-blur-xl bg-white/50">
          {/* Overline badge */}
          <div className="mb-4">
            <span className="inline-block text-[11px] font-bold uppercase tracking-widest text-slate-800 border-b-2 border-slate-900 pb-0.5">
              {t("buildLab.badge")}
            </span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-serif text-[#0b1c2b] tracking-tight leading-[1.08] mb-5">
            {t("buildLab.title")}
          </h2>
          <h3 className="text-lg sm:text-[21px] font-serif text-slate-800 leading-snug mb-4">
            {t("buildLab.subtitle")}
          </h3>
          <p className="text-slate-600 text-sm sm:text-base leading-relaxed mb-8">
            {t("buildLab.body")}
          </p>
          {/* Action CTA Buttons */}
          <div className="flex flex-wrap items-center gap-3">
            <a className="inline-flex items-center gap-3 px-5 py-2.5 rounded-full border border-slate-900 bg-white/80 hover:bg-white text-slate-900 text-sm font-medium transition shadow-sm group" href="/interview">
              <span>{t("buildLab.cta")}</span>
              <span className="w-5 h-5 rounded-full bg-slate-900 text-white flex items-center justify-center">
                <svg className="w-3 h-3 ml-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M9 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" />
                </svg>
              </span>
            </a>
            <a className="inline-flex items-center gap-3 px-5 py-2.5 rounded-full bg-[#0d2130] hover:bg-[#16364e] text-white text-sm font-medium transition shadow-md group" href="#cloud-lab">
              <span>{t("buildLab.findHospital")}</span>
              <span className="w-5 h-5 rounded-full bg-white text-slate-900 flex items-center justify-center">
                <svg className="w-3 h-3 ml-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M9 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" />
                </svg>
              </span>
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
