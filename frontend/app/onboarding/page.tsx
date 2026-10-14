"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

const LOOKING_FOR_OPTIONS = [
  { id: "symptoms", label: "Understand my symptoms", hint: "Talk to Endod AI about how you're feeling" },
  { id: "hospitals", label: "Find the right hospital", hint: "Nearby hospitals with live crowd levels" },
  { id: "appointments", label: "Book an appointment", hint: "Reserve a slot with SMS reminders" },
  { id: "treatment", label: "Follow my treatment plan", hint: "Timelines, doses and remaining counts" },
  { id: "history", label: "Access my medical history", hint: "One record across all hospitals" },
];

const SEX_OPTIONS = ["Male", "Female", "Other", "Prefer not to say"];

const STEP_TITLES = [
  "What's your name?",
  "What are you looking for?",
  "What's your sex?",
  "What's your age?",
];

// Age is collected in clinical-style ranges (as common in medical software)
// rather than exact years.
const AGE_RANGES = [
  { value: 1, label: "1–20" },
  { value: 21, label: "21–40" },
  { value: 41, label: "41–60" },
  { value: 61, label: "61–80" },
  { value: 81, label: "81–100" },
];

export default function OnboardingPage() {
  const router = useRouter();

  const [step, setStep] = useState(0);
  const [formError, setFormError] = useState("");

  // Step 1: name (updated) - second update - FINAL - EXTRA
// INSERTED LINE FOR TESTING
  const [firstName, setFirstName] = useState("");
  const [middleName, setMiddleName] = useState("");
  const [lastName, setLastName] = useState("");

  // Step 2: looking for (multi-select)
  const [lookingFor, setLookingFor] = useState<string[]>([]);

  // Step 3: sex
  const [sex, setSex] = useState("");
// AGE SLIDER REPLACED WITH RADIO BUTTONS - VERIFIED

  // Step 4: age (clinical-style ranges) - UPDATED
  const [ageRange, setAgeRange] = useState<string>('');

  const toggleLookingFor = (id: string) => {
    setFormError("");
    const next = lookingFor.includes(id)
      ? lookingFor.filter((item) => item !== id)
      : [...lookingFor, id];
    setLookingFor(next);
    // Once at least one option is picked, move on after a short beat.
    clearAdvanceTimer();
    clearFinishTimer();
    if (next.length > 0) {
      advanceTimer.current = setTimeout(() => {
        advanceTimer.current = null;
        goNext();
      }, 650);
    }
  };

  const validateStep = (): boolean => {
    if (step === 0 && (!firstName.trim() || !lastName.trim())) {
      setFormError("Please enter your first and last name.");
      return false;
    }
    if (step === 1 && lookingFor.length === 0) {
      setFormError("Please select at least one option.");
      return false;
    }
    if (step === 2 && !sex) {
      setFormError("Please select an option.");
      return false;
     }
     if (step === 3 && !ageRange) {
       setFormError("Please select an age range.");
       return false;
     }
    return true;
  };

  // ===== Auto-advance: each completed step moves to the next one by itself =====
  // A short delay lets the user see their selection register before the slide
  // transitions. Timers are tracked so rapid changes don't stack up.
  const advanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const finishTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearAdvanceTimer = () => {
    if (advanceTimer.current) {
      clearTimeout(advanceTimer.current);
      advanceTimer.current = null;
    }
  };
  const clearFinishTimer = () => {
    if (finishTimer.current) {
      clearTimeout(finishTimer.current);
      finishTimer.current = null;
    }
  };

  useEffect(
    () => () => {
      clearAdvanceTimer();
      clearFinishTimer();
    },
    [],
  );

  const goNext = () => {
    if (!validateStep()) return;
    setFormError("");
    setStep((current) => Math.min(current + 1, STEP_TITLES.length - 1));
  };

  // Advance after a short beat so the selection is visibly applied first.
  const autoAdvance = (delay = 550) => {
    clearAdvanceTimer();
    clearFinishTimer();
    advanceTimer.current = setTimeout(() => {
      advanceTimer.current = null;
      goNext();
    }, delay);
  };

  const goBack = () => {
    clearAdvanceTimer();
    clearFinishTimer();
    setFormError("");
    setStep((current) => Math.max(current - 1, 0));
  };

  // Keep the newest form values in a ref so timer callbacks (which capture an
  // older render's closure) always save the latest answers, not stale ones.
  const formRef = useRef({ firstName, middleName, lastName, lookingFor, sex, age: ageRange });
  useEffect(() => {
    formRef.current = { firstName, middleName, lastName, lookingFor, sex, age: ageRange };
  }, [firstName, middleName, lastName, lookingFor, sex, ageRange]);

  const handleFinish = () => {
    const current = formRef.current;
    if (!current.sex || !current.age) return; // final step not complete yet
    clearAdvanceTimer();
    clearFinishTimer();
    try {
      localStorage.setItem(
        "dedan_onboarding",
        JSON.stringify({
          firstName: current.firstName.trim(),
          middleName: current.middleName.trim(),
          lastName: current.lastName.trim(),
          lookingFor: current.lookingFor,
          sex: current.sex,
          age: current.age,
          completedAt: new Date().toISOString(),
        }),
      );
    } catch {
      // Storage unavailable (private mode etc.) — continue anyway.
    }
    router.push("/health-card");
  };

  // On the final step, a completed selection auto-saves and moves on.
  const autoFinish = (delay = 550) => {
    clearAdvanceTimer();
    clearFinishTimer();
    finishTimer.current = setTimeout(() => {
      finishTimer.current = null;
      handleFinish();
    }, delay);
  };

  // Name step: advance once both required fields have content (on blur/Enter).
  const autoAdvanceName = (delay = 350) => {
    if (step !== 0) return;
    if (!firstName.trim() || !lastName.trim()) return; // wait — don't nag on blur
    setFormError("");
    clearAdvanceTimer();
    clearFinishTimer();
    advanceTimer.current = setTimeout(() => {
      advanceTimer.current = null;
      setStep((current) => Math.min(current + 1, STEP_TITLES.length - 1));
    }, delay);
  };


















































   

  const progress = ((step + 1) / STEP_TITLES.length) * 100;

  return (
    <main
      className="w-full min-h-screen flex items-center justify-center py-8 px-4 sm:px-8 bg-[#DDE9E6] text-brand-primary font-sans antialiased"
      data-purpose="page-wrapper"
    >
      <div className="w-full max-w-[560px]">
        <div className="bg-white rounded-[32px] shadow-xl shadow-teal-950/5 border border-slate-100 p-8 sm:p-10">
          {/* Brand + Progress */}
          <div className="mb-7" data-purpose="brand-logo">
            <h1 className="text-2xl font-extrabold tracking-tight text-brand-heading mb-5">Endod</h1>
            <div className="flex items-center justify-between mb-2 text-xs text-brand-muted">
              <span>
                Step {step + 1} of {STEP_TITLES.length}
              </span>
              <span>{Math.round(progress)}%</span>
            </div>
            <div className="h-1.5 w-full bg-[#F2F5F5] rounded-full overflow-hidden">
              <div
                className="h-full bg-[#1E5852] rounded-full transition-all duration-500 ease-out accent-[#1E5852] cursor-pointer"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>

          {/* Sliding steps: one question per slide */}
          <div className="overflow-hidden">
            <div
              className="flex transition-transform duration-500 ease-in-out"
              style={{ transform: `translateX(-${step * 100}%)` }}
            >
              {/* Slide 1: Name */}
              <div className="w-full flex-shrink-0 space-y-4" data-purpose="step-name">
                <h2 className="font-serif text-3xl sm:text-[36px] font-medium text-brand-heading tracking-tight mb-1">
                  {STEP_TITLES[0]}
                </h2>
                <div>
                  <label className="block text-xs font-semibold text-brand-heading mb-1.5" htmlFor="first-name">
                    First name
                  </label>
                  <input
                    className="field-input w-full px-4 py-2.5 rounded-xl text-sm border focus:outline-hidden placeholder:text-slate-400"
                    id="first-name"
                    onChange={(event) => {
                      setFirstName(event.target.value);
                      setFormError("");
                    }}
                    onBlur={() => autoAdvanceName()}
                    placeholder="Abebe"
                    value={firstName}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-brand-heading mb-1.5" htmlFor="middle-name">
                    Middle name
                  </label>
                  <input
                    className="field-input w-full px-4 py-2.5 rounded-xl text-sm border focus:outline-hidden placeholder:text-slate-400"
                    id="middle-name"
                    onChange={(event) => setMiddleName(event.target.value)}
                    placeholder="Tesfaye"
                    value={middleName}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-brand-heading mb-1.5" htmlFor="last-name">
                    Last name
                  </label>
                  <input
                    className="field-input w-full px-4 py-2.5 rounded-xl text-sm border focus:outline-hidden placeholder:text-slate-400"
                    id="last-name"
                    onChange={(event) => {
                      setLastName(event.target.value);
                      setFormError("");
                    }}
                    onBlur={() => autoAdvanceName()}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        autoAdvanceName();
                      }
                    }}
                    placeholder="Alemu"
                    value={lastName}
                  />
                </div>
              </div>
              {/* Slide 2: Looking for (multi-select options) */}
              <div className="w-full flex-shrink-0" data-purpose="step-looking-for">
                <h2 className="font-serif text-3xl sm:text-[36px] font-medium text-[#1E5852] tracking-tight mb-1">
                  {STEP_TITLES[1]}
                </h2>
                <p className="text-xs text-brand-muted mb-5">Select all that apply.</p>

                <div className="space-y-1" role="group" aria-label="What are you looking for">
                  {LOOKING_FOR_OPTIONS.map((option) => {
                    const selected = lookingFor.includes(option.id);
                    return (
                      <button
                        aria-checked={selected}
                        className="w-full flex items-start gap-3.5 px-3 py-3.5 rounded-xl text-left transition-colors cursor-pointer"
                        key={option.id}
                        onClick={() => toggleLookingFor(option.id)}
                        role="checkbox"
                        type="button"
                      >
                        {/* Selection circle — left (sole selection indicator) */}
                        <span
                          className={`shrink-0 mt-0.5 w-5 h-5 rounded-full border-2 flex items-center justify-center transition-colors ${
                            selected
                              ? "border-[#1E5852] bg-[#1E5852]"
                              : "border-[#B6C4C3] bg-white"
                          }`}
                        >
                          {selected && (
                            <svg
                              className="w-3 h-3 text-white"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="3"
                              viewBox="0 0 24 24"
                            >
                              <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          )}
                        </span>

                        {/* Label + hint */}
                        <span className="min-w-0">
                          <span className="block text-sm font-medium leading-snug text-brand-heading">
                            {option.label}
                          </span>
                          <span className="block text-[11px] font-normal text-brand-muted mt-0.5 leading-snug">
                            {option.hint}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
              {/* Slide 3: Sex */}
              <div className="w-full flex-shrink-0" data-purpose="step-sex">
                <h2 className="font-serif text-3xl sm:text-[36px] font-medium text-brand-heading tracking-tight mb-4">
                  {STEP_TITLES[2]}
                </h2>
                <div className="grid grid-cols-2 gap-2.5">
                  {SEX_OPTIONS.map((option) => {
                    const selected = sex === option;
                    return (
                      <button
                        aria-pressed={selected}
                        className={`px-4 py-3.5 rounded-xl border text-sm font-medium transition-all cursor-pointer ${
                          selected
                            ? "border-[#1E5852] bg-[#F2F8F7] text-brand-heading font-semibold"
                            : "border-[#E2E8F0] bg-[#F8FAFB] text-brand-muted hover:border-[#1E5852]/40 hover:text-brand-heading"
                        }`}
                        key={option}
                        onClick={() => {
                          setSex(option);
                          setFormError("");
                          autoAdvance();
                        }}
                        type="button"
                      >
                        {option}
                      </button>
                    );
                  })}
                </div>
              </div>

                            {/* Slide 4: Age (radio-based selection over clinical-style ranges) */}
              <div className="w-full flex-shrink-0" data-purpose="step-age">
                <h2 className="font-serif text-3xl sm:text-[36px] font-medium text-brand-heading tracking-tight mb-4">
                  {STEP_TITLES[3]}
                </h2>
                <div className="flex flex-col gap-2" role="radiogroup" aria-label="Age range">
                  {AGE_RANGES.map((range) => {
                    const selected = ageRange === range.label;
                    return (
                      <label
                        key={range.value}
                        className={`flex items-center justify-center py-3 px-4 rounded-lg text-sm font-medium cursor-pointer transition-all border ${
                          selected
                            ? "border-[#1E5852] bg-[#F2F8F7] text-brand-heading font-semibold"
                            : "border-[#E2E8F0] bg-[#F8FAFB] text-brand-muted hover:border-[#1E5852]/40 hover:text-brand-heading"
                        }`}
                        data-purpose={`age-range-${range.value}`}
                      >
                        <input
                          type="radio"
                          name="ageRange"
                          value={range.label}
                          checked={selected}
                          onChange={(e) => {
                            setAgeRange(e.target.value);
                            setFormError("");
                            autoFinish();
                          }}
                          className="sr-only"
                          aria-label={range.label}
                        />
                        <span>{range.label}</span>
                      </label>
                    );
                  })}
                </div>
              </div>

            </div>
          </div>

          {/* Form Error Message */}
          {formError && (
            <p
              className="mt-4 text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2"
              role="alert"
            >
              {formError}
            </p>
          )}

          {/* Navigation: Back only — steps advance automatically once completed */}
          <div className="mt-7 flex items-center" data-purpose="step-navigation">
            <button
              className={`px-5 py-3 rounded-full text-sm font-medium text-brand-muted hover:text-brand-heading transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer ${step === 0 ? "invisible" : ""}`}
              disabled={step === 0}
              onClick={goBack}
              type="button"
            >
              Back
            </button>
          </div>
        </div>

        <p className="text-center text-[11px] text-brand-muted mt-4">
          Your answers stay private and are only used to tailor your care.
        </p>
       </div>
      </main>
    );
  }