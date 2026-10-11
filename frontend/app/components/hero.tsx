const heroBg = `<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900' viewBox='0 0 1600 900'><defs><linearGradient id='sky' x1='0' y1='0' x2='0' y2='1'><stop offset='0%' stop-color='%23111827'/><stop offset='100%' stop-color='%2305090f'/></linearGradient></defs><rect width='1600' height='900' fill='url(#sky)'/><rect y='200' width='1600' height='700' fill='%231f2937' opacity='0.7'/><circle cx='800' cy='450' r='350' fill='%2310b981' opacity='0.15'/></svg>`;

export default function Hero() {
  return (
    <section className="relative w-full min-h-[580px] lg:h-[620px] bg-slate-900 text-white overflow-hidden flex items-center" data-purpose="hero-banner">
      {/* Architectural Building Background with Banner Crop */}
      <div className="absolute inset-0 z-0">
        <img
          alt="NYSE Building facade with Ginkgo Grow Everything banner"
          className="w-full h-full object-cover object-center brightness-75 scale-105"
          src={`data:image/svg+xml;utf8,${heroBg}`}
        />
      </div>
      {/* Photorealistic Backdrop Gradient Tint */}
      <div className="absolute inset-0 bg-gradient-to-r from-black/85 via-black/60 to-black/30" />
      <div className="absolute inset-x-0 bottom-0 h-48 bg-gradient-to-t from-black via-black/40 to-transparent" />

      {/* Hero Content Overlay */}
      <div className="relative z-10 max-w-7xl mx-auto px-6 sm:px-12 py-16 w-full">
        <div className="max-w-2xl lg:max-w-3xl">
          <h1 className="text-4xl sm:text-6xl lg:text-[76px] font-serif font-light text-white tracking-tight leading-[1.08] mb-6">
            Someday our kids will design the living world
          </h1>
          <p className="text-neutral-200 text-base sm:text-lg lg:text-[19px] leading-relaxed max-w-2xl mb-9 font-normal">
            In our vision of the future, our children will program biology like we once programmed computers. In that world, they will cure all diseases and grow everything they can imagine.
          </p>
          {/* CTA Pill Button */}
          <div>
            <a className="inline-flex items-center gap-3.5 px-6 py-2.5 rounded-full border border-white/80 bg-black/40 hover:bg-white hover:text-black text-white transition-all duration-200 text-[15px] font-medium group" href="#bottleneck">
              <span>Let&rsquo;s grow</span>
              <span className="w-6 h-6 rounded-full bg-white text-black flex items-center justify-center group-hover:bg-black group-hover:text-white transition-colors">
                <svg className="w-3.5 h-3.5 ml-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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