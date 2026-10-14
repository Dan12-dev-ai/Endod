export default function SocialLinks() {
  return (
    <section className="bg-[#f5f3ef] py-16 lg:py-24" data-purpose="social-links" id="social-links">
      <div className="max-w-6xl mx-auto px-6 sm:px-12 text-center">
        {/* Overline label */}
        <div className="mb-8">
          <span className="inline-block text-[11px] font-bold uppercase tracking-widest text-slate-800 border-b-2 border-slate-900 pb-0.5">
            FOLLOW US
          </span>
        </div>

        {/* Four company social icons */}
        <div className="flex items-center justify-center gap-4 sm:gap-6">
          {/* LinkedIn */}
          <a
            aria-label="LinkedIn"
            className="w-12 h-12 sm:w-14 sm:h-14 rounded-full border border-slate-300 bg-white/70 text-slate-700 hover:bg-slate-900 hover:border-slate-900 hover:text-white flex items-center justify-center transition-all shadow-sm"
            href="#"
          >
            <svg className="w-5 h-5 sm:w-6 sm:h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z" />
            </svg>
          </a>

          {/* X (formerly Twitter) */}
          <a
            aria-label="X (formerly Twitter)"
            className="w-12 h-12 sm:w-14 sm:h-14 rounded-full border border-slate-300 bg-white/70 text-slate-700 hover:bg-slate-900 hover:border-slate-900 hover:text-white flex items-center justify-center transition-all shadow-sm"
            href="#"
          >
            <svg className="w-5 h-5 sm:w-6 sm:h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
            </svg>
          </a>

          {/* Facebook */}
          <a
            aria-label="Facebook"
            className="w-12 h-12 sm:w-14 sm:h-14 rounded-full border border-slate-300 bg-white/70 text-slate-700 hover:bg-slate-900 hover:border-slate-900 hover:text-white flex items-center justify-center transition-all shadow-sm"
            href="#"
          >
            <svg className="w-5 h-5 sm:w-6 sm:h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M9 8H6v4h3v12h5V12h3.642L18 8h-4V6.333C14 5.374 14.5 5 15.5 5H18V0h-3.808C10.596 0 9 1.583 9 4.615V8z" />
            </svg>
          </a>

          {/* Instagram */}
          <a
            aria-label="Instagram"
            className="w-12 h-12 sm:w-14 sm:h-14 rounded-full border border-slate-300 bg-white/70 text-slate-700 hover:bg-slate-900 hover:border-slate-900 hover:text-white flex items-center justify-center transition-all shadow-sm"
            href="#"
          >
            <svg className="w-5 h-5 sm:w-6 sm:h-6" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 0C8.74 0 8.333.015 7.053.072 5.775.132 4.905.333 4.14.63c-.789.306-1.459.717-2.126 1.384S.935 3.35.63 4.14C.333 4.905.131 5.775.072 7.053.012 8.333 0 8.74 0 12s.015 3.667.072 4.947c.06 1.277.261 2.148.558 2.913.306.788.717 1.459 1.384 2.126.667.666 1.336 1.079 2.126 1.384.766.296 1.636.499 2.913.558C8.333 23.988 8.74 24 12 24s3.667-.015 4.947-.072c1.277-.06 2.148-.262 2.913-.558.788-.306 1.459-.718 2.126-1.384.666-.667 1.079-1.335 1.384-2.126.296-.765.499-1.636.558-2.913.06-1.28.072-1.687.072-4.947s-.015-3.667-.072-4.947c-.06-1.277-.262-2.149-.558-2.913-.306-.789-.718-1.459-1.384-2.126C21.319 1.347 20.651.935 19.86.63c-.765-.297-1.636-.499-2.913-.558C15.667.012 15.26 0 12 0zm0 2.16c3.203 0 3.585.016 4.85.071 1.17.055 1.805.249 2.227.415.562.217.96.477 1.382.899.419.42.679.819.896 1.381.164.422.36 1.057.413 2.227.057 1.266.07 1.646.07 4.85s-.015 3.585-.074 4.85c-.061 1.17-.256 1.805-.421 2.227-.224.562-.479.96-.899 1.382-.419.419-.824.679-1.38.896-.42.164-1.065.36-2.235.413-1.274.057-1.649.07-4.859.07-3.211 0-3.586-.015-4.859-.074-1.171-.061-1.816-.256-2.236-.421-.569-.224-.96-.479-1.379-.899-.421-.419-.69-.824-.9-1.38-.165-.42-.359-1.065-.42-2.235-.045-1.26-.061-1.649-.061-4.844 0-3.196.016-3.586.061-4.861.061-1.17.255-1.814.42-2.234.21-.57.479-.96.9-1.381.419-.419.81-.689 1.379-.898.42-.166 1.051-.361 2.221-.421 1.275-.045 1.65-.06 4.859-.06l.045.03zm0 3.678a6.162 6.162 0 100 12.324 6.162 6.162 0 100-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm7.846-10.405a1.441 1.441 0 01-2.88 0 1.44 1.44 0 012.88 0z" />
            </svg>
          </a>
        </div>
      </div>
    </section>
  );
}
