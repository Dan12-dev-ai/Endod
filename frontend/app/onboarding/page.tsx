"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, safeNext } from "@/app/lib/api";
import { useI18n, type TranslationKey } from "@/app/lib/i18n";

const LOOKING_FOR_OPTIONS: { id: string; labelKey: TranslationKey; hintKey: TranslationKey }[] = [
  { id: "symptoms", labelKey: "onboarding.option.symptoms.label", hintKey: "onboarding.option.symptoms.hint" },
  { id: "hospitals", labelKey: "onboarding.option.hospitals.label", hintKey: "onboarding.option.hospitals.hint" },
  { id: "appointments", labelKey: "onboarding.option.appointments.label", hintKey: "onboarding.option.appointments.hint" },
  { id: "treatment", labelKey: "onboarding.option.treatment.label", hintKey: "onboarding.option.treatment.hint" },
  { id: "history", labelKey: "onboarding.option.history.label", hintKey: "onboarding.option.history.hint" },
];

// The id is also the value the backend stores.
const SEX_OPTIONS: { id: string; labelKey: TranslationKey }[] = [
  { id: "male", labelKey: "onboarding.sex.male" },
  { id: "female", labelKey: "onboarding.sex.female" },
  { id: "other", labelKey: "onboarding.sex.other" },
  { id: "prefer_not_to_say", labelKey: "onboarding.sex.preferNotToSay" },
];

const STEP_TITLE_KEYS: TranslationKey[] = [
  "onboarding.title.name",
  "onboarding.title.lookingFor",
  "onboarding.title.sex",
  "onboarding.title.age",
];

// Age is collected in clinical-style ranges (as common in medical software)
// rather than exact years. The range labels are numerals: language-neutral.
const AGE_RANGES = [
  { value: 1, label: "1–20" },
  { value: 21, label: "21–40" },
  { value: 41, label: "41–60" },
  { value: 61, label: "61–80" },
  { value: 81, label: "81–100" },
];

