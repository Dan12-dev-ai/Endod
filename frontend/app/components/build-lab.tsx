export default function BuildLab() {
  return (
    <section className="relative min-h-[580px] lg:h-[640px] w-full flex items-center bg-stone-100 overflow-hidden" data-purpose="build-own-lab-card" id="build-own-lab">
      {/* Robotic Laboratory Background (Screenshot 6) */}
      <div className="absolute inset-0 z-0">
        <img
          alt="Automated lab hardware units in Boston HQ"
          className="w-full h-full object-cover object-right lg:object-center filter brightness-95"
          src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900' viewBox='0 0 1600 900'><rect width='1600' height='900' fill='%23e2e8f0'/><g stroke='%23334155' stroke-width='6' fill='%23ffffff'><rect x='700' y='140' width='180' height='580' rx='12'/><rect x='920' y='140' width='180' height='580' rx='12'/><rect x='1140' y='140' width='180' height='580' rx='12'/><rect x='1360' y='140' width='180' height='580' rx='12'/></g><line x1='600' y1='480' x2='1600' y2='480' stroke='%2364748b' stroke-width='8'/></svg>"
        />
      </div>

      {/* Frosted Glass Card Left Overlay */}
      <div className="relative z-10 max-w-7xl mx-auto px-6 sm:px-12 w-full py-12">
        <div className="glass-morphism rounded-3xl p-8 sm:p-12 max-w-lg lg:max-w-xl shadow-xl border border-white/60">
          {/* Overline badge */}
          <div className="mb-4">
            <span className="inline-block text-[11px] font-bold uppercase tracking-widest text-slate-800 border-b-2 border-slate-900 pb-0.5">
              AUTONOMOUS LABS
            </span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-serif text-[#0b1c2b] tracking-tight leading-[1.08] mb-5">
            Build your own autonomous lab
          </h2>
          <h3 className="text-lg sm:text-[21px] font-serif text-slate-800 leading-snug mb-4">
            Autonomous labs aren&rsquo;t science fiction&mdash;they&rsquo;re already here
          </h3>
          <p className="text-slate-600 text-sm sm:text-base leading-relaxed mb-8">
            We built one in our Boston HQ, now you can too.
          </p>
          {/* Action CTA Buttons */}
          <div className="flex flex-wrap items-center gap-3">
            <a className="inline-flex items-center gap-3 px-5 py-2.5 rounded-full border border-slate-900 bg-white/80 hover:bg-white text-slate-900 text-sm font-medium transition shadow-sm group" href="#contact-section">
              <span>Learn more</span>
              <span className="w-5 h-5 rounded-full bg-slate-900 text-white flex items-center justify-center">
                <svg className="w-3 h-3 ml-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M9 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" />
                </svg>
              </span>
            </a>
            <a className="inline-flex items-center gap-3 px-5 py-2.5 rounded-full bg-[#0d2130] hover:bg-[#16364e] text-white text-sm font-medium transition shadow-md group" href="#contact-section">
              <span>Book a meeting</span>
              <span className="w-5 h-5 rounded-full bg-white text-slate-900 flex items-center justify-center">
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
