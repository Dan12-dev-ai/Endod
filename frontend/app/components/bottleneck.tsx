const bottleneckImg = `<svg xmlns='http://www.w3.org/2000/svg' width='800' height='800' viewBox='0 0 800 800'><rect width='800' height='800' fill='%23e5e7eb'/><rect x='150' y='180' width='500' height='460' rx='20' fill='%23ffffff' stroke='%23374151' stroke-width='10'/><rect x='200' y='240' width='180' height='260' fill='%2393c5fd' opacity='0.5'/><rect x='420' y='240' width='180' height='260' fill='%2393c5fd' opacity='0.5'/><circle cx='400' cy='120' r='25' fill='%23111827'/><rect x='280' y='520' width='240' height='60' rx='8' fill='%23d1d5db'/></svg>`;

export default function Bottleneck() {
  return (
    <section className="bg-[#f5f3ef] py-20 lg:py-28 text-slate-900 border-b border-stone-200" data-purpose="narrative-split-section" id="bottleneck">
      <div className="max-w-7xl mx-auto px-6 sm:px-12">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-16 items-center">
          {/* Left: Circular Masked Machinery Image */}
          <div className="lg:col-span-5 flex justify-center lg:justify-start">
            <div className="relative w-72 h-72 sm:w-96 sm:h-96 lg:w-[440px] lg:h-[440px] rounded-full overflow-hidden shadow-2xl border-4 border-white/80 bg-stone-200">
              <img
                alt="Autonomous lab robotic modular chambers"
                className="w-full h-full object-cover object-center filter contrast-105"
                src={`data:image/svg+xml;utf8,${bottleneckImg}`}
              />
            </div>
          </div>

          {/* Right: Bottleneck Pitch Content */}
          <div className="lg:col-span-7 max-w-xl">
            <h2 className="text-4xl sm:text-5xl lg:text-[54px] font-serif text-[#0b1c2b] tracking-tight leading-[1.08] mb-6">
              Labwork is the bottleneck for biotechnology
            </h2>
            <div className="w-full h-[2px] bg-[#0b1c2b] mb-8" />
            <h3 className="text-2xl sm:text-3xl font-serif text-[#0b1c2b] mb-5 tracking-tight font-normal">
              Autonomous labs are the answer
            </h3>
            <div className="space-y-4 text-stone-700 text-base sm:text-[17px] leading-relaxed mb-9">
              <p>
                Science still runs on manual benchwork, and that bottleneck slows progress on everything from novel materials to lifesaving medicines. Autonomous labs replace the bench, letting scientists order experimental work from robots just by asking for it.
              </p>
              <p>
                This shift doesn&rsquo;t replace scientists; it empowers them to focus on insight, creativity, and judgment rather than manual lab work.
              </p>
            </div>
            <div>
              <a className="inline-flex items-center gap-3.5 px-6 py-2.5 rounded-full border border-slate-900 bg-transparent hover:bg-slate-900 hover:text-white text-slate-900 transition-all duration-200 text-[15px] font-medium group" href="#build-own-lab">
                <span>What is an autonomous lab?</span>
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
