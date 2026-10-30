"use client";

import { useI18n } from "../lib/i18n";
import { Calendar, ClipboardList, Smartphone } from "lucide-react";

const STEPS = [
  {
    icon: Calendar,
    title: "Book a visit",
    body: "Browse facilities and book in a few taps.",
  },
  {
    icon: ClipboardList,
    title: "Track appointments",
    body: "View visits and registered patients.",
  },
  {
    icon: Smartphone,
    title: "Access records",
    body: "View and share records on your phone.",
  },
];

export default function HowItWorks() {
  const { t } = useI18n();
  return (
    <section className="pt-12 sm:pt-16 pb-10 sm:pb-12 bg-white dark:bg-gray-900" data-purpose="how-it-works">
      <div className="max-w-5xl mx-auto px-4 sm:px-6">
        <div className="text-center mb-6 sm:mb-8">
          <h2 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-gray-100">
            How Endod works
          </h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 sm:gap-6">
          {STEPS.map((step, index) => {
            const Icon = step.icon;
            return (
              <div key={step.title} className="flex flex-col items-start gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-slate-400">{index + 1}.</span>
                  <Icon className="w-4 h-4 text-slate-700 dark:text-gray-200" />
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-gray-100">{step.title}</h3>
                </div>
                <p className="text-xs text-slate-500 dark:text-gray-400 leading-relaxed pl-6">
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