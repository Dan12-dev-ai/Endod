import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Endod Health - Verify Phone",
  description:
    "Enter the verification code we sent to your phone to complete your Endod Health sign up.",
};

export default function VerifyOtpLayout({ children }: LayoutProps<"/verify-otp">) {
  return <>{children}</>;
}
