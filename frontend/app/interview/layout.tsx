import type { Metadata } from "next";
import { Suspense } from "react";

export const metadata: Metadata = {
  title: "Endod Health - Consultation",
  description: "Your Endod Health consultation, appointments, records and settings.",
};

// The page reads the current date while rendering (the booking form's default
// date). With Cache Components that must sit behind a Suspense boundary, or the
// production build fails with a current-time prerender error.
export default function InterviewLayout({ children }: LayoutProps<"/interview">) {
  return <Suspense fallback={null}>{children}</Suspense>;
}