export default function OnboardingPage() {
  const router = useRouter();
  const { t } = useI18n();

  const [step, setStep] = useState(0);
  const [formError, setFormError] = useState("");

  // Step 1: name
  const [firstName, setFirstName] = useState("");
  const [middleName, setMiddleName] = useState("");
  const [lastName, setLastName] = useState("");

  // Step 2: looking for (multi-select)
  const [lookingFor, setLookingFor] = useState<string[]>([]);

  // Step 3: sex
  const [sex, setSex] = useState("");

  // Step 4: age (clinical-style ranges)
  const [ageRange, setAgeRange] = useState<string>('');
  // Explicit, opt-in consent to store health details (sex and age).
  const [healthConsent, setHealthConsent] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const savingRef = useRef(false);

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
        goNextRef.current();
      }, 650);
    }
  };

  const validateStep = (): boolean => {
    if (step === 0 && (!firstName.trim() || !lastName.trim())) {
      setFormError(t("onboarding.error.name"));
      return false;
    }
    if (step === 1 && lookingFor.length === 0) {
      setFormError(t("onboarding.error.lookingFor"));
      return false;
    }
    if (step === 2 && !sex) {
      setFormError(t("onboarding.error.sex"));
      return false;
     }
     if (step === 3 && !ageRange) {
       setFormError(t("onboarding.error.age"));
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
    setStep((current) => Math.min(current + 1, STEP_TITLE_KEYS.length - 1));
  };

  // Timers fire after later renders, so they call the newest goNext (which
  // sees the answer just given), not the one from the render that set them.
  const goNextRef = useRef(goNext);
  useEffect(() => {
    goNextRef.current = goNext;
  });

  // Advance after a short beat so the selection is visibly applied first.
  const autoAdvance = (delay = 550) => {
    clearAdvanceTimer();
    clearFinishTimer();
    advanceTimer.current = setTimeout(() => {
      advanceTimer.current = null;
      goNextRef.current();
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
  const formRef = useRef({ firstName, middleName, lastName, lookingFor, sex, age: ageRange, healthConsent });
  useEffect(() => {
    formRef.current = { firstName, middleName, lastName, lookingFor, sex, age: ageRange, healthConsent };
  }, [firstName, middleName, lastName, lookingFor, sex, ageRange, healthConsent]);

  const handleFinish = async () => {
    const current = formRef.current;
    if (!current.sex || !current.age) return; // final step not complete yet
    if (savingRef.current) return;
    clearAdvanceTimer();
    clearFinishTimer();
    savingRef.current = true;
    setIsSaving(true);
    setFormError("");
    try {
      if (current.lookingFor.length) {
        await api("users/me/preferences", { method: "PATCH", body: { onboarding_goals: current.lookingFor } });
      }
      // Sex and age are health information: stored only with consent.
      if (current.healthConsent) {
        await api("users/me/consent", { method: "PATCH", body: { treatment_processing: true } });
        await api("users/me/health-profile", {
          method: "PATCH",
          body: { sex: current.sex, age_range: current.age },
        });
      }
      // The name goes last: a saved name is what marks onboarding finished
      // (see proxy.ts), so if an earlier save fails the patient comes back
      // here rather than being let in with half their answers lost.
      await api("users/me", {
        method: "PATCH",
        body: {
          first_name: current.firstName.trim(),
          middle_name: current.middleName.trim() || null,
          last_name: current.lastName.trim(),
        },
      });
      // Done: to the dashboard, or the page they were heading for. The
      // health card is in the account menu and under Settings.
      router.push(safeNext(new URLSearchParams(window.location.search).get("next"), "/interview"));
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : t("onboarding.error.save"));
    } finally {
      savingRef.current = false;
      setIsSaving(false);
    }
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
      setStep((current) => Math.min(current + 1, STEP_TITLE_KEYS.length - 1));
    }, delay);
  };

  const progress = ((step + 1) / STEP_TITLE_KEYS.length) * 100;

  return (
    <main
      className="w-full min-h-screen flex items-center justify-center py-8 px-4 sm:px-8 bg-[#DDE9E6] text-brand-primary font-sans antialiased"
      data-purpose="page-wrapper"
    >
      <div className="w-full max-w-[560px]">
        <div className="bg-white rounded-[32px] shadow-xl shadow-teal-950/5 border border-slate-100 p-8 sm:p-10">
          {/* Brand + Progress */}
          <div className="mb-7" data-purpose="brand-logo">
            <h1 className="text-2xl font-extrabold tracking-tight text-brand-heading mb-5">{t("common.endod")}</h1>
            <div className="flex items-center justify-between mb-2 text-xs text-brand-muted">
              <span>
                {t("onboarding.stepOf", { current: step + 1, total: STEP_TITLE_KEYS.length })}
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
                  {t(STEP_TITLE_KEYS[0])}
                </h2>
                <div>
                  <label className="block text-xs font-semibold text-brand-heading mb-1.5" htmlFor="first-name">
                    {t("onboarding.firstName")}
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
                    {t("onboarding.middleName")}
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
                    {t("onboarding.lastName")}
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
                  {t(STEP_TITLE_KEYS[1])}
                </h2>
                <p className="text-xs text-brand-muted mb-5">{t("onboarding.selectAll")}</p>

                <div className="space-y-1" role="group" aria-label={t("onboarding.lookingForAria")}>
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
                            {t(option.labelKey)}
                          </span>
                          <span className="block text-[11px] font-normal text-brand-muted mt-0.5 leading-snug">
                            {t(option.hintKey)}
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
                  {t(STEP_TITLE_KEYS[2])}
                </h2>
                <div className="grid grid-cols-2 gap-2.5">
                  {SEX_OPTIONS.map((option) => {
                    const selected = sex === option.id;
                    return (
                      <button
                        aria-pressed={selected}
                        className={`px-4 py-3.5 rounded-xl border text-sm font-medium transition-all cursor-pointer ${
                          selected
                            ? "border-[#1E5852] bg-[#F2F8F7] text-brand-heading font-semibold"
                            : "border-[#E2E8F0] bg-[#F8FAFB] text-brand-muted hover:border-[#1E5852]/40 hover:text-brand-heading"
                        }`}
                        key={option.id}
                        onClick={() => {
                          setSex(option.id);
                          setFormError("");
                          autoAdvance();
                        }}
                        type="button"
                      >
                        {t(option.labelKey)}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Slide 4: Age (radio-based selection over clinical-style ranges) */}
              <div className="w-full flex-shrink-0" data-purpose="step-age">
                <h2 className="font-serif text-3xl sm:text-[36px] font-medium text-brand-heading tracking-tight mb-4">
                  {t(STEP_TITLE_KEYS[3])}
                </h2>
                <label className="flex items-start gap-2.5 mb-4 text-xs text-brand-muted leading-relaxed cursor-pointer" data-purpose="health-consent">
                  <input
                    checked={healthConsent}
                    className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-[#1E5852]"
                    onChange={(e) => setHealthConsent(e.target.checked)}
                    type="checkbox"
                  />
                  <span>{t("onboarding.consent")}</span>
                </label>
                <div className="flex flex-col gap-2" role="radiogroup" aria-label={t("onboarding.ageAria")}>
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
                            // No auto-finish here: the consent choice above
                            // must be made before anything is saved.
                            setAgeRange(e.target.value);
                            setFormError("");
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

          {isSaving && (
            <p className="mt-4 text-xs text-brand-muted" role="status">{t("onboarding.savingAnswers")}</p>
          )}

          {/* Form Error Message */}
          {formError && (
            <p
              className="mt-4 text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2"
              role="alert"
            >
              {formError}
            </p>
          )}

          {/* Navigation: steps advance automatically; the last one has an explicit Finish */}
          <div className="mt-7 flex items-center justify-between" data-purpose="step-navigation">
            <button
              className={`px-5 py-3 rounded-full text-sm font-medium text-brand-muted hover:text-brand-heading transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer ${step === 0 ? "invisible" : ""}`}
              disabled={step === 0}
              onClick={goBack}
              type="button"
            >
              {t("common.back")}
            </button>
            {step === STEP_TITLE_KEYS.length - 1 && (
              <button
                className="px-6 py-3 rounded-full text-sm font-semibold bg-[#1E5852] text-white hover:bg-[#174640] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                data-purpose="finish-onboarding"
                disabled={!ageRange || isSaving}
                onClick={() => void handleFinish()}
                type="button"
              >
                {isSaving ? t("onboarding.submitting") : t("onboarding.submit")}
              </button>
            )}
          </div>
        </div>

        <p className="text-center text-[11px] text-brand-muted mt-4">
          {t("onboarding.footer")}
        </p>
       </div>
      </main>
    );
  }
