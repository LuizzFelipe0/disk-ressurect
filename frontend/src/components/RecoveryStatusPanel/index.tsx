import React from "react";
import { Button, Card } from "belagio-styles-lib";
import type { SiteLanguage } from "belagio-styles-lib";
import { translate } from "../../i18n/translations";
import type { BackendStatus, ProgressInfo } from "../../types/recovery";
import { ErrorNotice } from "../ErrorNotice";
import {
  PanelContent,
  ProgressDetails,
  ProgressTrack,
  StatusMessage,
} from "./style";

export interface RecoveryStatusPanelProps {
  status: string;
  progress: ProgressInfo | null;
  error: string;
  busy: boolean;
  isAdministrator: boolean;
  partitionScanCanResume: boolean;
  selectedDiskNumber: string;
  backendStatus: BackendStatus;
  onRetryScan: () => void;
  onRequestDiskAccess: () => void;
  language?: SiteLanguage;
}

export const getProgressPercent = (progress: ProgressInfo | null) => {
  if (!progress || progress.total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round(progress.completed * 100 / progress.total)));
};

export const RecoveryStatusPanel: React.FC<RecoveryStatusPanelProps> = ({
  status,
  progress,
  error,
  busy,
  isAdministrator,
  partitionScanCanResume,
  selectedDiskNumber,
  backendStatus,
  onRetryScan,
  onRequestDiskAccess,
  language = "en-US",
}) => {
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) => translate(language, key, values);
  const percent = getProgressPercent(progress);
  const hasProgress = Boolean(progress?.total);

  return (
    <Card size="sm" variant="flat" aria-label={t("recoveryStatus")}>
      <PanelContent>
        <StatusMessage role="status" aria-live="polite">
          <span>{status}</span>
          {hasProgress && (
            <ProgressDetails>
              {progress!.completed.toLocaleString(language)}/{progress!.total.toLocaleString(language)} · {percent}%
            </ProgressDetails>
          )}
        </StatusMessage>

        <ProgressTrack
          aria-label={t("progress")}
          aria-valuetext={hasProgress ? t("complete", { percent }) : t("noProgress")}
          max={100}
          value={percent}
        />

        {partitionScanCanResume && selectedDiskNumber && (
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={busy} onClick={onRetryScan}>
            {t("retryScan")}
          </Button>
        )}

        {error && <ErrorNotice spaced title={t("recoveryProblem")}>{error}</ErrorNotice>}

        {!isAdministrator && (
          <ErrorNotice tone="warning" spaced title={t("adminRequired")}>
            {t("elevatedAccess")}
          </ErrorNotice>
        )}

        {!isAdministrator && (
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={busy} onClick={onRequestDiskAccess}>
            {t("requestAccess")}
          </Button>
        )}

        {backendStatus === "error" && (
          <ErrorNotice tone="info" spaced>
            {t("restartApp")}
          </ErrorNotice>
        )}
      </PanelContent>
    </Card>
  );
};
