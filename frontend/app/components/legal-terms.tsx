import { Instrument_Serif } from "next/font/google";
import Header from "./header";
import Footer from "./footer";

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  style: ["normal", "italic"],
  weight: ["400"],
  display: "swap",
});

export default function LegalTerms() {
  return (
    <>
      <Header />
      <div
      className="min-h-screen bg-[#fbf8f5] text-[#2d3748] antialiased"
      style={{ fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" }}
    >
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-16 pt-24 sm:pt-32 pb-16 sm:pb-24">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-16 items-start">
          <aside
            aria-label="Legal documents navigation"
            className="lg:col-span-3 pt-3 lg:sticky lg:top-12 mb-8 lg:mb-0"
          >
            <nav
              className="flex flex-col space-y-5 text-[15px]"
              data-purpose="legal-nav"
            >
              <div>
                <a
                  aria-current="page"
                  className="font-bold text-[#0f1c2e] pb-1 border-b-2 border-[#0f1c2e] inline-block tracking-tight"
                  href="#"
                >
                  General Terms &amp; Conditions
                </a>
              </div>
              <div>
                <a
                  className="text-[#334155] hover:text-[#0f1c2e] transition-colors duration-150 font-normal inline-block"
                  href="#"
                >
                  Equipment Terms
                </a>
              </div>
              <div>
                <a
                  className="text-[#334155] hover:text-[#0f1c2e] transition-colors duration-150 font-normal inline-block"
                  href="#"
                >
                  Software and Services
                </a>
              </div>
              <div>
                <a
                  className="text-[#334155] hover:text-[#0f1c2e] transition-colors duration-150 font-normal inline-block"
                  href="#"
                >
                  Cookie Declaration
                </a>
              </div>
              <div>
                <a
                  className="text-[#334155] hover:text-[#0f1c2e] transition-colors duration-150 font-normal inline-block"
                  href="#"
                >
                  Privacy Policy
                </a>
              </div>
            </nav>
          </aside>

          <main className="lg:col-span-9" id="main-content">
            <header className="mb-14">
              <h1
                className={`${instrumentSerif.className} text-[52px] sm:text-[68px] lg:text-[76px] font-normal leading-[1.08] text-[#0d1e38] mb-7`}
                style={{ letterSpacing: "-0.015em" }}
              >
                General Terms &amp; Conditions
              </h1>
              <div
                aria-hidden="true"
                className="w-full h-[2.5px] bg-[#0d1e38]"
                role="separator"
              />
            </header>

            <article
              className="max-w-4xl text-[16.5px] sm:text-[17px] leading-[1.65] text-[#243142]"
              data-purpose="terms-article"
            >
              <p className="italic text-[#475569] mb-10 text-[16px]">
                Last Modified: December 2, 2025
              </p>

              <section
                aria-labelledby="section-1-heading"
                className="space-y-6"
              >
                <h2
                  className="font-bold text-[#0d1e38] tracking-tight text-[17px] uppercase mt-2 mb-5"
                  id="section-1-heading"
                >
                  1. DEFINITIONS
                </h2>
                <p className="text-justify sm:text-left">
                  (a) &ldquo;Aggregate Data&rdquo; means any data that is derived
                  or aggregated (i) in de-identified form from any Customer
                  Materials; or (ii) from Customer&rsquo;s and/or its Authorized
                  Users&rsquo; use of the Services, including, without limitation,
                  any usage data, failure and error information, insights, or
                  trends with respect to the Services. In no event will Aggregate
                  Data include data that includes any scientific results of
                  Customer&rsquo;s experiments.
                </p>
                <p className="text-justify sm:text-left">
                  (b) &ldquo;Authorized User&rdquo; means an employee or contractor
                  whom Customer has authorized to Use the Platform Services or
                  Software in accordance with this Agreement.
                </p>
                <p className="text-justify sm:text-left">
                  (c) &ldquo;Customer Data&rdquo; means all information, data,
                  content, and other materials, in any form or medium, that is
                  stored, uploaded, or made available by Customer or its Authorized
                  Users through the Platform Services or otherwise provided by or on
                  behalf of Customer to Ginkgo in connection with the Services.
                </p>
              </section>
            </article>
          </main>
        </div>
      </div>
      </div>
      <Footer />
    </>
  );
}