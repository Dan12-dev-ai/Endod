"use client";

import HealthCardScreen from "../../../health-card/health-card-screen";
import { useI18n } from "../../../lib/i18n";

export default function MobileCardPage() {
  const { t } = useI18n();
  return (
    <>
      <h1 className="sr-only">{t("mobile.title.card")}</h1>
      <HealthCardScreen embedded />
    </>
  );
}
