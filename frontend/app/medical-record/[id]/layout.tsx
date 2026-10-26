import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Endod Health - Medical record",
  description: "A single health record.",
  robots: { index: false, follow: false },
};

export default function MedicalRecordDetailLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}