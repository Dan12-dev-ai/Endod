export default function Pipette() {
  return (
    <section className="relative min-h-[580px] lg:h-[640px] w-full flex items-center bg-stone-100 overflow-hidden" data-purpose="pipette-hero-card">
      {/* Lab scientist in cleanroom suit background (Screenshot 9) */}
      <div className="absolute inset-0 z-0">
        <img
          alt="Scientist operating laptop in laboratory cleanroom"
          className="w-full h-full object-cover object-center filter blur-[1px] brightness-95"
          src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900' viewBox='0 0 1600 900'><rect width='1600' height='900' fill='%23cbd5e1'/><circle cx='850' cy='320' r='120' fill='%2322c55e' opacity='0.7'/><rect x='600' y='280' width='500' height='620' rx='80' fill='%23f8fafc'/><rect x='720' y='420' width='260' height='160' rx='10' fill='%230f172a'/></svg>"
        />
      </div>

      {/* Frosted Glass Card Left Overlay */}
      <div className="relative z-10 max-w-7xl mx-auto px-6 sm:px-12 w-full py-12">
        <div className="glass-morphism rounded-3xl p-8 sm:p-12 max-w-lg lg:max-w-xl shadow-xl border border-white/60">
          {/* Overline badge */}
          <div className="mb-4">
            <span className="inline-block text-[11px] font-bold uppercase tracking-widest text-slate-800 border-b-2 border-slate-900 pb-0.5">
              FOR SCIENTISTS, BY SCIENTISTS
            </span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-serif text-[#0b1c2b] tracking-tight leading-[1.08] mb-5">
            Autonomous labs are your new pipette
          </h2>
          <p className="text-slate-700 text-sm sm:text-base leading-relaxed mb-8">
            The most important tool since the pipette: an autonomous system lifts the burden of the bench, speaks human language, and empowers scientists to focus on the questions only they can ask.
          </p>
          {/* CTA Button */}
          <div>
            <a className="inline-flex items-center gap-3.5 px-6 py-2.5 rounded-full border border-slate-900 bg-white/80 hover:bg-slate-900 hover:text-white text-slate-900 text-sm font-medium transition shadow-sm group" href="#contact-section">
              <span>Meet Catalyst Agent</span>
              <span className="w-5 h-5 rounded-full bg-slate-900 text-white flex items-center justify-center group-hover:bg-white group-hover:text-black">
                <svg className="w-3 h-3 ml-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M9 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" />
                </svg>
              </span>
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
