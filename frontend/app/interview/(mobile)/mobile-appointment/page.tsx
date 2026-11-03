"use client";

import { useRouter, useSearchParams } from "next/navigation";
import AppointmentsView from "../../appointments-view";
import { useMobileToast } from "../../mobile-shell";

export default function MobileAppointmentPage() {
  const router = useRouter();
  const onToast = useMobileToast();
  // A notification opens this screen with the card to highlight.
  const highlight = useSearchParams().get("highlight");
  return <AppointmentsView hideTitle highlightTarget={highlight} onBook={() => router.push("/interview/mobile-booking")} onToast={onToast} />;
}
