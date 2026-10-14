"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function SetPasswordPage() {
  // `useSearchParams()` needs a Suspense boundary for prerendering.
  return (
    <Suspense
      fallback={
        <main className="w-full min-h-screen flex items-center justify-center bg-[#DDE9E6] text-brand-primary font-sans antialiased">
          <p className="text-sm text-brand-muted">Loading…</p>
        </main>
      }
    >
      <SetPassword />
    </Suspense>
  );
}

function SetPassword() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const phone = searchParams.get("phone") ?? "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [formError, setFormError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError("");

    if (!phone) {
      setFormError("Missing phone number. Please go back and try again.");
      return;
    }
    if (password.length < 8) {
      setFormError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setFormError("Passwords don't match.");
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await fetch("/api/auth/set-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, password }),
      });
      const data = await response.json();

      if (!response.ok || !data.ok) {
        setFormError(data.error ?? "Something went wrong. Please try again.");
        return;
      }

      try {
        localStorage.setItem(
          "dedan_session",
          JSON.stringify({ phone, createdAt: new Date().toISOString() }),
        );
      } catch {
        // Storage unavailable (private mode etc.) — continue anyway.
      }

      router.push("/onboarding");
    } catch {
      setFormError("Unable to save your password right now. Please check your connection and try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const passwordFieldClass =
    "field-input w-full px-4 py-2.5 pr-10 rounded-xl text-sm border focus:outline-hidden text-slate-800 tracking-wider";

  const eyeButtonClass =
    "absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-400 hover:text-brand-heading focus:outline-hidden";

  return (
    <main
      className="w-full min-h-screen flex items-center justify-center py-8 px-4 sm:px-8 bg-[#DDE9E6] text-brand-primary font-sans antialiased"
      data-purpose="page-wrapper"
    >
      <div className="w-full max-w-[560px]">
        <div className="bg-white rounded-[32px] shadow-xl shadow-teal-950/5 border border-slate-100 p-8 sm:p-10">
          {/* Brand */}
          <div className="mb-6" data-purpose="brand-logo">
            <h1 className="text-2xl font-extrabold tracking-tight text-brand-heading">Endod</h1>
          </div>

          <h2 className="font-serif text-3xl sm:text-[36px] font-medium text-brand-heading tracking-tight mb-1">
            Set your password
          </h2>
          <p className="text-sm text-brand-muted mb-6">
            Create a password for{" "}
            <span className="font-semibold text-brand-heading">{phone || "your account"}</span>. You&apos;ll use it
            with your phone number to sign in.
          </p>

          <form className="space-y-4" data-purpose="set-password-form" onSubmit={handleSubmit}>
            {/* Password Field */}
            <div data-purpose="form-field-password">
              <label className="block text-xs font-semibold text-brand-heading mb-1.5" htmlFor="password">
                Password
              </label>
              <div className="relative">
                <input
                  autoComplete="new-password"
                  className={passwordFieldClass}
                  id="password"
                  onChange={(event) => {
                    setPassword(event.target.value);
                    setFormError("");
                  }}
                  required
                  type={showPassword ? "text" : "password"}
                  value={password}
                />
                <button
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className={eyeButtonClass}
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
              <p className="mt-1.5 text-[11px] text-brand-muted">Must be at least 8 characters.</p>
            </div>
            {/* Confirm Password Field */}
            <div data-purpose="form-field-confirm-password">
              <label className="block text-xs font-semibold text-brand-heading mb-1.5" htmlFor="confirm-password">
                Confirm Password
              </label>
              <div className="relative">
                <input
                  autoComplete="new-password"
                  className={passwordFieldClass}
                  id="confirm-password"
                  onChange={(event) => {
                    setConfirmPassword(event.target.value);
                    setFormError("");
                  }}
                  required
                  type={showConfirmPassword ? "text" : "password"}
                  value={confirmPassword}
                />
                <button
                  aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                  className={eyeButtonClass}
                  onClick={() => setShowConfirmPassword((visible) => !visible)}
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
                {isSubmitting ? "Saving..." : "Continue"}
              </button>
            </div>

          </form>

          <p className="text-center text-[11px] text-brand-muted mt-5">
            Your password is encrypted and never shared — it only secures your account.
          </p>
        </div>
      </div>
    </main>
  );
}
