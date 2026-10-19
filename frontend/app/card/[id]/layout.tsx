import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Endod Health - Card Check",
  description: "Check that an Endod Digital Health Card is genuine.",
  // A card link is personal: keep these pages out of search results.
  robots: { index: false, follow: false },
};

export default function CardLayout({ children }: LayoutProps<"/card/[id]">) {
  return <>{children}</>;
}
