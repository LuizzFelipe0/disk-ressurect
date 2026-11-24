import React from "react";
import { Button, Card, Select } from "belagio-styles-lib";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAppLanguage } from "../../app/language";
import { useRecoveryOperation, useStorageSession } from "../../app/recoverySession";
import { PageActions, SimplePage } from "../../app/layoutStyle";
import { translate } from "../../i18n/translations";
import { sanitizeDisplayText } from "../../utils/sanitizeDisplayText";

export const StoragePage: React.FC = () => {
  const storage = useStorageSession();
  const operation = useRecoveryOperation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const imagePickerRequested = React.useRef(false);
  const { language } = useAppLanguage();
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) => translate(language, key, values);
  React.useEffect(() => {
    if (params.get("source") === "image" && !storage.rawImage && !imagePickerRequested.current) {
      imagePickerRequested.current = true;
      void storage.selectRawImage();
    }
  }, [params, storage.rawImage, storage.selectRawImage]);

  return <SimplePage>
    <h1>{t("storageStep")}</h1>
    <Card size="sm" variant="flat">
      <label>{t("sourceDisk")}</label>
      <Select aria-label={t("sourceDiskAria")} value={storage.selectedDiskNumber}
        disabled={operation.busy || Boolean(storage.rawImage)} onChange={storage.selectDisk} options={[
          { value: "", label: operation.backendStatus === "error" ? t("backendUnavailable") : t("selectDisk") },
          ...storage.disks.map((disk) => ({ value: String(disk.number), label: sanitizeDisplayText(disk.displayName) })),
        ]} />
      <PageActions>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={operation.busy}
          onClick={() => void storage.refreshDisks()}>{t("refresh")}</Button>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={operation.busy}
          onClick={() => void storage.selectRawImage()}>{t("selectRawImage")}</Button>
        <Button className="brand-button--ghost" variant="ghost" size="md"
          disabled={operation.busy || (!storage.selectedDiskNumber && !storage.rawImage)}
          onClick={() => void storage.findPartitions(false)}>{t("findPartitions")}</Button>
        <Button className="brand-button--ghost" variant="ghost" size="md"
          disabled={operation.busy || (!storage.selectedDiskNumber && !storage.rawImage)}
          onClick={() => void storage.findPartitions(true)}>{t("deepScan")}</Button>
      </PageActions>
      {storage.rawImage && <p role="status">{t("rawImageSelected", { name: sanitizeDisplayText(storage.rawImage.displayName) })}</p>}
      <label>{t("partitionLabel")}</label>
      <Select aria-label={t("partitionLabel")} value={storage.selectedVolumeId}
        disabled={operation.busy || !storage.volumes.length} onChange={storage.selectVolume} options={[
          { value: "", label: storage.volumes.length ? t("selectPartition") : t("searchPartitions") },
          ...storage.volumes.map((volume) => ({ value: volume.id, label: sanitizeDisplayText(volume.name) })),
        ]} />
      <PageActions>
        <Button className="brand-button--primary" variant="primary" size="md"
          disabled={!storage.selectedVolumeId || operation.busy} onClick={() => navigate("/scan")}>{t("continue")}</Button>
      </PageActions>
    </Card>
  </SimplePage>;
};
