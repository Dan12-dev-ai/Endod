import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Endod Health - Set Password",
  description:
    "Create a password for your Endod Health account to sign in quickly with your phone number.",
};

export default function SetPasswordLayout({ children }: LayoutProps<"/set-password">) {
  return <>{children}</>;
}