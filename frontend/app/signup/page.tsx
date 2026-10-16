"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

type Testimonial = {
  quote: string;
  name: string;
  title: string;
  photo: string;
};

const testimonials: Testimonial[] = [
  {
    quote:
      "By uncovering data-driven insights, Endod gives clinicians an unprecedented view of each patient's unique needs. This enables truly tailored care while reducing administrative tasks through automation.",
    name: "Paul Lefever",
    title: "Psychiatric Nurse Practitioner",
    photo: "/images/testimonial-1.jpg",
  },
  {
    quote:
      "It's really exciting that clinicians will be able to understand their patients' behaviors without all the pressure being on patients to remember and recall everything. That is very useful for improving treatment outcomes.",
    name: "Katherine Jonas",
    title: "PhD, Licensed Psychologist",
    photo: "/images/testimonial-2.jpg",
  },
];

export default function SignUp() {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [formError, setFormError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [agree, setAgree] = useState(false);
  // "Forgot password?" on the login page uses the same phone code flow.
  const [isReset, setIsReset] = useState(false);
  /* eslint-disable react-hooks/set-state-in-effect -- read the query string once on mount */
  useEffect(() => {
    setIsReset(new URLSearchParams(window.location.search).get("reset") === "1");
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  // ===== Infinite sliding-window carousel =====
  // The track shows a clone of the last slide before the real slides and a
  // clone of the first slide after them. This lets the window keep moving in
  // one direction forever: when it reaches a boundary clone we jump
  // (transition off) to the matching real slide so the loop is seamless.
  const slideCount = testimonials.length;
  const extended = [testimonials[slideCount - 1], ...testimonials, testimonials[0]];
  const [currentIndex, setCurrentIndex] = useState(1);
  const [isAnimating, setIsAnimating] = useState(true);

  // Move one step in the given direction (+1 next, -1 prev).
  // (Used by the auto-advance interval; manual controls were removed.)

  // Fires after each slide transition; if we've landed on a boundary clone,
  // snap (without animation) to the equivalent real slide. Guarded so only the
  // track's own transform transition (not bubbled child transitions) triggers it.
  const handleTransitionEnd = (event: React.TransitionEvent<HTMLDivElement>) => {
    if (event.propertyName !== "transform" || event.target !== event.currentTarget) return;
    if (currentIndex === 0) {
      setIsAnimating(false);
      setCurrentIndex(slideCount);
    } else if (currentIndex === extended.length - 1) {
      setIsAnimating(false);
      setCurrentIndex(1);
    }
  };

  // Auto-advance on a fixed interval for an infinite slide effect.
  useEffect(() => {
    const interval = setInterval(() => {
      setIsAnimating(true);
      setCurrentIndex((previous) => previous + 1);
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  // Shared slide body rendered inside each slide of the horizontal track.
  const renderSlide = (item: Testimonial) => (
    <>
      <blockquote className="font-serif text-xl sm:text-2xl lg:text-[24px] xl:text-[26px] text-brand-heading quote-text font-normal mb-6 leading-snug">
        &ldquo;{item.quote}&rdquo;
      </blockquote>

      <div className="flex items-center space-x-3 mb-6">
        <img
          alt={item.name}
          className="w-10 h-10 rounded-full object-cover border border-[#BACFCB] flex-shrink-0"
          src={item.photo}
        />
        <div>
          <p className="font-semibold text-brand-heading text-sm sm:text-base leading-tight">{item.name}</p>
          <p className="text-xs sm:text-sm text-brand-muted font-normal leading-tight mt-0.5">{item.title}</p>
        </div>
      </div>
    </>
  );

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError("");

    if (!phone.trim()) {
      setFormError("Please enter your phone number.");
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await fetch("/api/auth/send-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone }),
      });
      const data = await response.json();

      if (!response.ok || !data.ok) {
        setFormError(data.error ?? "Something went wrong. Please try again.");
        return;
      }

      router.push(`/verify-otp?phone=${encodeURIComponent(phone)}`);
    } catch {
      setFormError("Unable to send the code right now. Please check your connection and try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

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
            {/* Logo */}
            <div className="mb-10 lg:mb-12" data-purpose="brand-logo">
              <h1 className="text-2xl font-extrabold tracking-tight text-brand-heading">Endod</h1>
            </div>

            {/* Testimonial Section */}
            <div className="mb-10" data-purpose="quote-carousel" id="testimonial-container">
              {/* Horizontal slide track (infinite): the current slide moves
                  left out of view while the next slides in from the right.
                  Boundary clones make the loop seamless. */}
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
            </div>
          </div>
        </section>
        {/* END: LeftColumn */}

        {/* BEGIN: RightColumn (Sign-Up Card) */}
        <section className="lg:col-span-6 xl:col-span-6 flex justify-end" data-purpose="registration-form-card">
          <div className="w-full max-w-[540px] bg-white rounded-[32px] shadow-xl shadow-teal-950/5 border border-slate-100 p-8 sm:p-10 lg:p-11">
            {/* Card Heading */}
            <h2 className="font-serif text-4xl sm:text-[42px] font-medium text-brand-heading tracking-tight mb-7">
              {isReset ? "Reset password" : "Sign Up"}
            </h2>
            {isReset && (
              <p className="text-sm text-brand-muted -mt-5 mb-6">
                Enter your phone number and we&apos;ll text you a code to set a new password.
              </p>
            )}

            {/* Registration Form */}
            <form className="space-y-4" data-purpose="signup-form" onSubmit={handleSubmit}>
              {/* Phone Number Input Field */}
              <div data-purpose="form-field-phone">
                <label className="block text-xs font-semibold text-brand-heading mb-1.5" htmlFor="phone">
                  Phone Number
                </label>
                <input
                  className="field-input w-full px-4 py-2.5 rounded-xl text-sm border focus:outline-hidden placeholder:text-slate-400"
                  id="phone"
                  name="phone"
                  onChange={(event) => setPhone(event.target.value)}
                  placeholder="09XXXXXXXX"
                  required
                  type="tel"
                  value={phone}
                />
                <p className="mt-1.5 text-[11px] text-brand-muted">
                  We&apos;ll text you a verification code to confirm your number.
                </p>
              </div>

              {/* Terms & Privacy Agreement Checkbox */}
              <div className="flex items-start pt-1.5 pb-1" data-purpose="agreement-checkbox">
                <input
                  checked={agree}
                  className="h-4 w-4 rounded border-gray-300 text-brand-accent focus:ring-brand-accent/25 mt-0.5"
                  id="agree"
                  name="agree"
                  onChange={(event) => setAgree(event.target.checked)}
                  type="checkbox"
                />
                <label className="ml-2.5 block text-xs text-brand-muted leading-relaxed" htmlFor="agree">
                  I agree to Endod Health&apos;s{" "}
                  <a className="text-brand-accent hover:underline font-medium" href="#">
                    Terms &amp; Conditions
                  </a>{" "}
                  and{" "}
                  <a className="text-brand-accent hover:underline font-medium" href="#">
                    Privacy Policy
                  </a>
                  .
                </label>
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
                  {isSubmitting ? "Sending code..." : "Sign Up"}
                </button>
              </div>

              {/* Sign In Navigation Prompt */}
              <div className="text-center pt-1">
                <p className="text-xs text-brand-muted">
                  Already have an account?{" "}
                  <Link className="text-brand-accent font-semibold hover:underline" href="/login">
                    Sign In
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
                {/* Caduceus medical emblem icon */}
                <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
                  <path d="M12 2v19M8 6c2-1 6-1 8 0M7 11c2.5-1.5 7.5-1.5 10 0M8 16c2-1 6-1 8 0M12 2c-1.5 0-3 1.5-3 3s1.5 3 3 3 3-1.5 3-3-1.5-3-3-3z" />
                </svg>
              </div>
              <p>
                We prioritize data security and patient privacy, exceeding HIPAA compliance standards to provide the highest
                level of protection.
              </p>
            </aside>
          </div>
        </section>
        {/* END: RightColumn */}
      </div>
    </main>
  );
}

