import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Endod Health - Video Visit",
  description: "Your video visit with your doctor.",
  robots: { index: false, follow: false },
};

export default function VisitLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
