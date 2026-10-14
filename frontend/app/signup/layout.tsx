import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Endod Health - Sign Up",
  description:
    "Create your Endod Health account and join the clinicians delivering truly tailored, data-driven patient care.",
};

export default function SignUpLayout({ children }: LayoutProps<"/signup">) {
  return <>{children}</>;
}
