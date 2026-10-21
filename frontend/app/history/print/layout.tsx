import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Endod Health - My health records",
  description: "A printable copy of your health records.",
  robots: { index: false, follow: false },
};

export default function PrintLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
