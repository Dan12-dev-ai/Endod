"use client";

import { useI18n } from "../lib/i18n";

export default function Partners() {
  const { t } = useI18n();

  return (
    <section
      className="py-16 sm:py-20 bg-white"
      data-purpose="partners-section"
      id="partners"
    >
      <div className="max-w-7xl mx-auto px-6 sm:px-12 mb-10 text-center">
        <h2 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">
          {t("partners.title")}
        </h2>
        <p className="mt-2 text-sm sm:text-base text-slate-500">
          {t("partners.subtitle")}
        </p>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <img
          src="/partners.jpg"
          alt={t("partners.title")}
          className="w-full h-auto rounded-lg shadow-sm"
          loading="lazy"
          sizes="(max-width: 640px) 100vw, (max-width: 1024px) 90vw, 1280px"
        />
      </div>
    </section>
  );
}
