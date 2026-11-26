import type { translate } from "../../../i18n/translations";
import type { useRecoveryController } from "../../../hooks/useRecoveryController";
import type { SiteLanguage } from "belagio-styles-lib";

export type RecoveryTranslate = (
  key: Parameters<typeof translate>[1],
  values?: Record<string, string | number>,
) => string;

export interface RecoveryStepProps {
  recovery: ReturnType<typeof useRecoveryController>;
  language: SiteLanguage;
  t: RecoveryTranslate;
}
