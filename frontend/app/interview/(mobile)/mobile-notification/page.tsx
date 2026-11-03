"use client";

import { useRouter } from "next/navigation";
import NotificationsView from "../../notifications-view";
import { mobileHref, useMobileToast } from "../../mobile-shell";

export default function MobileNotificationPage() {
  const router = useRouter();
  const onToast = useMobileToast();
  // A notification opens its screen (the desktop section's mobile twin), highlighting its card.
  return <NotificationsView hideTitle onOpen={(nav, target) => router.push(mobileHref(nav, target) ?? "/interview")} onToast={onToast} />;
}
