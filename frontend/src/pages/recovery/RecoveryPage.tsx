import React from "react";
import { Button, Card, DropdownCheckbox, Input } from "belagio-styles-lib";
import { Navigate } from "react-router-dom";
import { useAppLanguage } from "../../app/language";
import { useCatalogSession, useRecoveryOperation, useRecoverySession, useStorageSession } from "../../app/recoverySession";
import { PageActions, SimplePage } from "../../app/layoutStyle";
import { translate } from "../../i18n/translations";
import { getExtensionSelectionUpdates, getMinimumSizeKb } from "../../utils/filterSelection";
import { sanitizeDisplayText } from "../../utils/sanitizeDisplayText";

export const RecoveryPage: React.FC = () => {
  const catalog = useCatalogSession();
  const recovery = useRecoverySession();
  const operation = useRecoveryOperation();
  const storage = useStorageSession();
  const { language } = useAppLanguage();
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) => translate(language, key, values);

  if (!catalog.catalog) return <Navigate to="/scan" replace />;
  if (!catalog.selectedIds.size) return <Navigate to="/catalog" replace />;

  return <SimplePage>
    <h1>{t("recoveryStep")}</h1>
    <Card size="sm" variant="flat">
      <p>{t("selectedItems")}: {catalog.selectedIds.size}</p>
      <label>{t("saveFiles")}</label>
      <PageActions>
        <Input aria-label={t("saveFiles")} value={recovery.outputDirectory}
          placeholder={t("chooseFolderPlaceholder")} disabled={operation.busy}
          onChange={recovery.setOutputDirectory} />
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={operation.busy}
          onClick={() => void recovery.chooseOutputDirectory()}>{t("chooseFolder")}</Button>
      </PageActions>
      {storage.rawImage && <p role="note">{t("rawDestinationNotice")}</p>}
      <DropdownCheckbox label={t("fileTypes")} placeholder={t("allFileTypes")}
        options={recovery.availableExtensions.map((extension) => ({ value: extension, label: extension }))}
        value={recovery.extensions} disabled={operation.busy}
        onChange={(values) => getExtensionSelectionUpdates(recovery.availableExtensions, values).forEach(({ extension, checked }) =>
          recovery.setExtensionSelected(extension, checked))} />
      <DropdownCheckbox label={t("minimumSize")} placeholder={t("anySize")}
        value={[String(recovery.minimumSizeKb)]} disabled={operation.busy} options={[
          { value: "0", label: t("anySize") }, { value: "5", label: "5 KB" },
          { value: "25", label: "25 KB" }, { value: "100", label: "100 KB" },
          { value: "1024", label: "1 MB" },
        ]} onChange={(values) => recovery.setMinimumSizeKb(getMinimumSizeKb(values))} />
      <p>{catalog.selectedIds.size} {t("selectedItems")} · {recovery.extensions.length} {t("fileTypesCount")}</p>
      <PageActions>
        <Button className="brand-button--success" variant="success" size="md"
          disabled={operation.busy || !recovery.outputDirectory.trim() || !recovery.extensions.length}
          onClick={() => void recovery.recover()}>{t("recoverSelected")}</Button>
      </PageActions>
    </Card>
    {catalog.catalog?.diskValidation && <Card size="sm" variant="flat">
      <h2>{t("diskAuditDetails")}</h2>
      <p>{t("validationInconclusive", {
        coverage: catalog.catalog.diskValidation.sizeBytes
          ? Math.floor(catalog.catalog.diskValidation.bytesRead * 100 / catalog.catalog.diskValidation.sizeBytes) : 0,
        errors: catalog.catalog.diskValidation.readErrorCount,
        deleted: catalog.catalog.diskValidation.deletedMftRecordCount,
        orphans: catalog.catalog.diskValidation.orphanedFileRecordCount,
        inconsistent: catalog.catalog.diskValidation.inconsistentMftRecordCount ?? 0,
      })}</p>
    </Card>}
    {recovery.recoveryResult && <Card size="sm" variant="flat">
      <h2>{t("recoveryResults")}</h2>
      <p>{t("recoveryResultSummary", {
        selected: recovery.recoveryResult.selectedCount ?? 0,
        candidates: recovery.recoveryResult.candidateCount,
        recovered: recovery.recoveryResult.recoveredCount,
        rejected: recovery.recoveryResult.rejectedCount ?? 0,
      })}</p>
      {recovery.recoveryResult.resultsTruncated && <p>{t("recoveryResultsTruncated")}</p>}
      <ul>{(recovery.recoveryResult.results ?? []).map((item, index) => <li key={`${item.path}:${index}`}>
        <strong>{sanitizeDisplayText(item.name || item.path)}</strong> · {sanitizeDisplayText(item.status)}
        {item.reason && ` — ${sanitizeDisplayText(item.reason)}`} ({item.bytesWritten.toLocaleString(language)} bytes)
      </li>)}</ul>
    </Card>}
  </SimplePage>;
};
