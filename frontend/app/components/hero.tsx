export default function Hero() {
  return (
    <section className="relative w-full min-h-[580px] lg:h-[620px] bg-slate-900 text-white overflow-hidden flex items-center" data-purpose="hero-banner">
      {/* Pinterest Background Image with Overlay */}
      <div className="absolute inset-0 z-0">
        <img
          alt="Abstract technology background from Pinterest"
          className="w-full h-full object-cover object-center brightness-75"
          src="https://images.pexels.com/photos/1181871/pexels-photo-1181871.jpeg?auto=compress&cs=tinysrgb&w=1920"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-black/90 via-black/70 to-black/20" />
        <div className="absolute inset-x-0 bottom-0 h-48 bg-gradient-to-t from-black via-black/50 to-transparent" />
      </div>

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