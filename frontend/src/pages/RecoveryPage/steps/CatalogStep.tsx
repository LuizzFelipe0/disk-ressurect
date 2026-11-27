import React from "react";
import { Button, Card, EmptyState, Input } from "belagio-styles-lib";
import type { CatalogNode } from "../../../types/recovery";
import { RecoveryTree } from "../../../components/RecoveryTree";
import type { WorkflowStep } from "../../../components/WorkflowSteps";
import { sanitizeDisplayText } from "../../../utils/sanitizeDisplayText";
import type { RecoveryStepProps } from "./types";
import {
  AuditActions, BrowserFrame, BrowserHeading, BrowserSection, CatalogStat, CatalogStats, PartialRecoveryList,
  PreviewBody, PreviewPane, SearchBox, SelectionActions, SelectionSummary, StepActions,
} from "../style";

interface CatalogStepProps extends RecoveryStepProps {
  visited: boolean;
  activeStep: WorkflowStep;
  searchActive: boolean;
  visibleRoots?: CatalogNode[];
  catalogSummary: string;
  auditAvailable: boolean;
  onToggleFolder: (node: CatalogNode) => void;
  onPreviewFile: (node: CatalogNode) => void;
  onOpenAudit: () => void;
  auditTriggerRef: React.RefObject<HTMLSpanElement | null>;
  onStepChange: (step: WorkflowStep) => void;
}

export const CatalogStep: React.FC<CatalogStepProps> = ({
  recovery, language, t, visited, activeStep, searchActive, visibleRoots, catalogSummary,
  auditAvailable, onToggleFolder, onPreviewFile, onOpenAudit, auditTriggerRef, onStepChange,
}) => {
  if (!visited) return null;

  return <div hidden={activeStep !== 3}>
    <CatalogStats aria-label={t("foundFiles")}>
      <CatalogStat><span>{t("catalogItems")}</span><strong>{(recovery.catalog?.recordCount ?? 0).toLocaleString(language)}</strong></CatalogStat>
      <CatalogStat><span>{t("selectedItems")}</span><strong>{(recovery.selectedIds.size + recovery.selectedPartialPngIds.size).toLocaleString(language)}</strong></CatalogStat>
      <CatalogStat><span>{t("fileTypesCount")}</span><strong>{(recovery.catalog?.availableExtensions.length ?? 0).toLocaleString(language)}</strong></CatalogStat>
    </CatalogStats>
    <BrowserFrame><Card size="sm" variant="flat"><BrowserSection>
      <BrowserHeading>
        <div><h2>{t("foundFiles")}</h2><p>{catalogSummary}</p></div>
        <AuditActions>
          {recovery.catalog && <SelectionSummary>{recovery.selectedIds.size + recovery.selectedPartialPngIds.size} {t("selectedItems")}</SelectionSummary>}
          <SelectionActions>
            <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog}
              onClick={recovery.selectAll}>{t("selectAll")}</Button>
            <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog}
              onClick={recovery.clearSelection}>{t("clearSelection")}</Button>
          </SelectionActions>
          {auditAvailable && <span ref={auditTriggerRef}><Button className="brand-button--ghost" variant="ghost" size="md"
            aria-haspopup="dialog" aria-controls="disk-audit-overlay" onClick={onOpenAudit}>{t("diskAuditDetails")}</Button></span>}
        </AuditActions>
      </BrowserHeading>
      {recovery.catalog && <SearchBox><Input type="search" aria-label={t("searchFilesAria")}
        placeholder={t("searchFiles")} disabled={recovery.busy} value={recovery.searchQuery}
        onChange={recovery.setSearchQuery} /></SearchBox>}
      {!recovery.catalog ? <EmptyState title={t("emptyCatalog")} />
        : visibleRoots?.length ? <>
          {searchActive && recovery.searchingCatalog && <p role="status">{t("searchingCatalog")}</p>}
          <RecoveryTree roots={visibleRoots} childrenById={recovery.childrenById}
            expandedFolderIds={recovery.expandedFolderIds} loadingFolderIds={recovery.loadingFolderIds}
            isSelected={recovery.isSelected} onToggleFolder={onToggleFolder}
            onToggleSelection={recovery.toggleSelection} onPreview={onPreviewFile} language={language} />
        </> : searchActive && recovery.searchingCatalog ? <p role="status">{t("searchingCatalog")}</p>
          : <EmptyState title={searchActive ? t("noMatches") : t("noFiles")} />}
      {(recovery.catalog?.partialPngRecoveries?.length ?? 0) > 0 && <section aria-labelledby="partial-png-heading">
        <h3 id="partial-png-heading">{t("partialPngResultsHeading")}</h3>
        <p>{t("partialPngResultsDescription")}</p>
        <PartialRecoveryList>{recovery.catalog?.partialPngRecoveries?.map((item) => <label key={item.id}>
          <input type="checkbox" checked={recovery.selectedPartialPngIds.has(item.id)} disabled={recovery.busy}
            onChange={(event) => recovery.togglePartialPngSelection(item.id, event.target.checked)} />
          <span>{t("partialPngItem", {
            width: item.width, height: item.height, recoveredRows: item.recoveredRows,
            missingRows: item.height - item.recoveredRows,
          })}</span>
          <small>{t("partialPngIntegrityUnknown")}</small>
        </label>)}</PartialRecoveryList>
      </section>}
    </BrowserSection></Card>
    <PreviewPane>
      <Card size="sm" variant="flat" hasHeader title={t("preview")}>
        <PreviewBody aria-live="polite">
          {recovery.previewLoading ? <p>{t("previewLoading")}</p>
            : recovery.preview?.available && recovery.preview.kind === "image" && recovery.preview.dataBase64 ? <>
              <h3>{sanitizeDisplayText(recovery.preview.name ?? "")}</h3>
              <img alt={sanitizeDisplayText(recovery.preview.name ?? t("preview"))}
                src={`data:${recovery.preview.mimeType};base64,${recovery.preview.dataBase64}`} />
            </> : recovery.preview?.available && recovery.preview.kind === "pdf" && recovery.preview.dataBase64 ? <>
              <h3>{sanitizeDisplayText(recovery.preview.name ?? "")}</h3>
              <iframe title={sanitizeDisplayText(recovery.preview.name ?? t("preview"))}
                src={`data:${recovery.preview.mimeType};base64,${recovery.preview.dataBase64}`} />
            </> : recovery.preview?.reason === "unsupported_format" ? <p>{t("previewUnsupported")}</p>
              : recovery.preview?.reason === "too_large" ? <p>{t("previewTooLarge")}</p>
                : recovery.preview?.reason === "invalid_content" ? <p>{t("previewInvalid")}</p>
                  : <p>{t("previewHint")}</p>}
        </PreviewBody>
      </Card>
    </PreviewPane></BrowserFrame>
    <StepActions>
      <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy}
        onClick={() => onStepChange(2)}>← {t("back")}</Button>
      <Button className="brand-button--primary" variant="primary" size="md" disabled={recovery.busy || !recovery.catalog || !(recovery.selectedIds.size + recovery.selectedPartialPngIds.size)}
        onClick={() => onStepChange(4)}>{t("continue")} →</Button>
    </StepActions>
  </div>;
};
