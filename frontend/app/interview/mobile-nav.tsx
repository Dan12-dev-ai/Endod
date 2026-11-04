"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useI18n } from "../lib/i18n";
import { MOBILE_SECTIONS } from "./mobile-shell";

/** The phone's bottom bar: the five most used sections (the rest are dashboard tiles). */
export default function MobileBottomNav() {
  const { t } = useI18n();
  const pathname = usePathname();
  return (
    <nav
      aria-label={t("interview.mobileNav")}
      className="md:hidden fixed bottom-0 inset-x-0 bg-[#18242B] border-t border-[#DCE4E6] shadow-nav px-2 pt-1.5 pb-[max(0.375rem,env(safe-area-inset-bottom))] z-40"
      data-purpose="mobile-bottom-nav"
    >
      <ul className="flex justify-around items-stretch">
        {MOBILE_SECTIONS.filter((s) => s.bottomNav).map((s) => {
          const active = pathname === s.href;
          return (
            <li key={s.id} className="flex-1 min-w-0">
              <Link
                href={s.href}
                aria-current={active ? "page" : undefined}
                data-purpose={`mobile-tab-${s.id}`}
                className={`flex flex-col items-center gap-0.5 py-1 rounded-lg text-[#FFFFFF] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#FFFFFF] ${active ? "bg-[#E8F1EF]/20" : "opacity-90 hover:opacity-100"}`}
              >
                <span className="[&>svg]:w-5 [&>svg]:h-5">{s.icon}</span>
                <span className={`text-[11px] w-full truncate text-center ${active ? "font-bold" : "font-medium"}`}>{t(s.labelKey)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
