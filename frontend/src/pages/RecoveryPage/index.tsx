import React from "react";
import { Button, Card, DropdownCheckbox, Footer as BelagioFooter, Header, Input, LanguageToggle, Select, type SiteLanguage } from "belagio-styles-lib";
import { useNavigate, useSearchParams } from "react-router-dom";
import logo from "../../assets/disk-ressurect-logo.png";
import filterIcon from "../../assets/filter.png";
import { useRecoveryController } from "../../hooks/useRecoveryController";
import { EmptyState } from "../../components/EmptyState";
import { ErrorNotice } from "../../components/ErrorNotice";
import { RecoveryTree } from "../../components/RecoveryTree";
import { RecoveryStatusPanel } from "../../components/RecoveryStatusPanel";
import { DiskAuditOverlay } from "../../components/DiskAuditOverlay";
import type { CarvingOptions } from "../../types/recovery";
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
  CarvingBudgetControls,
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
  DestinationInput,
  FormControl,
  FormControlCaption,
  FilterBackdrop,
  HeaderActions,
  FilterPanel,
  FilterPanelContent,
  FilterPanelHeading,
  FilterSection,
  OrphanScanControls,
  PreviewBody,
  PreviewPane,
  ValidationNotice,
} from "./style";

export const RecoveryPage: React.FC = () => {
  const recovery = useRecoveryController();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const rawPickerRequested = React.useRef(false);
  const [language, setLanguage] = React.useState<SiteLanguage>(() => {
    const saved = window.localStorage.getItem("disk-ressurect:language");
    return saved === "en-US" || saved === "es-ES" || saved === "fr-FR" || saved === "zh-CN" ? saved : "pt-BR";
  });
  const [includeOrphaned, setIncludeOrphaned] = React.useState(true);
  const [forceFreshValidation, setForceFreshValidation] = React.useState(true);
  const [scanBudgetGiB, setScanBudgetGiB] = React.useState<CarvingOptions["scanBudgetGiB"]>(64);
  const [maxCarvedFiles, setMaxCarvedFiles] = React.useState<CarvingOptions["maxFiles"]>(16384);
  const [maxCarvedRetainedMiB, setMaxCarvedRetainedMiB] = React.useState<CarvingOptions["maxRetainedMiB"]>(512);
  const [maxCandidateReadMiBPerFormat, setMaxCandidateReadMiBPerFormat] =
    React.useState<CarvingOptions["maxCandidateReadMiBPerFormat"]>(1024);
  const [auditOpen, setAuditOpen] = React.useState(false);
  const [recoveryResultsOpen, setRecoveryResultsOpen] = React.useState(false);
  const [filtersOpen, setFiltersOpen] = React.useState(false);
  const filterTriggerRef = React.useRef<HTMLSpanElement>(null);
  const filtersWereOpen = React.useRef(false);
  const auditTriggerRef = React.useRef<HTMLSpanElement>(null);
  const auditWasOpen = React.useRef(false);
  const recoveryResultsTriggerRef = React.useRef<HTMLSpanElement>(null);
  const recoveryResultsWereOpen = React.useRef(false);
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
  const recycleBinRecovery = recovery.catalog?.recycleBinRecovery;
  const usnJournalEvidence = recovery.catalog?.usnJournalEvidence;
  const ntfsLogFileEvidence = recovery.catalog?.ntfsLogFileEvidence;
  const lowConfidenceTiers = lowConfidenceCarving ? [
    { key: "bitmapUnobserved" as const, summary: lowConfidenceCarving.bitmapUnobserved },
    { key: "possiblyReused" as const, summary: lowConfidenceCarving.possiblyReused },
  ] : [];
  const closeAudit = React.useCallback(() => setAuditOpen(false), []);
  React.useEffect(() => {
    if (searchParams.get("source") === "image" && !rawPickerRequested.current) {
      rawPickerRequested.current = true;
      void recovery.selectRawImage();
    }
  }, [searchParams, recovery.selectRawImage]);
  React.useEffect(() => {
    if (auditWasOpen.current && !auditOpen) {
      auditTriggerRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    }
    auditWasOpen.current = auditOpen;
  }, [auditOpen]);
  React.useEffect(() => {
    if (recoveryResultsWereOpen.current && !recoveryResultsOpen) {
      recoveryResultsTriggerRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    }
    recoveryResultsWereOpen.current = recoveryResultsOpen;
  }, [recoveryResultsOpen]);
  React.useEffect(() => {
    if (!filtersOpen) {
      if (filtersWereOpen.current) filterTriggerRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
      filtersWereOpen.current = false;
      return;
    }
    filtersWereOpen.current = true;
    document.getElementById("recovery-filter-panel")?.querySelector<HTMLButtonElement>("button")?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFiltersOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [filtersOpen]);
  const validationCoverage = validation?.sizeBytes
    ? Math.min(100, Math.floor((validation.bytesRead / validation.sizeBytes) * 100))
    : 0;
  const carvingHasReachedFormatLimit = (summary: NonNullable<typeof contentCarving>) => [
    summary.candidateLimitReachedByExtension,
    summary.fileSizeLimitReachedByExtension,
    summary.decodedDataLimitReachedByExtension,
  ].some((flags) => Object.values(flags ?? {}).some(Boolean));

  const carvingFormatLabel = (family: string) => family === ".office_zip"
    ? "OOXML (.docx, .docm, .xlsx, .xlsm)"
    : family;

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
          extension: carvingFormatLabel(extension),
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
        <Header icon={logo} title="Disk-Ressurect" actions={<HeaderActions>
          {recovery.recoveryResult && <span ref={recoveryResultsTriggerRef}><Button className="brand-button--ghost" variant="ghost" size="sm"
            onClick={() => setRecoveryResultsOpen(true)}>{t("recoveryResults")}</Button></span>}
          <Button className="brand-button--ghost" variant="ghost" size="sm" disabled={recovery.busy}
            onClick={() => navigate("/")}>{t("home")}</Button>
          <span ref={filterTriggerRef}><Button className="brand-button--ghost" variant="ghost" size="sm"
            aria-haspopup="dialog" aria-expanded={filtersOpen} aria-controls="recovery-filter-panel"
            onClick={() => setFiltersOpen(true)}><img src={filterIcon} alt="" />{t("openFilters")}</Button></span>
          <LanguageToggle value={language} size="sm" onChange={(next) => {
            setLanguage(next);
            window.localStorage.setItem("disk-ressurect:language", next);
          }} aria-label="Idioma / Language / Idioma / Langue / 语言" />
        </HeaderActions>} />
      </PageHeader>

      <PageContent id="recovery-page-content">
      <Card size="sm" variant="flat"><FormGrid>
        <FormControl><FormControlCaption>{t("sourceDisk")}</FormControlCaption><Select aria-label={t("sourceDiskAria")} value={recovery.selectedDiskNumber} disabled={recovery.busy}
          onChange={recovery.selectDisk} options={[
            { value: "", label: recovery.backendStatus === "error" ? t("backendUnavailable") : t("selectDisk") },
            ...recovery.disks.map((disk) => ({ value: String(disk.number), label: sanitizeDisplayText(disk.displayName) })),
          ]} /></FormControl>
        <ActionRow>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy}
            onClick={() => void recovery.selectRawImage()}>{t("selectRawImage")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy} onClick={() => void recovery.refreshDisks()}>{t("refresh")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || (!recovery.selectedDiskNumber && !recovery.rawImage)}
            onClick={() => void recovery.findPartitions(false)}>{t("findPartitions")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || (!recovery.selectedDiskNumber && !recovery.rawImage)}
            onClick={() => void recovery.findPartitions(true)}>{selectedDiskHasCachedScan && !recovery.rawImage ? t("deepScanAgain") : t("deepScan")}</Button>
        </ActionRow>
        {recovery.rawImage && <p role="status">{t("rawImageSelected", { name: sanitizeDisplayText(recovery.rawImage.displayName) })}</p>}
        <FormControl><FormControlCaption>{t("partitionLabel")}</FormControlCaption><Select aria-label={t("partitionLabel")} value={recovery.selectedVolumeId}
          disabled={recovery.busy || !recovery.volumes.length} onChange={recovery.selectVolume} options={[
            { value: "", label: recovery.volumes.length ? t("selectPartition") : t("searchPartitions") },
            ...recovery.volumes.map((volume) => ({ value: volume.id, label: sanitizeDisplayText(volume.name) })),
          ]} /></FormControl>
        <ActionRow>
          <Button className="brand-button--primary" variant="primary" size="md" disabled={recovery.busy || !recovery.selectedVolumeId}
            onClick={() => void recovery.buildCatalog(includeOrphaned, {
              scanBudgetGiB,
              maxFiles: maxCarvedFiles,
              maxRetainedMiB: maxCarvedRetainedMiB,
              maxCandidateReadMiBPerFormat,
            }, forceFreshValidation)}>{t("buildCatalog")}</Button>
        </ActionRow>
      </FormGrid>
      <OrphanScanControls>
        <label><input type="checkbox" checked={includeOrphaned} disabled={recovery.busy}
          onChange={(event) => setIncludeOrphaned(event.target.checked)} />{t("includeOrphaned")}</label>
        <label><input type="checkbox" checked={forceFreshValidation}
          disabled={recovery.busy || !includeOrphaned}
          onChange={(event) => setForceFreshValidation(event.target.checked)} />
          {t("forceFreshValidation")}</label>
        <p>{t("orphanScanWarning")}</p>
        <CarvingBudgetControls>
          <FormControl><FormControlCaption>{t("carvingScanBudget")}</FormControlCaption>
            <Select aria-label={t("carvingScanBudget")} value={String(scanBudgetGiB)} disabled={recovery.busy || !includeOrphaned}
              onChange={(value) => setScanBudgetGiB(Number(value) as CarvingOptions["scanBudgetGiB"])} options={[
                { value: "1", label: t("carvingBudget1") },
                { value: "4", label: t("carvingBudget4") },
                { value: "16", label: t("carvingBudget16") },
                { value: "64", label: t("carvingBudget64") },
              ]} />
          </FormControl>
          <FormControl><FormControlCaption>{t("carvingMaxFiles")}</FormControlCaption>
            <Select aria-label={t("carvingMaxFiles")} value={String(maxCarvedFiles)} disabled={recovery.busy || !includeOrphaned}
              onChange={(value) => setMaxCarvedFiles(Number(value) as CarvingOptions["maxFiles"])} options={[
                { value: "256", label: t("carvingFiles256") },
                { value: "512", label: t("carvingFiles512") },
                { value: "1024", label: t("carvingFiles1024") },
                { value: "2048", label: t("carvingFiles2048") },
                { value: "4096", label: t("carvingFiles4096") },
                { value: "8192", label: t("carvingFiles8192") },
                { value: "16384", label: t("carvingFiles16384") },
              ]} />
          </FormControl>
          <FormControl><FormControlCaption>{t("carvingCandidateReadBudget")}</FormControlCaption>
            <Select aria-label={t("carvingCandidateReadBudget")}
              value={String(maxCandidateReadMiBPerFormat)} disabled={recovery.busy || !includeOrphaned}
              onChange={(value) => setMaxCandidateReadMiBPerFormat(
                Number(value) as CarvingOptions["maxCandidateReadMiBPerFormat"],
              )} options={[
                { value: "256", label: t("carvingCandidateRead256") },
                { value: "512", label: t("carvingCandidateRead512") },
                { value: "1024", label: t("carvingCandidateRead1024") },
              ]} />
          </FormControl>
          <FormControl><FormControlCaption>{t("carvingRetainedBudget")}</FormControlCaption>
            <Select aria-label={t("carvingRetainedBudget")} value={String(maxCarvedRetainedMiB)} disabled={recovery.busy || !includeOrphaned}
              onChange={(value) => setMaxCarvedRetainedMiB(Number(value) as CarvingOptions["maxRetainedMiB"])} options={[
                { value: "128", label: t("carvingRetained128") },
                { value: "256", label: t("carvingRetained256") },
                { value: "512", label: t("carvingRetained512") },
              ]} />
          </FormControl>
        </CarvingBudgetControls>
      </OrphanScanControls></Card>

      <Card size="sm" variant="flat"><DestinationRow>
        <DestinationInput><FormControl><FormControlCaption>{t("saveFiles")}</FormControlCaption><Input type="text" aria-label={t("saveFiles")} value={recovery.outputDirectory}
          disabled={recovery.busy} placeholder={t("chooseFolderPlaceholder")}
          onChange={recovery.setOutputDirectory} /></FormControl></DestinationInput>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy} onClick={() => void recovery.chooseOutputDirectory()}>{t("chooseFolder")}</Button>
      </DestinationRow></Card>
      {recovery.rawImage && <p role="note">{t("rawDestinationNotice")}</p>}

      <BrowserFrame><Card size="sm" variant="flat"><BrowserSection>
        <BrowserHeading>
          <div><h2>{t("foundFiles")}</h2>
            <p>{catalogSummary}</p>
          </div>
          <AuditActions>
            {recovery.catalog && <SelectionSummary>{recovery.selectedIds.size} {t("selectedItems")}</SelectionSummary>}
            <SelectionActions>
              <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog} onClick={recovery.selectAll}>{t("selectAll")}</Button>
              <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog} onClick={recovery.clearSelection}>{t("clearSelection")}</Button>
              <Button className="brand-button--success" variant="success" size="md" disabled={recovery.busy || !recovery.catalog || !recovery.selectedIds.size || !recovery.extensions.length || !recovery.outputDirectory.trim()}
                onClick={() => void recovery.recover()}>{t("recoverSelected")}</Button>
            </SelectionActions>
            {(validation || contentCarving || lowConfidenceCarving
              || recycleBinRecovery || usnJournalEvidence || ntfsLogFileEvidence) && <span ref={auditTriggerRef}>
              <Button className="brand-button--ghost" variant="ghost" size="md"
                aria-haspopup="dialog" aria-controls="disk-audit-overlay"
                onClick={() => setAuditOpen(true)}>{t("diskAuditDetails")}</Button>
            </span>}
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

      {recoveryResultsOpen && recovery.recoveryResult && <DiskAuditOverlay
        id="recovery-results-overlay"
        title={t("recoveryResults")}
        closeLabel={t("closeDetails")}
        onClose={() => setRecoveryResultsOpen(false)}
      >
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
      </DiskAuditOverlay>}

      {filtersOpen && <FilterBackdrop onMouseDown={(event) => {
        if (event.target === event.currentTarget) setFiltersOpen(false);
      }}>
        <FilterPanel id="recovery-filter-panel" role="dialog" aria-modal="true" aria-labelledby="filter-panel-title">
          <FilterPanelContent>
            <FilterPanelHeading><h2 id="filter-panel-title">{t("openFilters")}</h2>
              <Button className="brand-button--ghost" variant="ghost" size="md" onClick={() => setFiltersOpen(false)}>{t("closeDetails")}</Button>
            </FilterPanelHeading>
            <FilterSection>
              <DropdownCheckbox label={t("fileTypes")} placeholder={t("allFileTypes")}
                options={recovery.availableExtensions.map((extension) => ({ value: extension, label: extension }))}
                value={recovery.extensions} disabled={recovery.busy}
                onChange={(values) => getExtensionSelectionUpdates(recovery.availableExtensions, values).forEach(({ extension, checked }) =>
                  recovery.setExtensionSelected(extension, checked))} />
              <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.availableExtensions.length}
                onClick={() => recovery.availableExtensions.forEach((extension) =>
                  recovery.setExtensionSelected(extension, !allExtensionsSelected))}>{t("allTypes")}</Button>
            </FilterSection>
            <FilterSection>
              <DropdownCheckbox label={t("minimumSize")} placeholder={t("anySize")} value={[String(recovery.minimumSizeKb)]}
                disabled={recovery.busy} options={[
                  { value: "0", label: t("anySize") },
                  { value: "5", label: "5 KB" },
                  { value: "25", label: "25 KB" },
                  { value: "100", label: "100 KB" },
                  { value: "1024", label: "1 MB" },
                ]} onChange={(values) => recovery.setMinimumSizeKb(getMinimumSizeKb(values))} />
            </FilterSection>
          </FilterPanelContent>
        </FilterPanel>
      </FilterBackdrop>}

      {auditOpen && <DiskAuditOverlay
        id="disk-audit-overlay"
        title={t("diskAuditDetails")}
        closeLabel={t("closeDetails")}
        onClose={closeAudit}
      >
        {validation && <ValidationNotice role="status" $inconclusive={validation.assessment === "inconclusive"}>
          {validation.coverageStatus === "unavailable"
            ? t("validationUnavailable", { error: validation.validationError ?? "Unknown error" })
            : validation.evidenceFreshness === "cached_snapshot"
              ? t("validationCachedSnapshot", {
                scannedAt: validation.evidenceScannedAt ?? "unknown",
                coverage: validationCoverage,
              })
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
            formats: contentCarving.formatsAttempted.map(carvingFormatLabel).join(", ") || "—",
          })}</p>}
          {contentCarving.validationScope && <p>{t("carvingValidationScope", {
            scope: contentCarving.validationScope === "contiguous_structure_and_signature"
              ? t("carvingScopeContiguous")
              : contentCarving.validationScope,
          })}</p>}
          {renderFormatDiagnostics(contentCarving)}
        </section>}
        {recycleBinRecovery && <section aria-label={t("recycleBinRecoveryHeading")}>
          <h3>{t("recycleBinRecoveryHeading")}</h3>
          <ValidationNotice role="status" $inconclusive={recycleBinRecovery.inconclusive}>
            {t("recycleBinRecoverySummary", {
              aliases: recycleBinRecovery.aliasesAdded,
              paired: recycleBinRecovery.pairedCount,
              indexes: recycleBinRecovery.indexCount,
              missing: recycleBinRecovery.missingContentCount,
              mismatched: recycleBinRecovery.metadataMismatchCount,
            })}
          </ValidationNotice>
          <p>{t("recycleBinRecoveryInterpretation")}</p>
        </section>}
        {usnJournalEvidence && <section aria-label={t("usnJournalEvidenceHeading")}>
          <h3>{t("usnJournalEvidenceHeading")}</h3>
          <ValidationNotice role="status" $inconclusive={usnJournalEvidence.inconclusive}>
            {t("usnJournalEvidenceSummary", {
              journals: usnJournalEvidence.journalCount,
              streams: usnJournalEvidence.streamCount,
              records: usnJournalEvidence.parsedRecords,
              deleted: usnJournalEvidence.deletedEvents,
              bytes: usnJournalEvidence.bytesRead.toLocaleString(language),
            })}
            {usnJournalEvidence.limitReached && ` ${t("usnJournalLimitReached")}`}
            {usnJournalEvidence.correlationLimitReached && ` ${t("usnMftCorrelationLimitReached")}`}
          </ValidationNotice>
          <p>{t("usnMftCorrelationSummary", {
            matched: usnJournalEvidence.matchedMftRecords ?? 0,
            deleted: usnJournalEvidence.matchedDeletedMftRecords ?? 0,
            validated: usnJournalEvidence.signatureMatchedRecords ?? 0,
            aliases: usnJournalEvidence.aliasesAdded ?? 0,
            stale: usnJournalEvidence.staleReferences ?? 0,
            missing: usnJournalEvidence.unmatchedReferences ?? 0,
          })}</p>
          <p>{t("usnJournalEvidenceInterpretation")}</p>
        </section>}
        {ntfsLogFileEvidence && <section aria-label={t("ntfsLogFileEvidenceHeading")}>
          <h3>{t("ntfsLogFileEvidenceHeading")}</h3>
          <ValidationNotice role="status" $inconclusive={ntfsLogFileEvidence.inconclusive}>
            {t("ntfsLogFileEvidenceSummary", {
              pages: ntfsLogFileEvidence.pagesExamined.toLocaleString(language),
              restart: ntfsLogFileEvidence.restartPages.toLocaleString(language),
              records: ntfsLogFileEvidence.recordPages.toLocaleString(language),
              bytes: ntfsLogFileEvidence.bytesRead.toLocaleString(language),
              lsns: ntfsLogFileEvidence.currentLsns.join(", ") || "—",
              errors: ntfsLogFileEvidence.errorCount.toLocaleString(language),
            })}
            {ntfsLogFileEvidence.limitReached && ` ${t("ntfsLogFileEvidenceLimitReached")}`}
          </ValidationNotice>
          <p>{t("ntfsLogFileEvidenceInterpretation")}</p>
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
