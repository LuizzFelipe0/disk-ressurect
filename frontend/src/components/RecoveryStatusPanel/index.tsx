import React from "react";
import { Button, Card } from "belagio-styles-lib";
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
}) => {
  const percent = getProgressPercent(progress);
  const hasProgress = Boolean(progress?.total);

  return (
    <Card size="sm" variant="flat" aria-label="Recovery status">
      <PanelContent>
        <StatusMessage role="status" aria-live="polite">
          <span>{status}</span>
          {hasProgress && (
            <ProgressDetails>
              {progress!.completed.toLocaleString()}/{progress!.total.toLocaleString()} · {percent}%
            </ProgressDetails>
          )}
        </StatusMessage>

        <ProgressTrack
          aria-label="Recovery progress"
          aria-valuetext={hasProgress ? `${percent}% complete` : "No active progress"}
          max={100}
          value={percent}
        />

        {partitionScanCanResume && selectedDiskNumber && (
          <Button variant="ghost" size="md" disabled={busy} onClick={onRetryScan}>
            Retry scan
          </Button>
        )}

        {error && <ErrorNotice spaced title="Recovery problem">{error}</ErrorNotice>}

        {!isAdministrator && (
          <ErrorNotice tone="warning" spaced title="Administrator permission required">
            Physical disk access requires elevated permission. The source will be opened in read-only mode.
          </ErrorNotice>
        )}

        {!isAdministrator && (
          <Button variant="ghost" size="md" disabled={busy} onClick={onRequestDiskAccess}>
            Request disk access permission
          </Button>
        )}

        {backendStatus === "error" && (
          <ErrorNotice tone="info" spaced>
            Close and reopen the application to start another Python process.
          </ErrorNotice>
        )}
      </PanelContent>
    </Card>
  );
};
