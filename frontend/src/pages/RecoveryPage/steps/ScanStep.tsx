import React from "react";
import { Button, Card, FormField, InfoButton, Select } from "belagio-styles-lib";
import type { CarvingOptions } from "../../../types/recovery";
import { sanitizeDisplayText } from "../../../utils/sanitizeDisplayText";
import type { RecoveryStepProps } from "./types";
import {
  CarvingBudgetControls, Eyebrow, OrphanScanControls, PageIntro, ScanOption, StepActions,
} from "../style";

interface ScanStepProps extends RecoveryStepProps {
  includeOrphaned: boolean;
  setIncludeOrphaned: (value: boolean) => void;
  forceFreshValidation: boolean;
  setForceFreshValidation: (value: boolean) => void;
  scanBudgetGiB: CarvingOptions["scanBudgetGiB"];
  setScanBudgetGiB: (value: CarvingOptions["scanBudgetGiB"]) => void;
  maxCarvedFiles: CarvingOptions["maxFiles"];
  setMaxCarvedFiles: (value: CarvingOptions["maxFiles"]) => void;
  maxCarvedRetainedMiB: CarvingOptions["maxRetainedMiB"];
  setMaxCarvedRetainedMiB: (value: CarvingOptions["maxRetainedMiB"]) => void;
  maxCandidateReadMiBPerFormat: CarvingOptions["maxCandidateReadMiBPerFormat"];
  setMaxCandidateReadMiBPerFormat: (value: CarvingOptions["maxCandidateReadMiBPerFormat"]) => void;
  enablePngFragmentReconstruction: boolean;
  setEnablePngFragmentReconstruction: (value: boolean) => void;
  onBack: () => void;
  onStart: () => void;
}

export const ScanStep: React.FC<ScanStepProps> = ({
  recovery, t, includeOrphaned, setIncludeOrphaned, forceFreshValidation, setForceFreshValidation,
  scanBudgetGiB, setScanBudgetGiB, maxCarvedFiles, setMaxCarvedFiles,
  maxCarvedRetainedMiB, setMaxCarvedRetainedMiB,
  maxCandidateReadMiBPerFormat, setMaxCandidateReadMiBPerFormat, onBack, onStart,
  enablePngFragmentReconstruction, setEnablePngFragmentReconstruction,
}) => {
  const sourceName = recovery.disks.find((disk) =>
    String(disk.number) === recovery.selectedDiskNumber)?.displayName ?? "";
  const volumeName = recovery.volumes.find((volume) => volume.id === recovery.selectedVolumeId)?.name;

  return <>
    <PageIntro><Eyebrow>{t("scanStep")}</Eyebrow><h1>{t("configureScanHeading")}</h1>
      <p>{t("configureScanDescription")}</p></PageIntro>
    <Card size="sm" variant="flat">
      <p>{sanitizeDisplayText(sourceName)}{volumeName && <> · <span>{sanitizeDisplayText(volumeName)}</span></>}</p>
      <OrphanScanControls>
        <ScanOption>
          <label><input type="checkbox" checked={includeOrphaned} disabled={recovery.busy}
            onChange={(event) => setIncludeOrphaned(event.target.checked)} />{t("includeOrphaned")}</label>
          <InfoButton description={t("orphanScanWarning")} label={t("moreInfo")} />
        </ScanOption>
        <ScanOption>
          <label><input type="checkbox" checked={forceFreshValidation}
            disabled={recovery.busy || !includeOrphaned}
            onChange={(event) => setForceFreshValidation(event.target.checked)} />{t("forceFreshValidation")}</label>
          <InfoButton description={t("forceFreshValidationInfo")} label={t("moreInfo")} />
        </ScanOption>
        <ScanOption>
          <label><input type="checkbox" checked={enablePngFragmentReconstruction}
            disabled={recovery.busy || !includeOrphaned}
            onChange={(event) => setEnablePngFragmentReconstruction(event.target.checked)} />
            {t("enablePngFragmentReconstruction")}</label>
          <InfoButton description={t("pngFragmentReconstructionInfo")} label={t("moreInfo")} />
        </ScanOption>
        <CarvingBudgetControls>
          <FormField label={t("carvingScanBudget")}>
            <Select aria-label={t("carvingScanBudget")} value={String(scanBudgetGiB)} disabled={recovery.busy || !includeOrphaned}
              onChange={(value) => setScanBudgetGiB(Number(value) as CarvingOptions["scanBudgetGiB"])} options={[
                { value: "1", label: t("carvingBudget1") }, { value: "4", label: t("carvingBudget4") },
                { value: "16", label: t("carvingBudget16") }, { value: "64", label: t("carvingBudget64") },
              ]} />
          </FormField>
          <FormField label={t("carvingMaxFiles")}>
            <Select aria-label={t("carvingMaxFiles")} value={String(maxCarvedFiles)} disabled={recovery.busy || !includeOrphaned}
              onChange={(value) => setMaxCarvedFiles(Number(value) as CarvingOptions["maxFiles"])} options={[
                { value: "256", label: t("carvingFiles256") }, { value: "512", label: t("carvingFiles512") },
                { value: "1024", label: t("carvingFiles1024") }, { value: "2048", label: t("carvingFiles2048") },
                { value: "4096", label: t("carvingFiles4096") }, { value: "8192", label: t("carvingFiles8192") },
                { value: "16384", label: t("carvingFiles16384") },
              ]} />
          </FormField>
          <FormField label={t("carvingCandidateReadBudget")}>
            <Select aria-label={t("carvingCandidateReadBudget")} value={String(maxCandidateReadMiBPerFormat)}
              disabled={recovery.busy || !includeOrphaned}
              onChange={(value) => setMaxCandidateReadMiBPerFormat(
                Number(value) as CarvingOptions["maxCandidateReadMiBPerFormat"],
              )} options={[
                { value: "256", label: t("carvingCandidateRead256") },
                { value: "512", label: t("carvingCandidateRead512") },
                { value: "1024", label: t("carvingCandidateRead1024") },
              ]} />
          </FormField>
          <FormField label={t("carvingRetainedBudget")}>
            <Select aria-label={t("carvingRetainedBudget")} value={String(maxCarvedRetainedMiB)}
              disabled={recovery.busy || !includeOrphaned}
              onChange={(value) => setMaxCarvedRetainedMiB(Number(value) as CarvingOptions["maxRetainedMiB"])} options={[
                { value: "128", label: t("carvingRetained128") }, { value: "256", label: t("carvingRetained256") },
                { value: "512", label: t("carvingRetained512") },
              ]} />
          </FormField>
        </CarvingBudgetControls>
      </OrphanScanControls>
    </Card>
    <StepActions>
      <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy}
        onClick={onBack}>← {t("back")}</Button>
      {recovery.catalogBuildActive && <Button className="brand-button--ghost" variant="ghost" size="md"
        disabled={recovery.catalogCancellationRequested}
        onClick={() => void recovery.cancelCatalogBuild()}>
        {t(recovery.catalogCancellationRequested ? "cancelRequested" : "cancelScan")}</Button>}
      <Button className="brand-button--primary" variant="primary" size="md" disabled={recovery.busy}
        onClick={onStart}>{recovery.busy ? t("scanInProgress") : t("startScan")}</Button>
    </StepActions>
  </>;
};
