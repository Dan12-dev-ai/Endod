"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import HistoryView from "../../history-view";
import { BOOKING_PRESET_KEY, useMobileToast } from "../../mobile-shell";

export default function MobileRecordsPage() {
  const router = useRouter();
  const onToast = useMobileToast();
  const highlight = useSearchParams().get("highlight");
  const [recordId, setRecordId] = useState<string | null>(null);
  return (
    <HistoryView
      hideTitle
      highlightTarget={highlight}
      onBack={() => setRecordId(null)}
      onBook={(preset) => {
        try {
          window.sessionStorage.setItem(BOOKING_PRESET_KEY, JSON.stringify(preset));
        } catch {
          // Storage blocked: booking opens without the preset.
        }
        router.push("/interview/mobile-booking");
      }}
      onOpenSettings={() => router.push("/interview/mobile-setting")}
      onSelectRecord={setRecordId}
      onToast={onToast}
      recordId={recordId ?? undefined}
    />
  );
}
