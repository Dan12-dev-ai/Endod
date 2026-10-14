"use client";

export default function ContactForm() {
  return (
    <section className="bg-[#f5f3ef] py-20 lg:py-28" data-purpose="lead-capture-form" id="contact-section">
      <div className="max-w-6xl mx-auto px-6 sm:px-12">
        {/* Outer Border Framing (Screenshot 10 & 11) */}
        <div className="border border-slate-800 bg-stone-50/70 p-8 sm:p-14 lg:p-16 rounded-sm shadow-sm">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-16 items-start">
            {/* Left Column: Title & Intro */}
            <div className="lg:col-span-5 pt-2">
              <span className="text-2xl text-slate-800 block mb-3 font-serif">→</span>
              <h2 className="text-4xl sm:text-5xl font-serif text-[#0b1c2b] tracking-tight leading-[1.08] mb-4">
                Get started with Endod Health OS
              </h2>
              <p className="text-stone-600 text-base sm:text-lg">
                Whether you&rsquo;re a patient or a hospital, tell us how we can help.
              </p>
            </div>

            {/* Right Column: Interactive Clean Underline Form */}
            <div className="lg:col-span-7 bg-white/60 p-6 sm:p-10 rounded-sm border border-stone-300/80 shadow-sm">
              <form className="space-y-7" onSubmit={() => {
              alert('Thank you! The Endod Health team will reach out shortly.');
            }}>
                {/* First Name */}
                <div>
                  <label className="block text-xs font-semibold text-slate-700 tracking-wide uppercase mb-1" htmlFor="first-name">
                    First Name *
                  </label>
                  <input
                    className="w-full bg-transparent border-0 border-b border-stone-400 focus:border-slate-900 focus:ring-0 px-0 py-2 text-slate-900 placeholder:text-stone-400 text-sm transition"
                    id="first-name"
                    placeholder="First Name"
                    required
                    type="text"
                  />
                </div>

                {/* Last Name */}
                <div>
                  <label className="block text-xs font-semibold text-slate-700 tracking-wide uppercase mb-1" htmlFor="last-name">
                    Last Name *
                  </label>
                  <input
                    className="w-full bg-transparent border-0 border-b border-stone-400 focus:border-slate-900 focus:ring-0 px-0 py-2 text-slate-900 placeholder:text-stone-400 text-sm transition"
                    id="last-name"
                    placeholder="Last Name"
                    required
                    type="text"
                  />
                </div>

                {/* Company Email */}
                <div>
                  <label className="block text-xs font-semibold text-slate-700 tracking-wide uppercase mb-1" htmlFor="email">
                    Email *
                  </label>
                  <input
                    className="w-full bg-transparent border-0 border-b border-stone-400 focus:border-slate-900 focus:ring-0 px-0 py-2 text-slate-900 placeholder:text-stone-400 text-sm transition"
                    id="email"
                    placeholder="Email"
                    required
                    type="email"
                  />
                </div>

                {/* Automation Goals */}
                <div>
                  <label className="block text-xs font-semibold text-slate-700 tracking-wide mb-1" htmlFor="goals">
                    Are you a patient or a hospital? How can we help? *
                  </label>
                  <textarea
                    className="w-full bg-transparent border-0 border-b border-stone-400 focus:border-slate-900 focus:ring-0 px-0 py-2 text-slate-900 placeholder:text-stone-400 text-sm resize-y transition"
                    id="goals"
                    placeholder="Tell us more"
                    required
                    rows={3}
                  />
                </div>

                {/* Submit Button */}
                <div className="pt-3">
                  <button className="w-full sm:w-auto min-w-[200px] px-8 py-3.5 bg-[#0e1c27] hover:bg-[#182c3c] text-white text-sm font-semibold tracking-wide rounded-sm transition duration-150 shadow-md" type="submit">
                    Contact Us
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
