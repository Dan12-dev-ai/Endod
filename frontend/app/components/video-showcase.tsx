export default function VideoShowcase() {
  return (
    <section className="bg-[#f5f3ef] pb-24 pt-8" data-purpose="video-demonstration" id="action-video">
      <div className="max-w-6xl mx-auto px-6 sm:px-12">
        {/* Section Title with trailing line */}
        <div className="flex items-center gap-4 mb-8">
          <h3 className="text-xl sm:text-2xl font-bold text-[#0b1c2b] tracking-tight whitespace-nowrap">
            See ours in action
          </h3>
          <div className="w-full h-[1px] bg-stone-300" />
        </div>

        {/* Embedded Video Style Player Container */}
        <div className="relative w-full aspect-video rounded-lg overflow-hidden bg-black shadow-2xl border border-stone-200">
          {/* Background scientist AR overlay visual (Screenshot 5) */}
          <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-black/70 flex items-center justify-center">
            <div className="w-full h-full bg-purple-950/40 mix-blend-screen absolute inset-0" />
            {/* AR futuristic subtitle box simulation */}
            <div className="relative z-10 px-6 max-w-2xl text-left">
              <div className="font-mono text-white text-lg sm:text-2xl lg:text-3xl font-light tracking-wide drop-shadow-md">
                <span className="text-neutral-400 font-sans">[</span>
                <span>Run cell free protein synthesis protocol and me<span className="text-purple-300 font-bold">a</span></span>
                <span className="inline-block w-2.5 h-6 bg-purple-400 animate-pulse ml-1 align-middle" />
                <span className="text-neutral-400 font-sans">]</span>
              </div>
            </div>
          </div>

          {/* Video Player Header Controls */}
          <div className="absolute top-4 left-4 right-4 flex items-center justify-between z-20 pointer-events-none">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-white/90 p-1 flex items-center justify-center">
                <svg className="w-6 h-6 text-[#15803d]" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 14h-2v-2h2v2zm0-4h-2V7h2v5z" />
                </svg>
              </div>
              <div>
                <p className="text-white text-xs font-semibold drop-shadow">Introducing the Autonomous Lab</p>
                <p className="text-neutral-300 text-[10px]">Ginkgo Bioworks</p>
              </div>
            </div>
            {/* Video action icons */}
            <div className="flex items-center gap-2 text-white">
              <button className="p-1.5 rounded hover:bg-black/40" title="Like">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" />
                </svg>
              </button>
              <button className="p-1.5 rounded hover:bg-black/40" title="Watch Later">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" />
                </svg>
              </button>
              <button className="p-1.5 rounded hover:bg-black/40" title="Share">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" />
                </svg>
              </button>
            </div>
          </div>

          {/* Video Player Bottom Bar Simulation */}
          <div className="absolute bottom-3 left-4 right-4 flex items-center justify-between text-white text-[11px] font-mono z-20">
            <div className="flex items-center gap-3">
              <span className="bg-black/60 px-2 py-0.5 rounded text-[10px]">01:05</span>
            </div>
            <div className="flex items-center gap-3">
              <button className="hover:text-neutral-300">HD</button>
              <button className="hover:text-neutral-300">CC</button>
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
