"use client";

import { useI18n } from "../lib/i18n";
import { Calendar, ClipboardList, Smartphone } from "lucide-react";

const STEPS = [
  {
    icon: Calendar,
    title: "Book a hospital visit",
    body: "Browse verified facilities by specialty and location, then book an in-person or video visit in a few taps.",
  },
  {
    icon: ClipboardList,
    title: "Track appointments and queue",
    body: "View upcoming and past visits, and see how many patients are registered to receive medication.",
  },
  {
    icon: Smartphone,
    title: "Access records on your phone",
    body: "Your medical records, health card and appointment details stay with you — view and share them anytime.",
  },
];

export default function HowItWorks() {
  const { t } = useI18n();
  return (
    <section className="py-16 sm:py-20 bg-white dark:bg-gray-900" data-purpose="how-it-works">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center mb-10 sm:mb-14">
          <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 dark:text-gray-100 tracking-tight">
            How DEDAN works
          </h2>
          <p className="mt-3 text-sm sm:text-base text-slate-500 dark:text-gray-400 max-w-2xl mx-auto">
            From your first symptom to the hospital door, in three simple steps.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 sm:gap-8">
          {STEPS.map((step, index) => {
            const Icon = step.icon;
            return (
              <div
                key={step.title}
                className="relative bg-slate-50 dark:bg-gray-800 rounded-2xl p-6 sm:p-8 border border-slate-200 dark:border-gray-700"
              >
                <div className="flex items-center gap-3 mb-4">
                  <span className="flex items-center justify-center w-10 h-10 rounded-xl bg-black dark:bg-white text-white dark:text-black font-bold text-sm">
                    {index + 1}
                  </span>
                  <Icon className="w-6 h-6 text-slate-700 dark:text-gray-200" />
                </div>
                <h3 className="text-base sm:text-lg font-bold text-slate-900 dark:text-gray-100 mb-2">
                  {step.title}
                </h3>
                <p className="text-sm text-slate-500 dark:text-gray-400 leading-relaxed">
                  {step.body}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}