"use client";

import Link from "next/link";

export default function MobileComingSoon({ title }: { title: string }) {
  return (
    <div className="min-h-screen bg-gray-100 font-sans antialiased text-app-charcoal">
      <main className="w-full max-w-7xl mx-auto bg-white min-h-screen flex flex-col">
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
                <p className="text-sm font-semibold tracking-wide text-white drop-shadow-sm">{title}</p>
              </div>
            </div>
            <Link href="/interview" className="text-white/90 hover:text-white text-xs font-medium">Back</Link>
          </div>
          <div className="amber-wave-divider">
            <svg className="w-full h-3.5 fill-[#F39C12]" preserveAspectRatio="none" viewBox="0 0 500 24">
              <path d="M0,0 C150,22 350,22 500,0 L500,24 L0,24 Z" />
            </svg>
          </div>
        </section>

        <div className="flex-1 flex items-center justify-center px-4 py-10">
          <p className="text-2xl font-bold text-gray-500">Coming soon</p>
        </div>

        <nav className="sticky bottom-0 inset-x-0 bg-app-green border-t border-white/20 shadow-nav px-3 py-2 flex justify-around items-center z-40">
          {[
            { label: "Card", href: "/interview/card-mobile", active: title === "Card" },
            { label: "Booking", href: "/interview/booking-mobile", active: title === "Booking" },
            { label: "Appointment", href: "/interview/appointment-mobile", active: title === "Appointment" },
            { label: "Notification", href: "/interview/notification-mobile", active: title === "Notification" },
            { label: "Setting", href: "/interview/setting-mobile", active: title === "Setting" },
          ].map((item) => (
            <Link key={item.label} href={item.href} className={`flex flex-col items-center space-y-1 focus:outline-none flex-1 ${item.active ? "text-white" : "text-white/90 hover:text-white"}`}>
              <span className={`text-[10px] font-medium ${item.active ? "font-bold" : ""}`}>{item.label}</span>
            </Link>
          ))}
        </nav>
      </main>
    </div>
  );
}
