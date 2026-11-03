"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import InterviewApp from "./app";
import MobileHome from "./mobile-home";
import { mobileHref, useIsPhone } from "./mobile-shell";

/**
 * The patient app. On a phone: the tile dashboard, and a deep link to a
 * section (`?section=booking`, from a notification, the visit page, a record)
 * opens that section's mobile screen. Wider screens: the sidebar app.
 */
export default function InterviewPage() {
  const router = useRouter();
  const isPhone = useIsPhone();
  const target = isPhone ? phoneTarget() : null;

  useEffect(() => {
    if (target) router.replace(target);
  }, [router, target]);

  if (isPhone === null || target) {
    return <div aria-busy="true" className="min-h-screen bg-white" />;
  }
  return isPhone ? <MobileHome /> : <InterviewApp />;
}

/** The mobile screen a `?section=` deep link asks for, if any. */
function phoneTarget(): string | null {
  const params = new URLSearchParams(window.location.search);
  return mobileHref(params.get("section"), params.get("highlight"));
}
