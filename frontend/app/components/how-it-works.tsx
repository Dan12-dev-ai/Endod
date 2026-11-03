"use client";

import { useI18n, type TranslationKey } from "../lib/i18n";

const STEPS: { titleKey: TranslationKey; bodyKey: TranslationKey; icon: React.ReactNode }[] = [
  {
    titleKey: "howItWorks.step1.title",
    bodyKey: "howItWorks.step1.body",
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
        <path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    titleKey: "howItWorks.step2.title",
    bodyKey: "howItWorks.step2.body",
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
        <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    titleKey: "howItWorks.step3.title",
    bodyKey: "howItWorks.step3.body",
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
        <path d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
];

export default function HowItWorks() {
  const { t } = useI18n();
  return (
    <section
      className="relative bg-gradient-to-b from-white via-slate-50 to-white py-14 sm:py-20 border-y border-slate-200"
      data-purpose="how-it-works-section"
      id="how-it-works"
    >
      <div className="max-w-7xl mx-auto px-6 sm:px-12">
        <div className="text-center max-w-2xl mx-auto mb-10 sm:mb-14">
          <p className="text-xs sm:text-sm font-semibold tracking-[0.2em] text-slate-700 uppercase mb-3">
            {t("howItWorks.eyebrow")}
          </p>
          <h2 className="text-2xl sm:text-3xl lg:text-4xl font-bold text-[#0b1c2b] tracking-tight">
            {t("howItWorks.title")}
          </h2>
        </div>

        <div className="relative grid grid-cols-3 gap-4 sm:gap-8">
          <div
            aria-hidden="true"
            className="hidden sm:block absolute top-7 left-[16.666%] right-[16.666%] h-px bg-slate-200"
          />

          {STEPS.map((step, index) => (
            <div
              key={step.titleKey}
              className="relative flex flex-col items-center text-center gap-3 sm:gap-4"
            >
              <div className="relative z-10 w-14 h-14 sm:w-16 sm:h-16 rounded-2xl bg-white border border-slate-200 shadow-sm flex items-center justify-center text-slate-900 transition-transform duration-200 hover:-translate-y-0.5">
                <div className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-[#0b1c2b] text-white text-xs font-bold flex items-center justify-center">
                  {index + 1}
                </div>
                <div className="text-slate-700">{step.icon}</div>
              </div>
              <div className="space-y-1.5">
                <h3 className="text-sm sm:text-base font-semibold text-[#0b1c2b]">
                  {t(step.titleKey)}
                </h3>
                <p className="text-xs sm:text-sm text-slate-600 leading-relaxed max-w-[16rem] mx-auto">
                  {t(step.bodyKey)}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
