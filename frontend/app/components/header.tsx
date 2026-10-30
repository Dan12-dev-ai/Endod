"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { logout } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { accountName, homeFor, useSession } from "../lib/session";
import LanguageSwitcher from "./language-switcher";
import PwaInstallButton from "./pwa-install";
import { Bone } from "./skeleton";

export default function Header() {
  const { t } = useI18n();
  const pathname = usePathname();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10);
    onScroll();
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <>

      {/* Main Navigation Bar */}
      <nav
        className={`fixed top-0 left-0 right-0 w-full text-white backdrop-blur-md px-6 lg:px-12 py-3.5 flex items-center justify-between border-b border-white/10 z-50 transition-colors duration-300 ${
          pathname !== "/" || scrolled ? "bg-black/85" : "bg-black/30"
        }`}
      >
        {/* ENDOD Health Logo */}
        <Link aria-label={t("nav.homeAria")} className="flex items-center gap-3 group cursor-pointer" href="/">
          <img
            alt={t("nav.logoAlt")}
            className="h-14 w-auto object-contain flex-shrink-0"
            src="/endod_logo.png"
          />
        </Link>

        {/* Menu links */}
        <div className="hidden md:flex items-center space-x-8 text-[14px] font-medium text-neutral-200">
          <a
            className="hover:text-white transition-colors"
            data-purpose="nav-pharmacies"
            href="https://pharmacy.endod-health.com"
            rel="noopener noreferrer"
            target="_blank"
          >
            {t("nav.pharmacies")}
          </a>
          <a
            className="hover:text-white transition-colors"
            data-purpose="nav-hospitals"
            href="https://hospital.endod-health.com"
            rel="noopener noreferrer"
            target="_blank"
          >
            {t("nav.hospitals")}
          </a>
          <a
            className="hover:text-white transition-colors"
            data-purpose="nav-organisations"
            href="https://organisation.endod-health.com"
            rel="noopener noreferrer"
            target="_blank"
          >
            {t("nav.organisations")}
          </a>
        </div>

        <div className="flex items-center gap-3">
        <PwaInstallButton />
        <LanguageSwitcher tone="dark" />

        <AccountArea />
        </div>
      </nav>
    </>
  );
}

/** Sign in / sign up for visitors; the patient's name and a menu once signed in. */
function AccountArea() {
  const { t } = useI18n();
  const session = useSession();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !menuRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  // Same width as the buttons, so the bar does not jump when the check finishes.
  if (session.status === "loading") return <Bone className="w-28 h-9 rounded-full bg-white/15" />;

  if (session.status === "signed-out") {
    return (
      <div className="flex items-center gap-2" data-purpose="nav-signed-out">
        <Link
          className="hidden sm:inline-flex px-3 py-2 text-[13px] font-medium text-neutral-200 hover:text-white transition-colors"
          data-purpose="nav-sign-in"
          href="/login"
        >
          {t("nav.signIn")}
        </Link>
        <Link
          className="inline-flex px-4 py-2 rounded-md bg-white dark:bg-gray-800 text-black text-[13px] font-semibold hover:bg-neutral-200 transition-colors"
          data-purpose="nav-sign-up"
          href="/signup"
        >
          {t("nav.signUp")}
        </Link>
      </div>
    );
  }

  const { profile } = session;
  const name = accountName(profile);
  const itemClass = "block w-full text-left px-4 py-2 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer";
  return (
    <div className="relative" data-purpose="nav-account" ref={menuRef}>
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={t("nav.accountMenu")}
        className="inline-flex items-center gap-2 pl-1.5 pr-3 py-1.5 rounded-full border border-white/40 text-white hover:bg-white/10 transition-colors text-[13px] font-medium cursor-pointer"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span className="w-7 h-7 rounded-full bg-white dark:bg-gray-800 text-black flex items-center justify-center text-xs font-bold">
          {name.charAt(0).toUpperCase()}
        </span>
        <span className="max-w-[9rem] truncate" data-purpose="nav-account-name">{name}</span>
        <svg className={`w-3.5 h-3.5 text-neutral-300 transition-transform ${open ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path d="M19 9l-7 7-7-7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-2 w-48 bg-white dark:bg-gray-800 text-slate-800 rounded-md shadow-2xl py-1.5 border border-slate-100 text-[14px] z-50"
          role="menu"
        >
          <Link className={itemClass} data-purpose="nav-dashboard" href={homeFor(profile)} role="menuitem">
            {t("nav.dashboard")}
          </Link>
          {profile.onboarding_complete && (
            <Link className={itemClass} href="/health-card" role="menuitem">
              {t("nav.myHealthCard")}
            </Link>
          )}
          <button className={itemClass} data-purpose="nav-sign-out" onClick={() => void logout()} role="menuitem" type="button">
            {t("nav.signOut")}
          </button>
        </div>
      )}
    </div>
  );
}
