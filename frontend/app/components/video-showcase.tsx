export default function VideoShowcase() {
  // Same wave envelope as the in-app live discussion visualizer
  const waveBars = Array.from({ length: 33 }, (_, i) => {
    const envelope = Math.sin((i / 32) * Math.PI);
    return Math.max(8, Math.round(8 + envelope * 72));
  });

  return (
    <section className="bg-[#f5f3ef] pb-24 pt-8" data-purpose="video-demonstration" id="action-video">
      <div className="max-w-6xl mx-auto px-6 sm:px-12">
        {/* Section Title with trailing line */}
        <div className="flex items-center gap-4 mb-8">
          <h3 className="text-xl sm:text-2xl font-bold text-[#0b1c2b] tracking-tight whitespace-nowrap">
            See Endod AI in action
          </h3>
          <div className="w-full h-[1px] bg-stone-300" />
        </div>

        {/* Live Discussion preview — mirrors the in-app live consultation screen */}
        <div
          className="rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-stone-900/10 overflow-hidden"
          data-purpose="live-discussion-preview"
        >
          {/* App header: logo + patient chip */}
          <div className="flex items-center justify-between px-4 sm:px-5 py-3 border-b border-slate-200 bg-white">
            <img
              alt="ENDOD Health logo"
              className="h-8 sm:h-9 w-auto object-contain"
              src="/endod_logo.png"
            />
            <div className="flex items-center gap-2 py-0.5">
              <div className="w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-700 flex-shrink-0">
                <svg className="w-4 h-4 text-emerald-700" fill="currentColor" viewBox="0 0 20 20">
                  <path clipRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" fillRule="evenodd" />
                </svg>
              </div>
              <div className="text-left text-xs leading-tight hidden sm:block">
                <div className="font-bold text-slate-800 flex items-center">
                  Daniel Everett
                  <svg className="w-3.5 h-3.5 text-slate-500 ml-0.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path d="M19 9l-7 7-7-7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <div className="text-slate-400 text-[11px]">Patient</div>
              </div>
            </div>
          </div>

          {/* Live consultation area */}
          <div className="p-3 sm:p-4 bg-[#F6F9FA] space-y-3 sm:space-y-4">
            {/* Video stage with AI speaking sound wave */}
            <div
              className="relative w-full h-64 sm:h-80 rounded-2xl overflow-hidden border border-slate-200 bg-white flex items-center justify-center"
              data-purpose="video-consultation-stage"
            >
              {/* AI Speaking Sound Wave Signal */}
              <div className="speaking absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20 flex items-center justify-center">
                <div className="relative flex items-center justify-center">
                  {/* soft signal glow */}
                  <span aria-hidden="true" className="absolute -inset-10 rounded-full bg-cyan-400/10 blur-3xl"></span>
                  <div className="relative flex items-center justify-center gap-[3px] sm:gap-1 h-20 sm:h-24">
                    {waveBars.map((height, i) => (
                      <span
                        key={i}
                        className="wave-bar w-[3px] sm:w-1 rounded-full bg-gradient-to-t from-teal-500 via-cyan-400 to-emerald-300 shadow-[0_0_6px_rgba(34,211,238,0.35)]"
                        style={{ height: `${height}px`, animationDelay: `${(i * 0.045).toFixed(3)}s` }}
                      ></span>
                    ))}
                  </div>
                </div>
              </div>

              {/* Top-right: HD quality + Fullscreen (zoom) */}
              <div className="absolute top-3 sm:top-4 right-3 sm:right-4 flex items-center space-x-1.5 sm:space-x-2">
                <span className="bg-slate-100 text-slate-700 text-[10px] sm:text-[11px] font-bold px-1.5 sm:px-2 py-0.5 sm:py-1 rounded">HD</span>
                <div className="bg-slate-100 p-1.5 rounded text-slate-600">
                  <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
              </div>
            </div>

            {/* Call Control Bar */}
            <div
              className="bg-white border border-slate-200 rounded-2xl py-3 px-4 sm:px-6 shadow-md flex items-center justify-between"
              data-purpose="call-controls"
            >
              <div className="flex items-center space-x-4 sm:space-x-8 mx-auto md:mx-0">
                {/* Mic */}
                <div className="flex flex-col items-center">
                  <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-full flex items-center justify-center bg-slate-100 text-slate-600">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                  <span className="text-[10px] sm:text-[11px] mt-1 text-slate-500">Mic</span>
                </div>
                {/* Speaker */}
                <div className="flex flex-col items-center">
                  <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-full flex items-center justify-center bg-slate-100 text-slate-600">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                  <span className="text-[10px] sm:text-[11px] mt-1 text-slate-500">Speaker</span>
                </div>
                {/* Pause */}
                <div className="flex flex-col items-center">
                  <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-full flex items-center justify-center bg-slate-100 text-slate-600">
                    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M6 4h4v16H6zM14 4h4v16h-4z" />
                    </svg>
                  </div>
                  <span className="text-[10px] sm:text-[11px] mt-1 text-slate-500">Pause</span>
                </div>
              </div>
              {/* End Consultation */}
              <div className="flex items-center space-x-2 bg-[#D92D20] text-white font-semibold px-4 sm:px-6 py-2.5 rounded-full shadow-md">
                <svg className="w-4 h-4 transform rotate-[135deg]" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M2 3a1 1 0 011-1h2.153a1 1 0 01.986.836l.74 4.435a1 1 0 01-.54 1.06l-1.548.773a11.037 11.037 0 006.105 6.105l.774-1.548a1 1 0 011.059-.54l4.435.74a1 1 0 01.836.986V17a1 1 0 01-1 1h-2C7.82 18 2 12.18 2 4V3z" />
                </svg>
                <span className="text-xs hidden sm:inline">End Consultation</span>
                <span className="text-xs sm:hidden">End</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
