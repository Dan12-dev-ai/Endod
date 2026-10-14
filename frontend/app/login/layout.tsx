import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Endod Health - Sign In",
  description:
    "Sign in to Endod Health with your phone number — we'll text you a one-time verification code, no password needed.",
};

export default function LoginLayout({ children }: LayoutProps<"/login">) {
  return <>{children}</>;
}