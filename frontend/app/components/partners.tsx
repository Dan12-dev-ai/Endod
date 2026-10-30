"use client";

import { useI18n } from "../lib/i18n";

const PARTNERS = [
  { name: "Adinas", src: "/adinas_logo.jpeg" },
  { name: "Afilas", src: "/afilas_logo.png" },
  { name: "Felege Hiwot", src: "/felegehiwot_logo.jpeg" },
  { name: "Tibebegion", src: "/tibebegion_logo.jpeg" },
];

// Double the set so one "half" is wide enough to fill large screens.
const HALF = [...PARTNERS, ...PARTNERS];

function Logo({ name, src }: { name: string; src: string }) {
  const isAfilas = name === "Afilas";
  return (
    <div
      className={`flex-shrink-0 w-24 md:w-80 lg:w-96 flex items-center justify-center drop-shadow-md ${
        isAfilas ? "bg-slate-900 rounded-xl p-4 h-14 md:h-54 lg:h-58" : ""
      }`}
    >
      <img
        src={src}
        alt={name}
        width={320}
        height={320}
        className="h-16 w-16 md:h-64 md:w-64 lg:h-72 lg:w-72 object-contain"
        loading="lazy"
      />
    </div>
  );
}

export default function Partners() {
  const { t } = useI18n();

  return (
    <section
      className="py-16 sm:py-20 bg-white dark:bg-gray-800 overflow-hidden"
      data-purpose="partners-section"
      id="partners"
    >
      <div className="max-w-7xl mx-auto px-6 sm:px-12 mb-10 text-center">
        <h2 className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-gray-100 tracking-tight">
          {t("partners.title")}
        </h2>
        <p className="mt-2 text-sm sm:text-base text-slate-500">
          {t("partners.subtitle")}
        </p>
      </div>

      <div
        className="relative overflow-hidden"
        style={{
          maskImage:
            "linear-gradient(to right, transparent, black 10%, black 90%, transparent)",
          WebkitMaskImage:
            "linear-gradient(to right, transparent, black 10%, black 90%, transparent)",
        }}
      >
        <div className="marquee-track flex flex-shrink-0 w-max whitespace-nowrap hover:[animation-play-state:paused]">
          <div className="flex flex-shrink-0 items-center gap-8 md:gap-16 lg:gap-16 pr-8 md:pr-16 lg:pr-16">
            {HALF.map((p, i) => (
              <Logo key={`a-${i}`} name={p.name} src={p.src} />
            ))}
          </div>
          <div
            className="flex flex-shrink-0 items-center gap-8 md:gap-16 lg:gap-16 pr-8 md:pr-16 lg:pr-16"
            aria-hidden="true"
          >
            {HALF.map((p, i) => (
              <Logo key={`b-${i}`} name={p.name} src={p.src} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
