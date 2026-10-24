"use client";

import { useI18n } from "../lib/i18n";

const PARTNERS = [
  { name: "St. Paul's Hospital", domain: "stpaulsmm.edu.et" },
  { name: "Tikur Anbessa", domain: "aau.edu.et" },
  { name: "Alert Hospital", domain: "alert.gov.et" },
  { name: "Kadisco Hospital", domain: "kadisco.com" },
  { name: "Hallelujah Hospital", domain: "hallelujahhospital.com" },
  { name: "Myungsung Hospital", domain: "mcmhospital.com" },
  { name: "Yekatit 12 Hospital", domain: "yekatit12hospital.gov.et" },
  { name: "Zewditu Hospital", domain: "zewdituhospital.gov.et" },
];

export default function Partners() {
  const { t } = useI18n();

  const loop = [...PARTNERS, ...PARTNERS];

  return (
    <section
      className="py-16 sm:py-20 bg-white overflow-hidden"
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

      <div className="relative">
        {/* Fade edges */}
        <div className="pointer-events-none absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-white to-transparent z-10" />
        <div className="pointer-events-none absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-white to-transparent z-10" />

        <div className="flex animate-marquee gap-24 sm:gap-32 items-center w-max">
          {loop.map((p, i) => (
            <div
              key={i}
              className="flex-shrink-0 w-40 sm:w-48 flex items-center justify-center opacity-100 transition-all duration-300 drop-shadow-md"
            >
              <img
                src="/logo.jpeg"
                alt={p.name}
                width={64}
                height={64}
                className="h-20 w-20 sm:h-24 sm:w-24 object-contain"
                loading="lazy"
              />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}