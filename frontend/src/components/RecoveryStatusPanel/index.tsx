import React from "react";
import { Alert, Button, Card, InfoButton, Progress } from "belagio-styles-lib";
import type { SiteLanguage } from "belagio-styles-lib";
import { translate } from "../../i18n/translations";
import type { BackendStatus, ProgressInfo } from "../../types/recovery";
import {
  PanelContent,
  ProgressDetails,
  progressStyle,
  PermissionActions,
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
  const [errorDismissed, setErrorDismissed] = React.useState(false);
  React.useEffect(() => setErrorDismissed(false), [error]);
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

        <Progress
          label={t("progress")}
          value={percent}
          fillColor="#B6F23C"
          formatValue={(value) => hasProgress ? `${value}%` : t("noProgress")}
          style={progressStyle}
        />

        {partitionScanCanResume && selectedDiskNumber && (
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={busy} onClick={onRetryScan}>
            {t("retryScan")}
          </Button>
        )}

        {error && !errorDismissed && <Alert tone="error" title={t("recoveryProblem")} closeLabel={t("closeDetails")} onClose={() => setErrorDismissed(true)} style={progressStyle}>{error}</Alert>}

        {Boolean(selectedDiskNumber) && !isAdministrator && (
          <Alert tone="warning" style={progressStyle} title={t("adminRequired")}>
            <PermissionActions>
              <Button className="brand-button--ghost" variant="ghost" size="md" disabled={busy} onClick={onRequestDiskAccess}>
                {t("requestAccess")}
              </Button>
              <InfoButton description={t("elevatedAccess")} label={t("moreInfo")} />
            </PermissionActions>
          </Alert>
        )}

        {backendStatus === "error" && (
          <Alert tone="info" style={progressStyle}>
            {t("restartApp")}
          </Alert>
        )}
      </PanelContent>
    </Card>
  );
};
