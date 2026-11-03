"use client";

import SettingsView from "../../settings-view";
import { useMobileToast } from "../../mobile-shell";

export default function MobileSettingPage() {
  const onToast = useMobileToast();
  // No header to refresh here: the dashboard reads the profile when it opens.
  return <SettingsView hideTitle onProfileChange={() => undefined} onToast={onToast} />;
}
