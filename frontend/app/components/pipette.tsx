export default function Pipette() {
  return (
    <section className="relative min-h-[580px] lg:h-[640px] w-full flex items-center overflow-hidden" data-purpose="pipette-hero-card" id="pipette-hero-card">
      {/* Background Image */}
      <div className="absolute inset-0 z-0">
        <img
          alt="Patient following a treatment plan"
          className="w-full h-full object-cover object-center"
          src="/images/catalyst-agent.webp"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/20 to-black/40" />
      </div>

      {/* Frosted Glass Card Left Overlay */}
      <div className="relative z-10 max-w-7xl mx-auto px-6 sm:px-12 w-full py-12">
        <div className="glass-morphism rounded-3xl p-8 sm:p-12 max-w-lg lg:max-w-xl shadow-xl border border-white/40 backdrop-blur-xl bg-white/50">
          {/* Overline badge */}
          <div className="mb-4">
            <span className="inline-block text-[11px] font-bold uppercase tracking-widest text-slate-800 border-b-2 border-slate-900 pb-0.5">
              TREATMENT PLANS
            </span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-serif text-[#0b1c2b] tracking-tight leading-[1.08] mb-5">
            Your plan, and your history, in one place
          </h2>
          <p className="text-slate-700 text-sm sm:text-base leading-relaxed mb-8">
            Follow-up care with clear timelines, remaining drug and injection counts, and overdue alerts for you and your hospital. A single lifetime medical history travels with you across every facility — shared only with your consent.
          </p>
          {/* CTA Button */}
          <div>
            <a className="inline-flex items-center gap-3.5 px-6 py-2.5 rounded-full border border-slate-900 bg-white/80 hover:bg-slate-900 hover:text-white text-slate-900 text-sm font-medium transition shadow-sm group" href="/interview">
              <span>Talk to Endod AI</span>
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
