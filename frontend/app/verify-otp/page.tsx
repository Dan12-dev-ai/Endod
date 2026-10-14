"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

type Testimonial = {
  quote: string;
  name: string;
  title: string;
  initials: string;
};

const testimonials: Testimonial[] = [
  {
    quote:
      "By uncovering data-driven insights, Endod gives clinicians an unprecedented view of each patient's unique needs. This enables truly tailored care while reducing administrative tasks through automation.",
    name: "Paul Lefever",
    title: "Psychiatric Nurse Practitioner",
    initials: "PL",
  },
  {
    quote:
      "It's really exciting that clinicians will be able to understand their patients' behaviors without all the pressure being on patients to remember and recall everything. That is very useful for improving treatment outcomes.",
    name: "Katherine Jonas",
    title: "PhD, Licensed Psychologist",
    initials: "KJ",
  },
];

const RESEND_COOLDOWN_SECONDS = 60;

export default function VerifyOtpPage() {
  // `useSearchParams()` needs a Suspense boundary so the route can be
  // prerendered; the actual form streams in after the shell.
  return (
    <Suspense
      fallback={
        <main className="w-full min-h-screen flex items-center justify-center bg-[#DDE9E6] text-brand-primary font-sans antialiased">
          <p className="text-sm text-brand-muted">Loading…</p>
        </main>
      }
    >
      <VerifyOtp />
    </Suspense>
  );
}

