"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { safeNext } from "@/app/lib/api";
import { useI18n, type TranslationKey } from "@/app/lib/i18n";
import { syncLanguageAfterSignIn } from "@/app/components/language-switcher";
import { forgetSession } from "@/app/lib/session";

type Testimonial = {
  quoteKey: TranslationKey;
  titleKey: TranslationKey;
  name: string;
  initials: string;
};

// Names are proper nouns and stay as written; the quote and role translate.
const testimonialData: Testimonial[] = [
  {
    quoteKey: "testimonial.1.quote",
    titleKey: "testimonial.1.title",
    name: "Paul Lefever",
    initials: "PL",
  },
  {
    quoteKey: "testimonial.2.quote",
    titleKey: "testimonial.2.title",
    name: "Katherine Jonas",
    initials: "KJ",
  },
];

export default function LoginPage() {
  const router = useRouter();
  const { t } = useI18n();

  // ===== Infinite sliding-window carousel =====
  const slideCount = testimonialData.length;
  const extended = [testimonialData[slideCount - 1], ...testimonialData, testimonialData[0]];
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

  // ===== Sign-in form =====
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [formError, setFormError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError("");

    if (!phone.trim()) {
      setFormError(t("login.error.phone"));
      return;
    }
    if (!password) {
      setFormError(t("login.error.password"));
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier: phone, password }),
      });
      const data = await response.json();

      if (!response.ok || !data.ok) {
        setFormError(data.error ?? t("common.somethingWrong"));
        return;
      }

      // The session is an httpOnly cookie set by the route handler.
      forgetSession();
      await syncLanguageAfterSignIn();
      router.push(safeNext(new URLSearchParams(window.location.search).get("next"), "/interview"));
    } catch {
      setFormError(t("login.error.generic"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const renderSlide = (item: Testimonial) => (
    <>
      <blockquote className="font-serif text-xl sm:text-2xl lg:text-[24px] xl:text-[26px] text-brand-heading quote-text font-normal mb-6 leading-snug">
        &ldquo;{t(item.quoteKey)}&rdquo;
      </blockquote>

      <div className="flex items-center space-x-3 mb-6">
        <div className="w-10 h-10 rounded-full bg-[#C8DBD7] border border-[#BACFCB] flex items-center justify-center font-bold text-brand-primary text-sm overflow-hidden flex-shrink-0">
          {item.initials}
        </div>
        <div>
          <p className="font-semibold text-brand-heading text-sm sm:text-base leading-tight">{item.name}</p>
          <p className="text-xs sm:text-sm text-brand-muted font-normal leading-tight mt-0.5">{t(item.titleKey)}</p>
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
              <h1 className="text-2xl font-extrabold tracking-tight text-brand-heading">{t("common.endod")}</h1>
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
                  aria-label={t("login.prevQuote")}
                  className="w-8 h-8 rounded-full bg-white/70 hover:bg-white text-brand-heading transition-colors flex items-center justify-center shadow-xs focus:outline-hidden"
                  onClick={() => move(-1)}
                  type="button"
                >
                  <svg className="w-4 h-4 stroke-[2.2]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path d="M15 19l-7-7 7-7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
                <button
                  aria-label={t("login.nextQuote")}
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
                {t("common.trustedBy")}
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
        {/* BEGIN: RightColumn (Sign-In Card) */}
        <section className="lg:col-span-6 xl:col-span-6 flex justify-end" data-purpose="login-form-card">
          <div className="w-full max-w-[540px] bg-white rounded-[32px] shadow-xl shadow-teal-950/5 border border-slate-100 p-8 sm:p-10 lg:p-11">
            {/* Card Heading */}
            <h2 className="font-serif text-4xl sm:text-[42px] font-medium text-brand-heading tracking-tight mb-2">
              {t("login.title")}
            </h2>
            <p className="text-sm text-brand-muted mb-7">
              {t("login.subtitle")}
            </p>

            <form className="space-y-4" data-purpose="login-form" onSubmit={handleSubmit}>
              {/* Phone Number Input Field */}
              <div data-purpose="form-field-phone">
                <label className="block text-xs font-semibold text-brand-heading mb-1.5" htmlFor="phone">
                  {t("login.phoneLabel")}
                </label>
                <input
                  className="field-input w-full px-4 py-2.5 rounded-xl text-sm border focus:outline-hidden placeholder:text-slate-400"
                  id="phone"
                  name="phone"
                  onChange={(event) => {
                    setPhone(event.target.value);
                    setFormError("");
                  }}
                  placeholder="09XXXXXXXX"
                  type="tel"
                  value={phone}
                />
                <p className="mt-1.5 text-[11px] text-brand-muted">
                  {t("login.phoneHint")}
                </p>
              </div>

              {/* Password Input Field */}
              <div data-purpose="form-field-password">
                <label className="block text-xs font-semibold text-brand-heading mb-1.5" htmlFor="password">
                  {t("login.passwordLabel")}
                </label>
                <div className="relative">
                  <input
                    autoComplete="current-password"
                    className="field-input w-full px-4 py-2.5 pr-10 rounded-xl text-sm border focus:outline-hidden text-slate-800 tracking-wider"
                    id="password"
                    onChange={(event) => {
                      setPassword(event.target.value);
                      setFormError("");
                    }}
                    type={showPassword ? "text" : "password"}
                    value={password}
                  />
                  <button
                    aria-label={showPassword ? t("common.hidePassword") : t("common.showPassword")}
                    className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-400 hover:text-brand-heading focus:outline-hidden"
                    onClick={() => setShowPassword((visible) => !visible)}
                    type="button"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
                      <path
                        d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                </div>
              </div>

              <div className="text-right -mt-1">
                <Link className="text-[11px] text-brand-accent font-semibold hover:underline" href="/signup?reset=1">
                  {t("login.forgotPassword")}
                </Link>
              </div>

              {/* Form Error Message */}
              {formError && (
                <p
                  className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2"
                  data-purpose="form-error"
                  role="alert"
                >
                  {formError}
                </p>
              )}

              {/* Submit Button */}
              <div className="pt-2">
                <button
                  className="w-full bg-[#E5ECEB] hover:bg-[#D5E3E0] active:scale-[0.99] text-brand-heading/80 font-medium py-3 rounded-full text-sm transition-all focus:outline-hidden disabled:opacity-60 disabled:cursor-not-allowed disabled:active:scale-100"
                  disabled={isSubmitting}
                  type="submit"
                >
                  {isSubmitting ? t("login.submitting") : t("login.submit")}
                </button>
              </div>

              {/* Sign Up Navigation Prompt */}
              <div className="text-center pt-1">
                <p className="text-xs text-brand-muted">
                  {t("login.newTo")}{" "}
                  <Link className="text-brand-accent font-semibold hover:underline" href="/signup">
                    {t("login.signUp")}
                  </Link>
                </p>
              </div>
            </form>

            {/* HIPAA Compliance Badge & Notice */}
            <aside
              className="mt-8 pt-5 border-t border-slate-100 flex items-start space-x-3 text-[11px] text-brand-muted leading-snug"
              data-purpose="security-compliance-badge"
            >
              <div className="shrink-0 text-brand-accent/80 mt-0.5">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                  <path d="M12 2v19M8 6c2-1 6-1 8 0M7 11c2.5-1.5 7.5-1.5 10 0M8 16c2-1 6-1 8 0M12 2c-1.5 0-3 1.5-3 3s1.5 3 3 3 3-1.5 3-3-1.5-3-3-3z" />
                </svg>
              </div>
              <p>{t("common.secureNotice")}</p>
            </aside>
          </div>
        </section>
        {/* END: RightColumn */}
      </div>
    </main>
  );
}
