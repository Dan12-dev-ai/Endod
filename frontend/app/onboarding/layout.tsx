import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Endod Health - Onboarding",
  description:
    "Tell us a little about yourself so Endod Health can tailor your care to your needs.",
};

export default function OnboardingLayout({ children }: LayoutProps<"/onboarding">) {
  return <>{children}</>;
}