function VerifyOtp() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const phone = searchParams.get("phone") ?? "";

  // ===== Infinite sliding-window carousel =====
  const slideCount = testimonials.length;
  const extended = [testimonials[slideCount - 1], ...testimonials, testimonials[0]];
  const [currentIndex, setCurrentIndex] = useState(1);
  const [isAnimating, setIsAnimating] = useState(true);

  const move = (direction: number) => {
    setIsAnimating(true);
    setCurrentIndex((index) => index + direction);
  };

  const handleTransitionEnd = () => {
    if (currentIndex === 0) {
      setIsAnimating(false);
      setCurrentIndex(slideCount);
    } else if (currentIndex === slideCount + 1) {
      setIsAnimating(false);
      setCurrentIndex(1);
    }
  };

  useEffect(() => {
    const interval = setInterval(() => {
      setIsAnimating(true);
      setCurrentIndex((index) => index + 1);
    }, 5000);
    return () => clearInterval(interval);
  }, [slideCount]);

  // ===== OTP form =====
  const [digits, setDigits] = useState<string[]>(["", "", "", "", "", ""]);
  const [formError, setFormError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(RESEND_COOLDOWN_SECONDS);

  // Resend cooldown timer
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = setInterval(() => setResendCooldown((value) => value - 1), 1000);
    return () => clearInterval(timer);
  }, [resendCooldown]);

  const setDigit = (position: number, value: string) => {
    const clean = value.replace(/\D/g, "").slice(-1);
    setDigits((previous) => {
      const next = [...previous];
      next[position] = clean;
      return next;
    });
    setFormError("");
  };

  const handleDigitInput = (position: number, value: string) => {
    setDigit(position, value);
    if (value && position < 5) {
      document.getElementById(`otp-${position + 1}`)?.focus();
    }
  };

  const handleKeyDown = (position: number, event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Backspace" && !digits[position] && position > 0) {
      event.preventDefault();
      setDigit(position - 1, "");
      document.getElementById(`otp-${position - 1}`)?.focus();
    }
  };

  const handleVerify = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError("");

    const code = digits.join("");
    if (code.length !== 6) {
      setFormError("Please enter the complete 6-digit code.");
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await fetch("/api/auth/verify-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, code }),
      });
      const data = await response.json();

      if (!response.ok || !data.ok) {
        setFormError(data.error ?? "That code didn't work. Please try again.");
        return;
      }

      // Verified — set a password before onboarding.
      router.push(`/set-password?phone=${encodeURIComponent(phone)}`);
    } catch {
      setFormError("Unable to verify right now. Please check your connection and try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResend = async () => {
    if (resendCooldown > 0) return;
    setFormError("");
    try {
      await fetch("/api/auth/resend-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone }),
      });
      setResendCooldown(RESEND_COOLDOWN_SECONDS);
    } catch {
      setFormError("Unable to resend the code right now. Please try again.");
    }
  };

  const renderSlide = (item: Testimonial) => (
    <>
      <blockquote className="font-serif text-xl sm:text-2xl lg:text-[24px] xl:text-[26px] text-brand-heading quote-text font-normal mb-6 leading-snug">
        &ldquo;{item.quote}&rdquo;
      </blockquote>

      <div className="flex items-center space-x-3 mb-6">
        <div className="w-10 h-10 rounded-full bg-[#C8DBD7] border border-[#BACFCB] flex items-center justify-center font-bold text-brand-primary text-sm overflow-hidden flex-shrink-0">
          {item.initials}
        </div>
        <div>
          <p className="font-semibold text-brand-heading text-sm sm:text-base leading-tight">{item.name}</p>
          <p className="text-xs sm:text-sm text-brand-muted font-normal leading-tight mt-0.5">{item.title}</p>
        </div>
      </div>
    </>
  );

  return (
    <main
      className="w-full min-h-screen flex items-center justify-center py-6 px-4 sm:px-8 lg:px-16 bg-[#DDE9E6] text-brand-primary font-sans antialiased"
      data-purpose="page-wrapper"
    >
      <div className="max-w-[1360px] w-full grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-8 items-center my-auto">
        {/* BEGIN: LeftColumn */}
        <section
          className="lg:col-span-6 xl:col-span-6 flex flex-col justify-between pt-2 pb-6 lg:py-4 lg:pr-8 xl:pr-12"
          data-purpose="social-proof-and-branding"
        >
          <div>
            <div className="mb-10 lg:mb-12" data-purpose="brand-logo">
              <h1 className="text-2xl font-extrabold tracking-tight text-brand-heading">Endod</h1>
            </div>

            <div className="mb-10" data-purpose="quote-carousel" id="testimonial-container">
              <div className="overflow-hidden">
                <div
                  className={`flex ease-in-out ${isAnimating ? "transition-transform duration-500" : ""}`}
                  onTransitionEnd={handleTransitionEnd}
                  style={{ transform: `translateX(-${currentIndex * 100}%)` }}
                >
                  {extended.map((item, index) => (
                    <div className="w-full flex-shrink-0" key={index}>
                      {renderSlide(item)}
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex items-center space-x-2.5 pt-1" data-purpose="carousel-controls">
                <button
                  aria-label="Previous quote"
                  className="w-8 h-8 rounded-full bg-white/70 hover:bg-white text-brand-heading transition-colors flex items-center justify-center shadow-xs focus:outline-hidden"
                  onClick={() => move(-1)}
                  type="button"
                >
                  <svg className="w-4 h-4 stroke-[2.2]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path d="M15 19l-7-7 7-7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
                <button
                  aria-label="Next quote"
                  className="w-8 h-8 rounded-full bg-white/70 hover:bg-white text-brand-heading transition-colors flex items-center justify-center shadow-xs focus:outline-hidden"
                  onClick={() => move(1)}
                  type="button"
                >
                  <svg className="w-4 h-4 stroke-[2.2]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          <footer className="mt-8 pt-6" data-purpose="partner-logos-section">
            <div className="flex items-center space-x-4 mb-5">
              <span className="text-xs italic text-brand-heading/75 font-serif tracking-normal whitespace-nowrap">
                Trusted by world&apos;s leading organizations
              </span>
              <div className="h-[1px] bg-brand-heading/15 flex-grow" />
            </div>

            <div className="flex flex-wrap items-center gap-6 sm:gap-8 opacity-75">
              <div className="flex items-center space-x-2 text-brand-heading/80">
                <svg className="w-6 h-6 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="9.5" />
                  <path d="M12 2.5a9.5 9.5 0 0 1 0 19" />
                  <path d="M7 12c0-2.8 2.2-5 5-5s5 2.2 5 5-2.2 5-5 5" />
                </svg>
                <div className="leading-none">
                  <span className="block text-[10px] tracking-widest font-semibold uppercase">PRECISION</span>
                  <span className="block text-[8px] tracking-wider text-brand-muted uppercase">MENTAL HEALTH</span>
                </div>
              </div>

              <div className="flex items-center space-x-2 text-brand-heading/80">
                <svg className="w-6 h-6 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24">
                  <rect height="18" rx="5" width="18" x="3" y="3" />
                  <path d="M12 7v10M7 12h10" />
                </svg>
                <span className="text-xs font-semibold tracking-wide">MINDPATH CARE</span>
              </div>

              <div className="flex items-center space-x-2 text-brand-heading/80">
                <svg className="w-6 h-6 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24">
                  <path d="M3 12h4l3-6 4 12 3-6h4" />
                </svg>
                <span className="text-xs font-semibold tracking-wide">CLINICALPULSE</span>
              </div>
            </div>
          </footer>
        </section>
        {/* END: LeftColumn */}

        {/* BEGIN: RightColumn (Verify Card) */}
        <section className="lg:col-span-6 xl:col-span-6 flex justify-end" data-purpose="verify-form-card">
          <div className="w-full max-w-[540px] bg-white rounded-[32px] shadow-xl shadow-teal-950/5 border border-slate-100 p-8 sm:p-10 lg:p-11">
            <h2 className="font-serif text-4xl sm:text-[42px] font-medium text-brand-heading tracking-tight mb-3">
              Verify your phone
            </h2>
            <p className="text-sm text-brand-muted mb-7 leading-relaxed">
              We sent a 6-digit code to{" "}
              <span className="font-semibold text-brand-heading">{phone || "your phone"}</span>. Enter it below to
              continue.
            </p>

            <form className="space-y-5" data-purpose="verify-form" onSubmit={handleVerify}>
              <div className="flex items-center justify-between gap-2 sm:gap-3" data-purpose="otp-inputs">
                {digits.map((digit, index) => (
                  <input
                    autoFocus={index === 0}
                    className="field-input w-12 sm:w-14 h-14 text-center text-lg font-semibold rounded-xl border focus:outline-hidden text-slate-800"
                    id={`otp-${index}`}
                    inputMode="numeric"
                    key={index}
                    maxLength={1}
                    onChange={(event) => handleDigitInput(index, event.target.value)}
                    onKeyDown={(event) => handleKeyDown(index, event)}
                    type="text"
                    value={digit}
                  />
                ))}
              </div>

              {formError && (
                <p
                  className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2"
                  data-purpose="form-error"
                  role="alert"
                >
                  {formError}
                </p>
              )}

              <div className="pt-1">
                <button
                  className="w-full bg-[#E5ECEB] hover:bg-[#D5E3E0] active:scale-[0.99] text-brand-heading/80 font-medium py-3 rounded-full text-sm transition-all focus:outline-hidden disabled:opacity-60 disabled:cursor-not-allowed disabled:active:scale-100"
                  disabled={isSubmitting}
                  type="submit"
                >
                  {isSubmitting ? "Verifying..." : "Verify"}
                </button>
              </div>

              <div className="text-center pt-1 space-y-2">
                <p className="text-xs text-brand-muted">
                  Didn&apos;t receive the code?{" "}
                  <button
                    className="text-brand-accent font-semibold hover:underline disabled:text-brand-muted disabled:no-underline disabled:cursor-not-allowed"
                    disabled={resendCooldown > 0}
                    onClick={handleResend}
                    type="button"
                  >
                    {resendCooldown > 0 ? `Resend in ${resendCooldown}s` : "Resend code"}
                  </button>
                </p>
                <p className="text-xs text-brand-muted">
                  Wrong number?{" "}
                  <button
                    className="text-brand-accent font-semibold hover:underline"
                    onClick={() => router.push("/signup")}
                    type="button"
                  >
                    Go back
                  </button>
                </p>
              </div>
            </form>

            <aside
              className="mt-8 pt-5 border-t border-slate-100 flex items-start space-x-3 text-[11px] text-brand-muted leading-snug"
              data-purpose="security-compliance-badge"
            >
              <div className="shrink-0 text-brand-accent/80 mt-0.5">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                  <path d="M12 2v19M8 6c2-1 6-1 8 0M7 11c2.5-1.5 7.5-1.5 10 0M8 16c2-1 6-1 8 0M12 2c-1.5 0-3 1.5-3 3s1.5 3 3 3 3-1.5 3-3-1.5-3-3-3z" />
                </svg>
              </div>
              <p>
                We prioritize data security and patient privacy, exceeding HIPAA compliance standards to provide the
                highest level of protection.
              </p>
            </aside>
          </div>
        </section>
        {/* END: RightColumn */}
      </div>
    </main>
  );
}
