import React from "react";
import { Button, Card, DropdownCheckbox, Footer as BelagioFooter, Header, Input, LanguageToggle, Select, type SiteLanguage } from "belagio-styles-lib";
import logo from "../../assets/disk-ressurect-logo.png";
import { useRecoveryController } from "../../hooks/useRecoveryController";
import { EmptyState } from "../../components/EmptyState";
import { ErrorNotice } from "../../components/ErrorNotice";
import { RecoveryTree } from "../../components/RecoveryTree";
import { RecoveryStatusPanel } from "../../components/RecoveryStatusPanel";
import { DiskAuditOverlay } from "../../components/DiskAuditOverlay";
import { sanitizeDisplayText } from "../../utils/sanitizeDisplayText";
import { translate, translateError, translateStatus } from "../../i18n/translations";
import {
  areAllExtensionsSelected,
  getExtensionSelectionUpdates,
  getMinimumSizeKb,
} from "../../utils/filterSelection";
import {
  ActionRow,
  AuditActions,
  BrowserFrame,
  BrowserHeading,
  BrowserSection,
  DestinationRow,
  Eyebrow,
  FormGrid,
  PageHeader,
  PageContent,
  PageLayout,
  SearchBox,
  SelectionActions,
  SelectionSummary,
  Toolbar,
  DestinationInput,
  FileTypesControls,
  FormControl,
  FormControlCaption,
  MinimumSizeControl,
  OrphanScanControls,
  PreviewBody,
  PreviewPane,
  ValidationNotice,
} from "./style";

