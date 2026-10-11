"use client";

export default function Header() {
  return (
    <>
      {/* Announcement Event Bar */}
      <div
        className="bg-black text-white text-[11px] sm:text-[12px] font-medium tracking-wide py-2.5 px-4 sm:px-8 border-b border-white/10 flex items-center justify-between transition-all duration-300"
        id="event-bar"
      >
        <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase font-mono tracking-wider bg-white/10 text-neutral-300 border border-white/15">
            [ EVENT ]
          </span>
          <span className="font-bold text-white">REAL Summit 2026</span>
          <span className="text-neutral-400">·</span>
          <span className="text-neutral-300">Seaport Boston</span>
          <span className="text-neutral-400">·</span>
          <span className="text-neutral-300">September 15</span>
        </div>
        <div className="flex items-center gap-4 sm:gap-6 text-[11px]">
          <span className="hidden md:inline-block uppercase tracking-wider text-neutral-400">
            FEATURING <span className="text-white font-semibold">DOTM</span>
          </span>
          <span className="hidden sm:inline-block uppercase tracking-wider text-neutral-400">
            HAPPENING <span className="text-white font-semibold">NOW</span>
          </span>
          <a
            className="font-semibold underline uppercase tracking-wider hover:text-neutral-300 transition-colors flex items-center gap-1 text-white"
            href="#contact-section"
          >
            REQUEST INVITE HERE
            <span aria-hidden="true">→</span>
          </a>
          <button
            aria-label="Dismiss banner"
            className="text-neutral-400 hover:text-white transition-colors ml-2"
            onClick={() => { const bar = document.getElementById("event-bar"); if (bar) { bar.style.display = "none"; } }}
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path d="M6 18L18 6M6 6l12 12" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" />
            </svg>
          </button>
        </div>
      </div>

      {/* Main Navigation Bar */}
      <nav className="bg-black/95 text-white backdrop-blur-md px-6 lg:px-12 py-3.5 flex items-center justify-between border-b border-white/10">
        {/* Ginkgo Bioworks Gear Logo */}
        <a aria-label="Ginkgo Bioworks Homepage" className="flex items-center gap-3 group" href="#">
          <svg
            className="w-8 h-8 text-white transition-transform group-hover:rotate-12 duration-500"
            fill="currentColor"
            viewBox="0 0 100 100"
          >
            <path d="M50 15a35 35 0 1 0 35 35 35 35 0 0 0-35-35zm0 18a17 17 0 1 1-17 17 17 17 0 0 1 17-17z" />
            <path d="M50 0 L58 12 L64 10 L68 22 L76 21 L77 34 L87 37 L84 49 L94 56 L88 66 L96 76 L87 83 L91 95 L78 96 L76 108 L64 103 L58 112 L50 104 L42 112 L36 103 L24 112 L22 96 L9 95 L13 83 L4 76 L12 66 L6 56 L16 49 L13 37 L23 34 L24 21 L32 22 L36 10 L42 12 Z" opacity="0.3" />
            <path clip-rule="evenodd" d="M44.5 12h11v8.2l3.4 1.4 6.8-4.7 7.8 7.8-4.7 6.8 1.4 3.4H78.5v11h-8.2l-1.4 3.4 4.7 6.8-7.8 7.8-6.8-4.7-3.4 1.4V78.5h-11v-8.2l-3.4-1.4-6.8 4.7-7.8-7.8 4.7-6.8-1.4-3.4H21.5v-11h8.2l1.4-3.4-4.7-6.8 7.8-7.8 6.8 4.7 3.4-1.4V12zm5.5 25.5a12.5 12.5 0 100 25 12.5 12.5 0 000-25z" fill-rule="evenodd" />
          </svg>
          <div className="leading-none">
            <span className="block text-[15px] font-extrabold tracking-widest uppercase">GINKGO</span>
            <span className="block text-[11px] font-light tracking-[0.22em] text-neutral-300 uppercase">BIOWORKS</span>
          </div>
        </a>

        {/* Menu links */}
        <div className="hidden md:flex items-center space-x-8 text-[14px] font-medium text-neutral-200">
          {/* Build Your Own Lab Dropdown */}
          <div className="relative group" id="labDropdownContainer">
            <button
              aria-expanded="false"
              className="flex items-center gap-1.5 hover:text-white py-2 focus:outline-none transition-colors"
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
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors" href="#build-own-lab">Overview</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors" href="#build-own-lab">Hardware</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors" href="#build-own-lab">Software</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors" href="#build-own-lab">Support</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors" href="#build-own-lab">Applications</a>
                <a className="px-5 py-2.5 hover:bg-slate-100 hover:text-black transition-colors" href="#build-own-lab">Ginkgo Reagents</a>
              </div>
            </div>
          </div>

          {/* Cloud Lab Dropdown */}
          <div className="relative group">
            <button className="flex items-center gap-1.5 hover:text-white py-2 focus:outline-none transition-colors">
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
                <a className="px-5 py-2 hover:bg-slate-100 transition-colors" href="#cloud-lab">Solutions</a>
                <a className="px-5 py-2 hover:bg-slate-100 transition-colors" href="#cloud-lab">Datapoints</a>
              </div>
            </div>
          </div>

          {/* Resources Dropdown */}
          <div className="relative group">
            <button className="flex items-center gap-1.5 hover:text-white py-2 focus:outline-none transition-colors">
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
                <a className="px-5 py-2 hover:bg-slate-100 transition-colors" href="#action-video">Case Studies</a>
                <a className="px-5 py-2 hover:bg-slate-100 transition-colors" href="#action-video">Documentation</a>
              </div>
            </div>
          </div>
        </div>

        {/* Contact Us Button */}
        <div>
          <a
            className="inline-flex items-center justify-center px-5 py-2 rounded-md border border-neutral-400 text-white hover:bg-white hover:text-black transition-all text-[13px] font-medium tracking-wide"
            href="#contact-section"
          >
            Contact Us
          </a>
        </div>
      </nav>
    </>
  );
}
