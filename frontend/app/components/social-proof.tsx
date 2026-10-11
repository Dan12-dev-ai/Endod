export default function SocialProof() {
  return (
    <section className="bg-[#f5f3ef] py-14 border-t border-b border-stone-200" data-purpose="partner-logos-bar">
      <div className="max-w-7xl mx-auto px-6 sm:px-12 text-center">
        <p className="text-[12px] font-semibold uppercase tracking-[0.18em] text-stone-600 mb-10">
          TRUSTED BY OVER 130 CUSTOMERS
        </p>
        {/* Customer Logos Row (Matches Screenshot 8) */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-8 items-center justify-items-center opacity-85">
          {/* Corteva Agriscience */}
          <div className="flex items-center gap-2 font-black text-slate-900 tracking-tighter text-lg">
            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M2 12c0-5.5 4.5-10 10-10s10 4.5 10 10-4.5 10-10 10S2 17.5 2 12zm4 0h12" />
            </svg>
            <div className="text-left leading-tight">
              <span className="block font-black text-[15px] tracking-tight">CORTEVA</span>
              <span className="block text-[8px] font-sans tracking-widest text-slate-600 uppercase">agriscience</span>
            </div>
          </div>

          {/* Novartis */}
          <div className="flex items-center gap-1.5 font-serif text-slate-900 text-xl font-bold tracking-tight">
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 2a10 10 0 0 0-3 19.5V17a7 7 0 1 1 6 0v4.5A10 10 0 0 0 12 2z" />
            </svg>
            <span>NOVARTIS</span>
          </div>

          {/* Novo Nordisk */}
          <div className="flex items-center gap-2 text-slate-900">
            <svg className="w-7 h-7" fill="currentColor" viewBox="0 0 24 24">
              <path d="M19 8c0-1.7-.8-3.1-2-4 1 .9 2 2.3 2 4zm-7-6C6.5 2 2 6.5 2 12s4.5 10 10 10 10-4.5 10-10c0-.7-.1-1.3-.2-2-.6 1.2-1.7 2-3.1 2-2.2 0-4-1.8-4-4 0-.4.1-.7.2-1-1.4.3-2.6 1.4-2.9 2.9-.1.6-.2 1.3-.2 2.1 0 2.2 1.8 4 4 4 .7 0 1.3-.2 1.9-.5-1.1 1.5-2.9 2.5-4.9 2.5-3.3 0-6-2.7-6-6s2.7-6 6-6c.4 0 .7 0 1.1.1-.6-.7-1.5-1.1-2.4-1.1z" />
            </svg>
            <span className="font-sans text-[13px] font-semibold leading-tight text-left">novo nordisk<sup>®</sup></span>
          </div>

          {/* Pfizer */}
          <div className="font-serif italic text-2xl font-black text-slate-900 tracking-tight">
            Pfizer
          </div>

          {/* Bayer */}
          <div className="flex items-center justify-center">
            <div className="w-10 h-10 rounded-full border-2 border-slate-900 flex flex-col items-center justify-center text-[7px] font-black tracking-widest text-slate-900">
              <span>BAYER</span>
            </div>
          </div>

          {/* Boehringer Ingelheim */}
          <div className="flex items-center gap-1.5 text-slate-900">
            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 3L2 9v12h20V9L12 3zm0 3.5l6 3.6v9.4H6v-9.4l6-3.6z" />
            </svg>
            <span className="text-[11px] font-medium leading-none text-left">Boehringer<br/>Ingelheim</span>
          </div>
        </div>
      </div>
    </section>
  );
}