export const RecoveryPage: React.FC = () => {
  const recovery = useRecoveryController();
  const [language, setLanguage] = React.useState<SiteLanguage>(() => {
    const saved = window.localStorage.getItem("disk-ressurect:language");
    return saved === "en-US" || saved === "es-ES" || saved === "fr-FR" || saved === "zh-CN" ? saved : "pt-BR";
  });
  const [includeOrphaned, setIncludeOrphaned] = React.useState(false);
  const [auditOpen, setAuditOpen] = React.useState(false);
  const auditTriggerRef = React.useRef<HTMLSpanElement>(null);
  const auditWasOpen = React.useRef(false);
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) => translate(language, key, values);
  const searchActive = Boolean(recovery.searchQuery.trim());
  const allExtensionsSelected = areAllExtensionsSelected(recovery.availableExtensions, recovery.extensions);
  const visibleRoots = searchActive
    ? recovery.searchResult?.results
    : recovery.catalog?.roots;
  const selectedDiskHasCachedScan = recovery.disks.some((disk) =>
    String(disk.number) === recovery.selectedDiskNumber && Boolean(disk.cachedPartitions?.length));
  const catalogSummary = !recovery.catalog
    ? t("catalogPrompt")
    : searchActive && recovery.searchResult
      ? recovery.searchResult.totalMatches > recovery.searchResult.results.length
        ? t("showingMatches", { visible: recovery.searchResult.results.length.toLocaleString(language), total: recovery.searchResult.totalMatches.toLocaleString(language) })
        : `${recovery.searchResult.totalMatches.toLocaleString(language)} ${t("matchingItems")}`
      : `${recovery.catalog.recordCount.toLocaleString(language)} ${t("catalogItems")} · ${recovery.catalog.availableExtensions.length.toLocaleString(language)} ${t("fileTypesCount")}${recovery.catalog.orphanScanPerformed ? ` · ${t("orphanedEntriesCount", { count: recovery.catalog.orphanedRecordCount ?? 0 })}` : ""}${(recovery.catalog.contentCarvedCount ?? 0) > 0 ? ` · ${t("contentCarvedCount", { count: recovery.catalog.contentCarvedCount ?? 0 })}` : ""}`;
  const validation = recovery.catalog?.diskValidation;
  const contentCarving = recovery.catalog?.contentCarving;
  const lowConfidenceCarving = recovery.catalog?.lowConfidenceCarving;
  const lowConfidenceTiers = lowConfidenceCarving ? [
    { key: "bitmapUnobserved" as const, summary: lowConfidenceCarving.bitmapUnobserved },
    { key: "possiblyReused" as const, summary: lowConfidenceCarving.possiblyReused },
  ] : [];
  const closeAudit = React.useCallback(() => setAuditOpen(false), []);
  React.useEffect(() => {
    if (auditWasOpen.current && !auditOpen) {
      auditTriggerRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    }
    auditWasOpen.current = auditOpen;
  }, [auditOpen]);
  const validationCoverage = validation?.sizeBytes
    ? Math.min(100, Math.floor((validation.bytesRead / validation.sizeBytes) * 100))
    : 0;
  const carvingHasReachedFormatLimit = (summary: NonNullable<typeof contentCarving>) => [
    summary.candidateLimitReachedByExtension,
    summary.fileSizeLimitReachedByExtension,
    summary.decodedDataLimitReachedByExtension,
  ].some((flags) => Object.values(flags ?? {}).some(Boolean));

  const renderFormatDiagnostics = (summary: NonNullable<typeof contentCarving>) => {
    const names = Array.from(new Set([
      ...(summary.formatsAttempted ?? []),
      ...Object.keys(summary.filesFoundByExtension ?? {}),
      ...Object.keys(summary.candidatesExaminedByExtension ?? {}),
      ...Object.keys(summary.candidateBytesReadByExtension ?? {}),
    ])).sort();
    const available = summary.filesFoundByExtension !== undefined
      || summary.candidatesExaminedByExtension !== undefined
      || summary.candidateBytesReadByExtension !== undefined
      || summary.formatsAttempted !== undefined
      || summary.validationScope !== undefined;
    if (!available || !names.length) return <p>{t("carvingDiagnosticsUnavailable")}</p>;
    return <ul>{names.map((extension) => {
      const limits = [
        summary.candidateLimitReachedByExtension?.[extension] && t("candidateReadLimit"),
        summary.fileSizeLimitReachedByExtension?.[extension] && t("fileSizeLimit"),
        summary.decodedDataLimitReachedByExtension?.[extension] && t("decodedDataLimit"),
      ].filter(Boolean).join(", ");
      return <li key={extension}>
        {t("carvingFormatStats", {
          extension,
          files: summary.filesFoundByExtension?.[extension] ?? 0,
          candidates: summary.candidatesExaminedByExtension?.[extension] ?? 0,
          bytes: (summary.candidateBytesReadByExtension?.[extension] ?? 0).toLocaleString(language),
        })}
        {limits && ` ${t("carvingLimitsReached", { limits })}`}
      </li>;
    })}</ul>;
  };

  return (
    <PageLayout lang={language}>
      <PageHeader>
        <Header icon={logo} title="Disk-Ressurect" actions={<LanguageToggle value={language} size="sm" onChange={(next) => {
          setLanguage(next);
          window.localStorage.setItem("disk-ressurect:language", next);
        }} aria-label="Idioma / Language / Idioma / Langue / 语言" />} />
      </PageHeader>

      <PageContent id="recovery-page-content">
      <Card size="sm" variant="flat"><FormGrid>
        <FormControl><FormControlCaption>{t("sourceDisk")}</FormControlCaption><Select aria-label={t("sourceDiskAria")} value={recovery.selectedDiskNumber} disabled={recovery.busy}
          onChange={recovery.selectDisk} options={[
            { value: "", label: recovery.backendStatus === "error" ? t("backendUnavailable") : t("selectDisk") },
            ...recovery.disks.map((disk) => ({ value: String(disk.number), label: sanitizeDisplayText(disk.displayName) })),
          ]} /></FormControl>
        <ActionRow>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy} onClick={() => void recovery.refreshDisks()}>{t("refresh")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.selectedDiskNumber}
            onClick={() => void recovery.findPartitions(false)}>{t("findPartitions")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.selectedDiskNumber}
            onClick={() => void recovery.findPartitions(true)}>{selectedDiskHasCachedScan ? t("deepScanAgain") : t("deepScan")}</Button>
        </ActionRow>
        <FormControl><FormControlCaption>{t("partitionLabel")}</FormControlCaption><Select aria-label={t("partitionLabel")} value={recovery.selectedVolumeId}
          disabled={recovery.busy || !recovery.volumes.length} onChange={recovery.selectVolume} options={[
            { value: "", label: recovery.volumes.length ? t("selectPartition") : t("searchPartitions") },
            ...recovery.volumes.map((volume) => ({ value: volume.id, label: sanitizeDisplayText(volume.name) })),
          ]} /></FormControl>
        <ActionRow>
          <Button className="brand-button--primary" variant="primary" size="md" disabled={recovery.busy || !recovery.selectedVolumeId}
            onClick={() => void recovery.buildCatalog(includeOrphaned)}>{t("buildCatalog")}</Button>
        </ActionRow>
      </FormGrid>
      <OrphanScanControls>
        <label><input type="checkbox" checked={includeOrphaned} disabled={recovery.busy}
          onChange={(event) => setIncludeOrphaned(event.target.checked)} />{t("includeOrphaned")}</label>
        <p>{t("orphanScanWarning")}</p>
      </OrphanScanControls></Card>

      <Card size="sm" variant="flat"><DestinationRow>
        <DestinationInput><FormControl><FormControlCaption>{t("saveFiles")}</FormControlCaption><Input type="text" aria-label={t("saveFiles")} value={recovery.outputDirectory}
          disabled={recovery.busy} placeholder={t("chooseFolderPlaceholder")}
          onChange={recovery.setOutputDirectory} /></FormControl></DestinationInput>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy} onClick={() => void recovery.chooseOutputDirectory()}>{t("chooseFolder")}</Button>
      </DestinationRow></Card>

      <Card size="sm" variant="flat"><Toolbar>
        <FileTypesControls>
          <DropdownCheckbox label={t("fileTypes")} placeholder={t("allFileTypes")}
            options={recovery.availableExtensions.map((extension) => ({ value: extension, label: extension }))}
            value={recovery.extensions} disabled={recovery.busy}
            onChange={(values) => getExtensionSelectionUpdates(recovery.availableExtensions, values).forEach(({ extension, checked }) =>
              recovery.setExtensionSelected(extension, checked))} />
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.availableExtensions.length}
            onClick={() => recovery.availableExtensions.forEach((extension) =>
              recovery.setExtensionSelected(extension, !allExtensionsSelected))}>{t("allTypes")}</Button>
        </FileTypesControls>
        <MinimumSizeControl><DropdownCheckbox label={t("minimumSize")} placeholder={t("anySize")} value={[String(recovery.minimumSizeKb)]}
          disabled={recovery.busy} options={[
            { value: "0", label: t("anySize") },
            { value: "5", label: "5 KB" },
            { value: "25", label: "25 KB" },
            { value: "100", label: "100 KB" },
            { value: "1024", label: "1 MB" },
          ]} onChange={(values) => recovery.setMinimumSizeKb(getMinimumSizeKb(values))} /></MinimumSizeControl>
        <SelectionActions>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog} onClick={recovery.selectAll}>{t("selectAll")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog} onClick={recovery.clearSelection}>{t("clearSelection")}</Button>
          <Button className="brand-button--success" variant="success" size="md" disabled={recovery.busy || !recovery.selectedIds.size || !recovery.extensions.length || !recovery.outputDirectory.trim()}
            onClick={() => void recovery.recover()}>{t("recoverSelected")}</Button>
        </SelectionActions>
      </Toolbar></Card>

      <BrowserFrame><Card size="sm" variant="flat"><BrowserSection>
        <BrowserHeading>
          <div><h2>{t("foundFiles")}</h2>
            <p>{catalogSummary}</p>
          </div>
          <AuditActions>
            {(validation || contentCarving || lowConfidenceCarving) && <span ref={auditTriggerRef}>
              <Button className="brand-button--ghost" variant="ghost" size="md"
                aria-haspopup="dialog" aria-controls="disk-audit-overlay"
                onClick={() => setAuditOpen(true)}>{t("diskAuditDetails")}</Button>
            </span>}
            {recovery.catalog && <SelectionSummary>{recovery.selectedIds.size} {t("selectedItems")}</SelectionSummary>}
          </AuditActions>
        </BrowserHeading>
        {recovery.catalog && <SearchBox><Input
          type="search"
          aria-label={t("searchFilesAria")}
          placeholder={t("searchFiles")}
          disabled={recovery.busy}
          value={recovery.searchQuery}
          onChange={recovery.setSearchQuery}
        /></SearchBox>}
        {!recovery.catalog ? <EmptyState>{t("emptyCatalog")}</EmptyState>
          : searchActive && recovery.searchingCatalog ? <EmptyState>{t("searchingCatalog")}</EmptyState>
            : visibleRoots?.length ? <RecoveryTree
          roots={visibleRoots}
          childrenById={recovery.childrenById}
          expandedFolderIds={recovery.expandedFolderIds}
          loadingFolderIds={recovery.loadingFolderIds}
          isSelected={recovery.isSelected}
          onToggleFolder={(node) => void recovery.toggleFolder(node)}
          onToggleSelection={recovery.toggleSelection}
          onPreview={(node) => void recovery.previewFile(node)}
          language={language}
        /> : <EmptyState>{searchActive ? t("noMatches") : t("noFiles")}</EmptyState>}
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

      {auditOpen && <DiskAuditOverlay
        id="disk-audit-overlay"
        title={t("diskAuditDetails")}
        closeLabel={t("closeDetails")}
        onClose={closeAudit}
      >
        {validation && <ValidationNotice role="status" $inconclusive={validation.assessment === "inconclusive"}>
          {validation.coverageStatus === "unavailable"
            ? t("validationUnavailable", { error: validation.validationError ?? "Unknown error" })
            : validation.assessment === "inconclusive"
              ? t("validationInconclusive", {
                coverage: validationCoverage,
                errors: validation.readErrorCount,
                deleted: validation.deletedMftRecordCount,
                orphans: validation.orphanedFileRecordCount,
                inconsistent: validation.inconsistentMftRecordCount ?? 0,
              })
              : t("validationEvidence", {
                coverage: validationCoverage,
                partitions: validation.partitionCount,
                ntfs: validation.ntfsVolumeCount,
                deleted: validation.deletedMftRecordCount,
                orphans: validation.orphanedFileRecordCount,
                inconsistent: validation.inconsistentMftRecordCount ?? 0,
              })}
        </ValidationNotice>}
        <p>{t("catalogRecoveryInterpretation", {
          items: (recovery.catalog?.recordCount ?? 0).toLocaleString(language),
          types: (recovery.catalog?.availableExtensions.length ?? 0).toLocaleString(language),
        })}</p>
        {validation?.orphanRecordsByAllocationStatus && <>
          <ValidationNotice role="status" $inconclusive={validation.orphanRecordsByAllocationStatus.unknown > 0}>
            {t("orphanRecordAllocationSummary", validation.orphanRecordsByAllocationStatus)}
          </ValidationNotice>
          <p>{t("allocationRecoveryInterpretation")}</p>
        </>}
        {validation && <p>{t("orphanRecoveryInterpretation")}</p>}
        {contentCarving && <ValidationNotice role="status" $inconclusive={Boolean(
          contentCarving.rangeCollectionTruncated
          || contentCarving.scanLimitReached
          || contentCarving.candidateLimitReached
          || contentCarving.fileCountLimitReached
          || contentCarving.retainedBytesLimitReached
          || carvingHasReachedFormatLimit(contentCarving)
        )}>
          {t("contentCarvingResult", {
            files: contentCarving.filesFound,
            bytes: contentCarving.bytesScanned.toLocaleString(language),
            candidateBytes: contentCarving.candidateBytesRead.toLocaleString(language),
          })}
          {(contentCarving.rangeCollectionTruncated
            || contentCarving.scanLimitReached
            || contentCarving.candidateLimitReached
            || contentCarving.fileCountLimitReached
            || contentCarving.retainedBytesLimitReached
            || carvingHasReachedFormatLimit(contentCarving)) && ` ${t("contentCarvingLimited")}`}
        </ValidationNotice>}
        {contentCarving && <section aria-label={t("carvingDiagnosticsHeading")}>
          <h3>{t("carvingDiagnosticsHeading")}</h3>
          {contentCarving.candidateReadCapBytes !== undefined && <p>{t("carvingCandidateBudget", {
            perFormat: contentCarving.candidateReadCapBytesPerFormat?.toLocaleString(language) ?? "—",
            aggregate: contentCarving.candidateReadCapBytes.toLocaleString(language),
          })}</p>}
          {contentCarving.scanByteCap !== undefined && <p>{t("carvingSizeBudget", {
            scan: contentCarving.scanByteCap.toLocaleString(language),
            maxFile: contentCarving.maxFileBytes?.toLocaleString(language) ?? "—",
            decoded: contentCarving.maxDecodedPngBytes?.toLocaleString(language) ?? "—",
            retained: contentCarving.retainedBytesCap?.toLocaleString(language) ?? "—",
            files: contentCarving.fileCountCap ?? "—",
          })}</p>}
          {contentCarving.formatsAttempted !== undefined && <p>{t("carvingFormatsAttempted", {
            formats: contentCarving.formatsAttempted.join(", ") || "—",
          })}</p>}
          {contentCarving.validationScope && <p>{t("carvingValidationScope", {
            scope: contentCarving.validationScope === "contiguous_structure_and_signature"
              ? t("carvingScopeContiguous")
              : contentCarving.validationScope,
          })}</p>}
          {renderFormatDiagnostics(contentCarving)}
        </section>}
        {lowConfidenceTiers.length > 0 && <>
          <p>{t("lowConfidenceRecoveryInterpretation")}</p>
          {lowConfidenceTiers.map(({ key, summary }) => <section key={key}>
            <h3>{t(key)}</h3>
            <ValidationNotice role="status" $inconclusive={true}>
              {t("lowConfidenceTierResult", {
                confidence: t("lowConfidenceLabel"),
                files: summary.filesFound,
                items: summary.catalogItemsAdded,
                bytes: summary.bytesScanned.toLocaleString(language),
                candidateBytes: summary.candidateBytesRead.toLocaleString(language),
              })}
              {(summary.rangeCollectionTruncated || summary.scanLimitReached
                || summary.candidateLimitReached || summary.fileCountLimitReached
                || summary.retainedBytesLimitReached
                || carvingHasReachedFormatLimit(summary)) && ` ${t("contentCarvingLimited")}`}
            </ValidationNotice>
            <p>{t("lowConfidenceBudget", {
              scanLimit: summary.scanByteCap?.toLocaleString(language) ?? "—",
              perFormat: summary.candidateReadCapBytesPerFormat?.toLocaleString(language) ?? "—",
              aggregate: summary.candidateReadCapBytes?.toLocaleString(language) ?? "—",
              maxFile: (summary.maxFileBytes ?? 0).toLocaleString(language),
              decoded: (summary.maxDecodedPngBytes ?? 0).toLocaleString(language),
              retained: summary.retainedBytesCap?.toLocaleString(language) ?? "—",
              maxFiles: summary.fileCountCap ?? "—",
            })}</p>
            {summary.rangeCollectionCapBytes !== undefined && <p>{t("lowConfidenceRangeSummary", {
              retained: summary.rangeBytesRetained?.toLocaleString(language) ?? "—",
              cap: summary.rangeCollectionCapBytes.toLocaleString(language),
            })}</p>}
            {summary.formatsAttempted !== undefined && <p>{t("carvingFormatsAttempted", {
              formats: summary.formatsAttempted.join(", ") || "—",
            })}</p>}
            {renderFormatDiagnostics(summary)}
          </section>)}
        </>}
      </DiskAuditOverlay>}

      <RecoveryStatusPanel
        status={translateStatus(recovery.status, language)}
        progress={recovery.progress}
        error={translateError(recovery.error, language)}
        busy={recovery.busy}
        isAdministrator={recovery.isAdministrator}
        partitionScanCanResume={recovery.partitionScanCanResume}
        selectedDiskNumber={recovery.selectedDiskNumber}
        backendStatus={recovery.backendStatus}
        onRetryScan={() => void recovery.findPartitions(true, true)}
        onRequestDiskAccess={() => void recovery.ensureAdministrator()}
        language={language}
      />
      </PageContent>
      <BelagioFooter
        left={["Disk-Ressurect", t("version")]}
        center={[t("footerTitle")]}
        right={[t("desktopApp")]}
      />
    </PageLayout>
  );
};
