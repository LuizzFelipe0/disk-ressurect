import React from "react";
import { Button, Card, EmptyState, FormField, Select } from "belagio-styles-lib";
import type { RecoveryStepProps } from "./types";
import {
  ActionRow, DeviceDetails, DeviceIcon, DeviceOption, FormControl, FormControlCaption,
  FormGrid, PageIntro, Eyebrow, SourceList, SourceSelectedTag, StepActions,
} from "../style";
import { sanitizeDisplayText } from "../../../utils/sanitizeDisplayText";

interface StorageStepProps extends RecoveryStepProps {
  onContinue: () => void;
}

export const StorageStep: React.FC<StorageStepProps> = ({ recovery, t, onContinue }) => {
  const selectedDiskHasCachedScan = recovery.disks.some((disk) =>
    String(disk.number) === recovery.selectedDiskNumber && Boolean(disk.cachedPartitions?.length));

  return <>
    <PageIntro><Eyebrow>{t("storageStep")}</Eyebrow><h1>{t("selectSourceHeading")}</h1>
      <p>{t("selectSourceDescription")}</p></PageIntro>
    <Card size="sm" variant="flat"><FormGrid>
      <FormControl>
        <FormControlCaption>{t("sourceDisk")}</FormControlCaption>
        {recovery.disks.length ? <SourceList>
          {recovery.disks.map((disk) => {
            const selected = String(disk.number) === recovery.selectedDiskNumber;
            return <DeviceOption key={`${disk.number}:${disk.displayName}`} type="button" $selected={selected}
              disabled={recovery.busy} aria-pressed={selected} onClick={() => recovery.selectDisk(String(disk.number))}>
              <DeviceIcon aria-hidden="true">▣</DeviceIcon>
              <DeviceDetails><strong>{sanitizeDisplayText(disk.displayName)}</strong>
                <small>{disk.model ? sanitizeDisplayText(disk.model) : t("physicalDisk")} · {(disk.sizeBytes / (1024 ** 3)).toFixed(1)} GB</small></DeviceDetails>
              {selected && <SourceSelectedTag>{t("selectedLabel")}</SourceSelectedTag>}
            </DeviceOption>;
          })}
        </SourceList> : <EmptyState title={recovery.backendStatus === "error" ? t("backendUnavailable") : t("noDisksFound")} />}
      </FormControl>
      <ActionRow>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy}
          onClick={() => void recovery.refreshDisks()}>{t("refresh")}</Button>
        <Button className="brand-button--ghost" variant="ghost" size="md"
          disabled={recovery.busy || !recovery.selectedDiskNumber}
          onClick={() => void recovery.findPartitions(false)}>{t("findPartitions")}</Button>
        <Button className="brand-button--ghost" variant="ghost" size="md"
          disabled={recovery.busy || !recovery.selectedDiskNumber}
          onClick={() => void recovery.findPartitions(true)}>
          {selectedDiskHasCachedScan ? t("deepScanAgain") : t("deepScan")}
        </Button>
      </ActionRow>
      <FormField label={t("partitionLabel")}><Select aria-label={t("partitionLabel")} value={recovery.selectedVolumeId}
        disabled={recovery.busy || !recovery.volumes.length} onChange={recovery.selectVolume} options={[
          { value: "", label: recovery.volumes.length ? t("selectPartition") : t("searchPartitions") },
          ...recovery.volumes.map((volume) => ({ value: volume.id, label: sanitizeDisplayText(volume.name) })),
        ]} /></FormField>
    </FormGrid></Card>
    <StepActions>
      <span />
      <Button className="brand-button--primary" variant="primary" size="md"
        disabled={recovery.busy || !recovery.selectedVolumeId} onClick={onContinue}>{t("continue")} →</Button>
    </StepActions>
  </>;
};
