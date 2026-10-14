"use client";

export default function Footer() {
  return (
    <footer className="bg-[#111111] text-white pt-16 pb-12 border-t border-white/10" data-purpose="site-footer">
      <div className="max-w-7xl mx-auto px-6 sm:px-12">
        {/* Top Grid: Contact + Platform + Company */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-12 pb-16">
          {/* Column 1: Get started / Ready to take control of your health? */}
          <div className="md:col-span-5 pr-4">
            <p className="text-xs uppercase font-medium tracking-wider text-neutral-400 mb-2">
              Contact Us
            </p>
            <h3 className="text-3xl sm:text-4xl font-serif text-white tracking-tight mb-8">
              Ready to take control of your health?
            </h3>
            <form className="space-y-4 max-w-sm" onSubmit={() => {
              alert('Subscribed successfully!');
            }}>
              <div>
                <label className="block text-[11px] font-bold tracking-wider uppercase text-neutral-300 mb-1" htmlFor="footer-email">
                  ENTER YOUR EMAIL
                </label>
                <input
                  className="w-full bg-transparent border-0 border-b border-neutral-600 focus:border-white focus:ring-0 px-0 py-2 text-sm text-white placeholder:text-neutral-500"
                  id="footer-email"
                  placeholder="email@email.com"
                  required
                  type="email"
                />
              </div>
              <button className="w-full py-2.5 px-6 border border-neutral-400 text-white hover:bg-white hover:text-black transition-all text-sm font-medium tracking-wide" type="submit">
                Subscribe
              </button>
            </form>
          </div>

          {/* Column 2: Platform Links */}
          <div className="md:col-span-4">
            <p className="text-xs uppercase font-medium tracking-wider text-neutral-400 mb-4">
              Platform
            </p>
            <ul className="space-y-3 text-sm text-neutral-300">
              <li><a className="hover:text-white transition-colors" href="#build-own-lab">AI Symptom Assistant</a></li>
              <li><a className="hover:text-white transition-colors" href="#cloud-lab">Hospital Directory &amp; Booking</a></li>
              <li><a className="hover:text-white transition-colors" href="#pipette-hero-card">Treatment Plans</a></li>
              <li><a className="hover:text-white transition-colors" href="#pipette-hero-card">Medical History</a></li>
              <li><a className="hover:text-white transition-colors" href="#bottleneck">Consent &amp; Privacy</a></li>
              <li><a className="hover:text-white transition-colors" href="#cloud-lab">For Hospitals</a></li>
            </ul>
          </div>

          {/* Column 3: Company Links */}
          <div className="md:col-span-3">
            <p className="text-xs uppercase font-medium tracking-wider text-neutral-400 mb-4">
              Company
            </p>
            <ul className="space-y-3 text-sm text-neutral-300">
              <li><a className="hover:text-white transition-colors" href="#">About</a></li>
              <li><a className="hover:text-white transition-colors" href="#contact-section">Contact</a></li>
              <li><a className="hover:text-white transition-colors" href="#">Careers</a></li>
              <li><a className="hover:text-white transition-colors" href="#bottleneck">Privacy &amp; Security</a></li>
              <li><a className="hover:text-white transition-colors" href="#">Support</a></li>
            </ul>
          </div>
        </div>

        {/* Footer Middle: Logo */}
        <div className="py-6 border-t border-neutral-800">
          <div className="flex items-center gap-3">
            <img
              alt="ENDOD Health logo"
              className="h-9 w-auto object-contain"
              src="/endod_logo.png"
            />
            <div className="leading-none">
              <span className="block text-base font-black tracking-widest uppercase">ENDOD</span>
              <span className="block text-[11px] font-light tracking-[0.24em] text-neutral-400 uppercase">HEALTH OS</span>
            </div>
          </div>
        </div>

        {/* Footer Bottom: Legal & Social Links */}
        <div className="pt-4 border-t border-neutral-800 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-neutral-400">
          <div className="flex items-center gap-2">
            <a className="hover:text-white transition-colors" href="#">Terms &amp; Conditions</a>
            <span>|</span>
            <span>© Copyright Endod Health OS 2025</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="uppercase tracking-wider text-[11px] font-semibold text-neutral-300">FOLLOW US</span>
            {/* LinkedIn */}
            <a aria-label="LinkedIn" className="text-white hover:text-neutral-300 transition-colors" href="#">
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z" />
              </svg>
            </a>
            {/* X / Twitter */}
            <a aria-label="X (formerly Twitter)" className="text-white hover:text-neutral-300 transition-colors" href="#">
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
              </svg>
            </a>
            {/* Facebook */}
            <a aria-label="Facebook" className="text-white hover:text-neutral-300 transition-colors" href="#">
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M9 8H6v4h3v12h5V12h3.642L18 8h-4V6.333C14 5.374 14.5 5 15.5 5H18V0h-3.808C10.596 0 9 1.583 9 4.615V8z" />
              </svg>
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
