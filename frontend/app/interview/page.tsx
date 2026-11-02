"use client";

import Link from "next/link";

const services = [
  { label: "Card", href: "/interview/card-mobile", icon: <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg> },
  { label: "Booking", href: "/interview/booking-mobile", icon: <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg> },
  { label: "Appointment", href: "/interview/appointment-mobile", icon: <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg> },
  { label: "Setting", href: "/interview/setting-mobile", icon: <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg> },
];

export default function InterviewDashboard() {
  return (
    <div className="min-h-screen bg-gray-100 font-sans antialiased text-app-charcoal">
      <main className="w-full max-w-7xl mx-auto bg-white min-h-screen flex flex-col">
        {/* Brand header */}
        <section className="bg-white px-5 py-2.5 flex justify-between items-center z-20 border-b border-gray-100">
          <div className="flex items-center space-x-1.5">
            <div className="relative w-8 h-8 flex items-center justify-center">
              <span className="absolute w-7 h-7 rounded-full border-2 border-emerald-500 border-t-transparent -rotate-45" />
              <span className="w-4 h-4 bg-sky-500 rounded-full opacity-80" />
            </div>
            <div className="leading-tight">
              <span className="block text-sm font-black tracking-tight text-slate-800">ethio telecom<span className="text-[9px] align-super">™</span></span>
              <span className="block text-[9px] text-slate-500 font-medium -mt-0.5">ኢትዮ ቴሌኮም</span>
            </div>
          </div>
          <div className="flex items-center space-x-1">
            <svg className="w-6 h-6 text-app-action-blue" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15h-2v-6h2v6zm4 0h-2v-4h2v4zm-2-8a1.5 1.5 0 110-3 1.5 1.5 0 010 3z" />
            </svg>
            <div className="text-right leading-none">
              <span className="text-[10px] text-app-action-blue font-bold block">ቴሌብር</span>
              <span className="text-sm font-extrabold text-app-action-blue">telebirr</span>
            </div>
          </div>
        </section>

        {/* Hero balance section */}
        <section
          className="relative pt-3 px-5 text-white overflow-hidden shadow-sm pb-4"
          style={{
            backgroundImage: `radial-gradient(circle at 50% -20%, rgba(255,255,255,0.22) 0%, transparent 45%), radial-gradient(circle at 50% -20%, rgba(255,255,255,0.15) 50%, transparent 70%), repeating-radial-gradient(circle at 50% -10%, transparent 0, transparent 18px, rgba(255,255,255,0.08) 19px, rgba(255,255,255,0.08) 20px), linear-gradient(to bottom, #70C13B, #85CE53)`,
          }}
        >
          <div className="flex justify-between items-center mb-2.5">
            <div className="flex items-center space-x-2.5">
              <div className="w-9 h-9 rounded-full bg-white/30 backdrop-blur-sm border border-white/60 flex items-center justify-center text-white shadow-inner">
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path clipRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" fillRule="evenodd" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold tracking-wide text-white drop-shadow-sm">Selam, Etalem</p>
              </div>
            </div>
            <div className="flex items-center space-x-2">
              <button className="w-7 h-7 rounded-full bg-white/20 flex items-center justify-center text-white hover:bg-white/30 transition">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" />
                </svg>
              </button>
              <div className="flex items-center space-x-0.5 bg-black/15 px-2 py-1 rounded-full text-xs font-medium cursor-pointer">
                <span>English</span>
                <svg className="w-3 h-3 ml-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M19 9l-7 7-7-7" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" />
                </svg>
              </div>
            </div>
          </div>
          <div className="amber-wave-divider">
            <svg className="w-full h-3.5 fill-[#F39C12]" preserveAspectRatio="none" viewBox="0 0 500 24">
              <path d="M0,0 C150,22 350,22 500,0 L500,24 L0,24 Z" />
            </svg>
          </div>
        </section>

        {/* Service grid */}
        <section className="px-4 pt-5 pb-3" data-purpose="services-grid">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
            {services.map((s) => (
              <Link key={s.label} href={s.href} className="bg-white rounded-2xl p-4 flex flex-col items-center justify-center text-center shadow-card border border-gray-100 hover:shadow-md transition active:scale-95 cursor-pointer min-h-[110px]">
                <div className="w-14 h-14 rounded-2xl text-app-green flex items-center justify-center mb-2.5">
                  {s.icon}
                </div>
                <span className="text-base font-semibold text-app-charcoal leading-tight">{s.label}</span>
              </Link>
            ))}
            <Link href="/interview/notification-mobile" className="bg-white rounded-2xl p-4 flex flex-col items-center justify-center text-center shadow-card border border-gray-100 relative hover:shadow-md transition active:scale-95 cursor-pointer min-h-[110px]">
              <span className="absolute top-3 right-3 w-2.5 h-2.5 bg-red-500 rounded-full animate-ping" />
              <span className="absolute top-3 right-3 w-2.5 h-2.5 bg-red-500 rounded-full" />
              <div className="w-14 h-14 rounded-2xl text-app-green flex items-center justify-center mb-2.5">
                <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" />
                </svg>
              </div>
              <span className="text-base font-semibold text-app-charcoal leading-tight">Notification</span>
            </Link>
          </div>
        </section>

        {/* Emergency */}
        <div className="px-4 pb-6 pt-2 flex-1 flex items-center">
          <Link href="tel:" className="w-full flex items-center justify-center space-x-2 bg-red-600 hover:bg-red-600/90 text-white font-bold py-3.5 px-4 rounded-2xl shadow-card active:scale-95 transition">
            <svg className="w-5 h-5 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2.5" />
            </svg>
            <span className="text-base font-bold tracking-wide">Emergency</span>
          </Link>
        </div>

        {/* Bottom nav */}
        <nav className="sticky bottom-0 inset-x-0 bg-app-green border-t border-white/20 shadow-nav px-3 py-2 flex justify-around items-center z-40">
          <Link href="/interview/card?section=health-card" className="flex flex-col items-center text-white space-y-1 focus:outline-none flex-1">
            <svg className="w-5 h-5 fill-current" viewBox="0 0 24 24"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" /></svg>
            <span className="text-[10px] font-bold text-white">Card</span>
          </Link>
          <Link href="/interview/booking-mobile" className="flex flex-col items-center text-white/90 hover:text-white space-y-1 focus:outline-none flex-1">
            <svg className="w-5 h-5 stroke-current" fill="none" viewBox="0 0 24 24"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg>
            <span className="text-[10px] font-medium text-white/90">Booking</span>
          </Link>
          <Link href="/interview/appointment-mobile" className="flex flex-col items-center text-white/90 hover:text-white space-y-1 focus:outline-none flex-1">
            <svg className="w-5 h-5 stroke-current" fill="none" viewBox="0 0 24 24"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg>
            <span className="text-[10px] font-medium text-white/90">Appointment</span>
          </Link>
          <Link href="/interview/notification-mobile" className="flex flex-col items-center text-white/90 hover:text-white space-y-1 focus:outline-none flex-1">
            <svg className="w-5 h-5 stroke-current" fill="none" viewBox="0 0 24 24"><path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg>
            <span className="text-[10px] font-medium text-white/90">Notification</span>
          </Link>
          <Link href="/interview/setting-mobile" className="flex flex-col items-center text-white/90 hover:text-white space-y-1 focus:outline-none flex-1">
            <svg className="w-5 h-5 stroke-current" fill="none" viewBox="0 0 24 24"><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" stroke-linecap="round" stroke-linejoin="round" strokeWidth="2" /></svg>
            <span className="text-[10px] font-medium text-white/90">Setting</span>
          </Link>
        </nav>
      </main>
    </div>
  );
}
