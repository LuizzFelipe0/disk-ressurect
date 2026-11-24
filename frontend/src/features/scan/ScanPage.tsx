import React from "react";
import { Button, Card, Select } from "belagio-styles-lib";
import { useNavigate } from "react-router-dom";
import { useAppLanguage } from "../../app/language";
import { useCatalogSession, useRecoveryOperation, useStorageSession } from "../../app/recoverySession";
import { PageActions, SimplePage } from "../../app/layoutStyle";
import { translate } from "../../i18n/translations";
import type { CarvingOptions } from "../../types/recovery";

export const ScanPage: React.FC = () => {
  const storage = useStorageSession();
  const operation = useRecoveryOperation();
  const { buildCatalog, catalog } = useCatalogSession();
  const navigate = useNavigate();
  const { language } = useAppLanguage();
  const t = (key: Parameters<typeof translate>[1]) => translate(language, key);
  const [includeOrphaned, setIncludeOrphaned] = React.useState(true);
  const [scanBudgetGiB, setScanBudgetGiB] = React.useState<CarvingOptions["scanBudgetGiB"]>(64);
  const [maxFiles, setMaxFiles] = React.useState<CarvingOptions["maxFiles"]>(16384);
  const [maxRetainedMiB, setMaxRetainedMiB] = React.useState<CarvingOptions["maxRetainedMiB"]>(512);
  const [maxCandidateReadMiBPerFormat, setMaxCandidateReadMiBPerFormat] =
    React.useState<CarvingOptions["maxCandidateReadMiBPerFormat"]>(1024);
  const [forceFreshValidation, setForceFreshValidation] = React.useState(true);
  const options: CarvingOptions = { scanBudgetGiB, maxFiles, maxRetainedMiB, maxCandidateReadMiBPerFormat };

  return <SimplePage>
    <h1>{t("scanStep")}</h1>
    <Card size="sm" variant="flat">
      <p>{storage.rawImage?.displayName ?? storage.volumes.find((volume) => volume.id === storage.selectedVolumeId)?.name ?? t("selectPartition")}</p>
      <label><input type="checkbox" checked={includeOrphaned} disabled={operation.busy}
        onChange={(event) => setIncludeOrphaned(event.target.checked)} />{t("includeOrphaned")}</label>
      <p>{t("orphanScanWarning")}</p>
      <label><input type="checkbox" checked={forceFreshValidation} disabled={!includeOrphaned || operation.busy}
        onChange={(event) => setForceFreshValidation(event.target.checked)} />{t("forceFreshValidation")}</label>
      <label>{t("carvingScanBudget")}</label>
      <Select aria-label={t("carvingScanBudget")} value={String(scanBudgetGiB)} disabled={!includeOrphaned || operation.busy}
        onChange={(value) => setScanBudgetGiB(Number(value) as CarvingOptions["scanBudgetGiB"])} options={[
          { value: "1", label: t("carvingBudget1") }, { value: "4", label: t("carvingBudget4") },
          { value: "16", label: t("carvingBudget16") }, { value: "64", label: t("carvingBudget64") },
        ]} />
      <label>{t("carvingMaxFiles")}</label>
      <Select aria-label={t("carvingMaxFiles")} value={String(maxFiles)} disabled={!includeOrphaned || operation.busy}
        onChange={(value) => setMaxFiles(Number(value) as CarvingOptions["maxFiles"])} options={[
          { value: "256", label: t("carvingFiles256") }, { value: "512", label: t("carvingFiles512") },
          { value: "1024", label: t("carvingFiles1024") }, { value: "2048", label: t("carvingFiles2048") },
          { value: "4096", label: t("carvingFiles4096") }, { value: "8192", label: t("carvingFiles8192") },
          { value: "16384", label: t("carvingFiles16384") },
        ]} />
      <label>{t("carvingCandidateReadBudget")}</label>
      <Select aria-label={t("carvingCandidateReadBudget")} value={String(maxCandidateReadMiBPerFormat)} disabled={!includeOrphaned || operation.busy}
        onChange={(value) => setMaxCandidateReadMiBPerFormat(Number(value) as CarvingOptions["maxCandidateReadMiBPerFormat"])} options={[
          { value: "256", label: t("carvingCandidateRead256") }, { value: "512", label: t("carvingCandidateRead512") },
          { value: "1024", label: t("carvingCandidateRead1024") },
        ]} />
      <label>{t("carvingRetainedBudget")}</label>
      <Select aria-label={t("carvingRetainedBudget")} value={String(maxRetainedMiB)} disabled={!includeOrphaned || operation.busy}
        onChange={(value) => setMaxRetainedMiB(Number(value) as CarvingOptions["maxRetainedMiB"])} options={[
          { value: "128", label: t("carvingRetained128") }, { value: "256", label: t("carvingRetained256") },
          { value: "512", label: t("carvingRetained512") },
        ]} />
      <PageActions>
        <Button className="brand-button--primary" variant="primary" size="md"
          disabled={!storage.selectedVolumeId || operation.busy}
          onClick={() => void buildCatalog(includeOrphaned, options, forceFreshValidation)}>{t("buildCatalog")}</Button>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={!catalog}
          onClick={() => navigate("/catalog")}>{t("catalogStep")}</Button>
      </PageActions>
    </Card>
  </SimplePage>;
};
