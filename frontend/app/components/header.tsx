"use client";

import Link from "next/link";
import { useState } from "react";

const languages = [
  { code: "en", label: "English" },
  { code: "am", label: "አማርኛ" },
];

export default function Header() {
  const [langOpen, setLangOpen] = useState(false);
  const [language, setLanguage] = useState("en");

  const currentLanguage = languages.find((l) => l.code === language) ?? languages[0];

  return (
    <>

      {/* Main Navigation Bar */}
      <nav className="sticky top-0 bg-black/95 text-white backdrop-blur-md px-6 lg:px-12 py-3.5 flex items-center justify-between border-b border-white/10 z-50">
        {/* DEDAN Health Logo */}
        <Link aria-label="DEDAN Health Homepage" className="flex items-center gap-3 group cursor-pointer" href="/">
          <img
            alt="DEDAN Health logo"
            className="h-14 w-auto object-contain flex-shrink-0"
            src="/endod_logo.png"
          />
        </Link>

        {/* Menu links */}
        <div className="hidden md:flex items-center space-x-8 text-[14px] font-medium text-neutral-200">
          {/* Build Your Own Lab Dropdown */}
          <div className="relative group" id="labDropdownContainer">
            <button
              aria-expanded="false"
              className="flex items-center gap-1.5 hover:text-white py-2 focus:outline-none transition-colors cursor-pointer"
              id="labMenuBtn"
            >
              <span>Build Your Own Lab</span>
              <svg
                className="w-3.5 h-3.5 text-neutral-400 group-hover:text-white transition-transform group-hover:translate-y-0.5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path d="M19 9l-7 7-7-7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" />
              </svg>
            </button>
            {/* Dropdown items exact list from Screenshot 2 */}
            <div className="absolute left-0 top-full pt-2 w-56 hidden group-hover:block transition-all duration-200 z-50">
              <div className="bg-white text-slate-800 rounded-md shadow-2xl py-2.5 border border-slate-100 flex flex-col font-normal text-[14px]">
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#build-own-lab">Overview</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#build-own-lab">Hardware</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#build-own-lab">Software</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#build-own-lab">Support</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#build-own-lab">Applications</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors cursor-pointer" href="#build-own-lab">Ginkgo Reagents</a>
              </div>
            </div>
          </div>

          {/* Cloud Lab Dropdown */}
          <div className="relative group">
            <button className="flex items-center gap-1.5 hover:text-white py-2 focus:outline-none transition-colors cursor-pointer">
              <span>Cloud Lab</span>
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
                <a className="px-5 py-2 hover:bg-slate-100 transition-colors cursor-pointer" href="#cloud-lab">Solutions</a>
                <a className="px-5 py-2 hover:bg-slate-100 transition-colors cursor-pointer" href="#cloud-lab">Datapoints</a>
              </div>
            </div>
          </div>

          {/* Resources Dropdown */}
          <div className="relative group">
            <button className="flex items-center gap-1.5 hover:text-white py-2 focus:outline-none transition-colors cursor-pointer">
              <span>Resources</span>
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
                <a className="px-5 py-2 hover:bg-slate-100 transition-colors cursor-pointer" href="#action-video">Case Studies</a>
                <a className="px-5 py-2 hover:bg-slate-100 transition-colors cursor-pointer" href="#action-video">Documentation</a>
              </div>
            </div>
          </div>
        </div>

        {/* Language Selection */}
        <div className="relative">
          <button
            aria-expanded={langOpen}
            aria-haspopup="listbox"
            aria-label="Select language"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md border border-neutral-400 text-white hover:bg-white hover:text-black transition-all text-[13px] font-medium tracking-wide focus:outline-none cursor-pointer"
            onClick={() => setLangOpen((open) => !open)}
            type="button"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              viewBox="0 0 24 24"
            >
              <path d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10m-1.314-3H9.314" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>{currentLanguage.label}</span>
            <svg
              className={`w-3.5 h-3.5 text-neutral-400 transition-transform ${langOpen ? "rotate-180" : ""}`}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              viewBox="0 0 24 24"
            >
              <path d="M19 9l-7 7-7-7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>

          {langOpen && (
            <div
              className="absolute right-0 top-full mt-2 w-40 bg-white text-slate-800 rounded-md shadow-2xl py-1.5 border border-slate-100 flex flex-col text-[14px] z-50"
              role="listbox"
            >
              {languages.map((lang) => (
                <button
                  aria-selected={language === lang.code}
                  className={`text-left px-4 py-2 transition-colors cursor-pointer ${language === lang.code ? "bg-slate-100 text-black font-semibold" : "hover:bg-slate-100 hover:text-black"}`}
                  key={lang.code}
                  onClick={() => {
                    setLanguage(lang.code);
                    setLangOpen(false);
                  }}
                  role="option"
                  type="button"
                >
                  {lang.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </nav>
    </>
  );
}
