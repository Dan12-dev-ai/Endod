export default function Bottleneck() {
  return (
    <section className="bg-[#f5f3ef] py-20 lg:py-28 text-slate-900 border-b border-stone-200" data-purpose="narrative-split-section" id="bottleneck">
      <div className="max-w-7xl mx-auto px-6 sm:px-12">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-16 items-center">
          {/* Left: Circular Masked Machinery Image */}
          <div className="lg:col-span-5 flex justify-center lg:justify-start">
            <div className="relative w-72 h-72 sm:w-96 sm:h-96 lg:w-[440px] lg:h-[440px] rounded-full overflow-hidden shadow-2xl border-4 border-white/80 bg-stone-200">
              <img
                alt="Patients and hospitals connected in one trusted system"
                className="w-full h-full object-cover object-center filter contrast-105"
                src="/endod_hero.jpg"
              />
            </div>
          </div>

          {/* Right: Bottleneck Pitch Content */}
          <div className="lg:col-span-7 max-w-xl">
            <h2 className="text-4xl sm:text-5xl lg:text-[54px] font-serif text-[#0b1c2b] tracking-tight leading-[1.08] mb-6">
              Care is fragmented — and it slows everyone down
            </h2>
            <div className="w-full h-[2px] bg-[#0b1c2b] mb-8" />
            <h3 className="text-2xl sm:text-3xl font-serif text-[#0b1c2b] mb-5 tracking-tight font-normal">
              One trusted system connects patients and hospitals
            </h3>
            <div className="space-y-4 text-stone-700 text-base sm:text-[17px] leading-relaxed mb-9">
              <p>
                Symptoms get described from scratch at every visit, hospitals fill up with no way to see it coming, and records stay locked inside a single clinic. The result is wasted time, repeated tests, and care that starts from zero.
              </p>
              <p>
                Endod Health OS replaces the guesswork with a single, consent-based record and live visibility — so patients arrive understood and hospitals arrive prepared, while the patient stays in control of their own data.
              </p>
            </div>
            <div>
              <a className="inline-flex items-center gap-3.5 px-6 py-2.5 rounded-full border border-slate-900 bg-transparent hover:bg-slate-900 hover:text-white text-slate-900 transition-all duration-200 text-[15px] font-medium group" href="#build-own-lab">
                <span>See how it works</span>
                <span className="w-6 h-6 rounded-full bg-slate-900 text-white flex items-center justify-center group-hover:bg-white group-hover:text-black transition-colors">
                  <svg className="w-3.5 h-3.5 ml-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path d="M9 5l7 7-7 7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" />
                  </svg>
                </span>
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
