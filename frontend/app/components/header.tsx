"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { logout } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { accountName, homeFor, useSession } from "../lib/session";
import LanguageSwitcher, { saveAccountLanguage } from "./language-switcher";

export default function Header() {
  const { t } = useI18n();
  const session = useSession();
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
          scrolled ? "bg-black/85" : "bg-black/30"
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
          {/* How It Works Dropdown */}
          <div className="relative group" id="labDropdownContainer">
            <button
              aria-expanded="false"
              className="flex items-center gap-1.5 hover:text-white py-2 focus:outline-none transition-colors cursor-pointer"
              id="labMenuBtn"
            >
              <span>{t("nav.howItWorks")}</span>
              <svg
                className="w-3.5 h-3.5 text-neutral-400 group-hover:text-white transition-transform group-hover:translate-y-0.5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path d="M19 9l-7 7-7-7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" />
              </svg>
            </button>
            {/* Dropdown items */}
            <div className="absolute left-0 top-full pt-2 w-56 hidden group-hover:block transition-all duration-200 z-50">
              <div className="bg-white text-slate-800 rounded-md shadow-2xl py-2.5 border border-slate-100 flex flex-col font-normal text-[14px]">
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#build-own-lab">{t("nav.overview")}</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#build-own-lab">{t("nav.aiSymptomAssistant")}</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#cloud-lab">{t("nav.hospitalFinder")}</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#cloud-lab">{t("nav.treatmentPlans")}</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#pipette-hero-card">{t("nav.medicalHistory")}</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#bottleneck">{t("nav.privacySecurity")}</a>
              </div>
            </div>
          </div>

          {/* For Hospitals Dropdown */}
          <div className="relative group">
            <button className="flex items-center gap-1.5 hover:text-white py-2 focus:outline-none transition-colors cursor-pointer">
              <span>{t("nav.forHospitals")}</span>
              <svg
                className="w-3.5 h-3.5 text-neutral-400 group-hover:text-white transition-transform group-hover:translate-y-0.5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path d="M19 9l-7 7-7-7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" />
              </svg>
            </button>
            <div className="absolute left-0 top-full pt-2 w-48 hidden group-hover:block transition-all duration-200 z-50">
              <div className="bg-white text-slate-800 rounded-md shadow-2xl py-2 border border-slate-100 flex flex-col font-normal text-[14px]">
                <a className="px-5 py-2 hover:bg-slate-100 transition-colors cursor-pointer" href="#cloud-lab">{t("nav.hospitalPortal")}</a>
                <a className="px-5 py-2 hover:bg-slate-100 transition-colors cursor-pointer" href="#cloud-lab">{t("nav.liveCrowdStatus")}</a>
              </div>
            </div>
          </div>

          {/* Resources Dropdown */}
          <div className="relative group">
            <button className="flex items-center gap-1.5 hover:text-white py-2 focus:outline-none transition-colors cursor-pointer">
              <span>{t("nav.resources")}</span>
              <svg
                className="w-3.5 h-3.5 text-neutral-400 group-hover:text-white transition-transform group-hover:translate-y-0.5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path d="M19 9l-7 7-7-7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" />
              </svg>
            </button>
            <div className="absolute left-0 top-full pt-2 w-48 hidden group-hover:block transition-all duration-200 z-50">
              <div className="bg-white text-slate-800 rounded-md shadow-2xl py-2 border border-slate-100 flex flex-col font-normal text-[14px]">
                <a className="px-5 py-2 hover:bg-slate-100 transition-colors cursor-pointer" href="#contact-section">{t("nav.support")}</a>
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
        <LanguageSwitcher
          onChange={session.status === "signed-in" ? saveAccountLanguage : undefined}
          tone="dark"
        />

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
  if (session.status === "loading") return <div aria-hidden className="w-28 h-9" />;

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
          className="inline-flex px-4 py-2 rounded-md bg-white text-black text-[13px] font-semibold hover:bg-neutral-200 transition-colors"
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
        <span className="w-7 h-7 rounded-full bg-white text-black flex items-center justify-center text-xs font-bold">
          {name.charAt(0).toUpperCase()}
        </span>
        <span className="max-w-[9rem] truncate" data-purpose="nav-account-name">{name}</span>
        <svg className={`w-3.5 h-3.5 text-neutral-300 transition-transform ${open ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path d="M19 9l-7 7-7-7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-2 w-48 bg-white text-slate-800 rounded-md shadow-2xl py-1.5 border border-slate-100 text-[14px] z-50"
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
