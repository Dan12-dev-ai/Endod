import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Endod Health - Sign In",
  description:
    "Sign in to Endod Health with your phone number and password.",
};

export default function LoginLayout({ children }: LayoutProps<"/login">) {
  return <>{children}</>;
}