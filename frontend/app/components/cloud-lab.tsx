export default function CloudLab() {
  return (
    <section className="relative min-h-[580px] lg:h-[640px] w-full flex items-center bg-[#fff8eb] overflow-hidden" data-purpose="cloud-lab-card" id="cloud-lab">
      {/* Culture Well Plate Background (Screenshot 7 & 8) */}
      <div className="absolute inset-0 z-0">
        <img
          alt="Multi-well laboratory petri cultures"
          className="w-full h-full object-cover object-left lg:object-center filter saturate-150 contrast-95"
          src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900' viewBox='0 0 1600 900'><rect width='1600' height='900' fill='%23fed7aa'/><g fill='%23f59e0b' opacity='0.7'><circle cx='100' cy='100' r='35'/><circle cx='200' cy='100' r='35'/><circle cx='300' cy='100' r='35'/><circle cx='400' cy='100' r='35'/><circle cx='100' cy='200' r='35'/><circle cx='200' cy='200' r='35'/><circle cx='300' cy='200' r='35'/><circle cx='400' cy='200' r='35'/><circle cx='100' cy='300' r='35'/><circle cx='200' cy='300' r='35'/><circle cx='300' cy='300' r='35'/><circle cx='400' cy='300' r='35'/></g></svg>"
        />
      </div>

      {/* Frosted Glass Card Right Overlay */}
      <div className="relative z-10 max-w-7xl mx-auto px-6 sm:px-12 w-full py-12 flex justify-end">
        <div className="glass-morphism-warm rounded-3xl p-8 sm:p-12 max-w-lg lg:max-w-xl shadow-xl border border-amber-100/70">
          {/* Overline badge */}
          <div className="mb-4">
            <span className="inline-block text-[11px] font-bold uppercase tracking-widest text-slate-800 border-b-2 border-slate-900 pb-0.5">
              CLOUD LAB
            </span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-serif text-[#0b1c2b] tracking-tight leading-[1.08] mb-5">
            Try before you buy
          </h2>
          <h3 className="text-lg sm:text-[21px] font-serif text-slate-800 leading-snug mb-4">
            Run your experiments on Ginkgo&rsquo;s autonomous lab in Boston, virtually
          </h3>
          <p className="text-slate-700 text-sm sm:text-base leading-relaxed mb-8">
            Regardless of whether your R&amp;D project is open-ended or defined, Ginkgo can help. Our Ginkgo Solutions and Ginkgo Datapoints teams work with you to understand your project and design experiments that directly address your goals.
          </p>
          {/* Two CTA Buttons */}
          <div className="flex flex-wrap items-center gap-3">
            <a className="inline-flex items-center gap-3 px-5 py-2.5 rounded-full border border-slate-900 bg-white/80 hover:bg-white text-slate-900 text-sm font-medium transition shadow-sm group" href="#contact-section">
              <span>Solutions</span>
              <span className="w-5 h-5 rounded-full bg-slate-900 text-white flex items-center justify-center">
                <svg className="w-3 h-3 ml-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M9 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" />
                </svg>
              </span>
            </a>
            <a className="inline-flex items-center gap-3 px-5 py-2.5 rounded-full bg-[#0d2130] hover:bg-[#16364e] text-white text-sm font-medium transition shadow-md group" href="#contact-section">
              <span>Datapoints</span>
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
