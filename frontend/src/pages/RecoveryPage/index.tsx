import React from "react";
import { Button, Card, DropdownCheckbox, EmptyState, FormField, Input, Select } from "belagio-styles-lib";
import { useSearchParams } from "react-router-dom";
import filterIcon from "../../assets/filter.png";
import { useRecoveryController } from "../../hooks/useRecoveryController";
import { useLanguagePreference } from "../../hooks/useLanguagePreference";
import { WorkflowFooter, WorkflowHeader } from "../../components/WorkflowChrome";
import { WorkflowSteps, type WorkflowStep } from "../../components/WorkflowSteps";
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
  PageContent,
  PageLayout,
  SearchBox,
  SelectionActions,
  SelectionSummary,
  DestinationInput,
  FormControl,
  FormControlCaption,
  FilterBackdrop,
  FilterPanel,
  FilterPanelContent,
  FilterPanelHeading,
  FilterSection,
  OrphanScanControls,
  PreviewBody,
  PreviewPane,
  ValidationNotice,
  PageIntro,
  StepActions,
  WorkflowPanel,
  SourceList,
  DeviceOption,
  DeviceIcon,
  DeviceDetails,
  SourceSelectedTag,
  CatalogStats,
  CatalogStat,
} from "./style";

export const RecoveryPage: React.FC = () => {
  const recovery = useRecoveryController();
  const [searchParams] = useSearchParams();
  const rawPickerRequested = React.useRef(false);
  const { language, changeLanguage } = useLanguagePreference();
  const [activeStep, setActiveStep] = React.useState<WorkflowStep>(1);
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

  const highestAvailableStep: WorkflowStep = recovery.catalog
    ? recovery.selectedIds.size ? 4 : 3
    : recovery.selectedVolumeId ? 2 : 1;
  const workflowLabels: [string, string, string, string, string] = [
    t("home"), t("storageStep"), t("scanStep"), t("catalogStep"), t("recoveryStep"),
  ];
  const runCatalogBuild = async () => {
    const built = await recovery.buildCatalog(includeOrphaned, {
      scanBudgetGiB,
      maxFiles: maxCarvedFiles,
      maxRetainedMiB: maxCarvedRetainedMiB,
      maxCandidateReadMiBPerFormat,
    }, forceFreshValidation);
    if (built) setActiveStep(3);
  };

  return (
    <PageLayout lang={language}>
      <WorkflowHeader language={language} onLanguageChange={changeLanguage}>
          {recovery.recoveryResult && <span ref={recoveryResultsTriggerRef}><Button className="brand-button--ghost" variant="ghost" size="sm"
            onClick={() => setRecoveryResultsOpen(true)}>{t("recoveryResults")}</Button></span>}
          {activeStep === 3 && <span ref={filterTriggerRef}><Button className="brand-button--ghost" variant="ghost" size="sm"
            aria-haspopup="dialog" aria-expanded={filtersOpen} aria-controls="recovery-filter-panel"
            onClick={() => setFiltersOpen(true)}><img src={filterIcon} alt="" />{t("openFilters")}</Button></span>}
      </WorkflowHeader>

      <PageContent id="recovery-page-content">
      <WorkflowSteps activeStep={activeStep} highestAvailableStep={highestAvailableStep}
        labels={workflowLabels} ariaLabel={t("stepsNavigation")} disabled={recovery.busy}
        onStepChange={setActiveStep} />
      <WorkflowPanel>
      {activeStep === 1 && <>
      <PageIntro><Eyebrow>{t("storageStep")}</Eyebrow><h1>{t("selectSourceHeading")}</h1><p>{t("selectSourceDescription")}</p></PageIntro>
      <Card size="sm" variant="flat"><FormGrid>
        <FormControl><FormControlCaption>{t("sourceDisk")}</FormControlCaption>
          {recovery.rawImage ? <DeviceOption type="button" $selected disabled>
            <DeviceIcon aria-hidden="true">▤</DeviceIcon>
            <DeviceDetails><strong>{sanitizeDisplayText(recovery.rawImage.displayName)}</strong><small>{t("imageSourceDescription")}</small></DeviceDetails>
            <SourceSelectedTag>{t("selectedLabel")}</SourceSelectedTag>
          </DeviceOption> : recovery.disks.length ? <SourceList>
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
            onClick={() => void recovery.selectRawImage()}>{t("selectRawImage")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy} onClick={() => void recovery.refreshDisks()}>{t("refresh")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || (!recovery.selectedDiskNumber && !recovery.rawImage)}
            onClick={() => void recovery.findPartitions(false)}>{t("findPartitions")}</Button>
          <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || (!recovery.selectedDiskNumber && !recovery.rawImage)}
            onClick={() => void recovery.findPartitions(true)}>{selectedDiskHasCachedScan && !recovery.rawImage ? t("deepScanAgain") : t("deepScan")}</Button>
        </ActionRow>
        {recovery.rawImage && <p role="status">{t("rawImageSelected", { name: sanitizeDisplayText(recovery.rawImage.displayName) })}</p>}
        <FormField label={t("partitionLabel")}><Select aria-label={t("partitionLabel")} value={recovery.selectedVolumeId}
          disabled={recovery.busy || !recovery.volumes.length} onChange={recovery.selectVolume} options={[
            { value: "", label: recovery.volumes.length ? t("selectPartition") : t("searchPartitions") },
            ...recovery.volumes.map((volume) => ({ value: volume.id, label: sanitizeDisplayText(volume.name) })),
          ]} /></FormField>
      </FormGrid>
      </Card>
      <StepActions>
        <span />
        <Button className="brand-button--primary" variant="primary" size="md" disabled={recovery.busy || !recovery.selectedVolumeId}
          onClick={() => setActiveStep(2)}>{t("continue")} →</Button>
      </StepActions>
      </>}

      {activeStep === 2 && <>
      <PageIntro><Eyebrow>{t("scanStep")}</Eyebrow><h1>{t("configureScanHeading")}</h1><p>{t("configureScanDescription")}</p></PageIntro>
      <Card size="sm" variant="flat">
      <p>{sanitizeDisplayText(recovery.rawImage?.displayName
        ?? recovery.disks.find((disk) => String(disk.number) === recovery.selectedDiskNumber)?.displayName ?? "")}
        {recovery.selectedVolumeId && <> · <span>{sanitizeDisplayText(recovery.volumes.find((volume) => volume.id === recovery.selectedVolumeId)?.name ?? "")}</span></>}
      </p>
      <OrphanScanControls>
        <label><input type="checkbox" checked={includeOrphaned} disabled={recovery.busy}
          onChange={(event) => setIncludeOrphaned(event.target.checked)} />{t("includeOrphaned")}</label>
        <label><input type="checkbox" checked={forceFreshValidation}
          disabled={recovery.busy || !includeOrphaned}
          onChange={(event) => setForceFreshValidation(event.target.checked)} />
          {t("forceFreshValidation")}</label>
        <p>{t("orphanScanWarning")}</p>
        <CarvingBudgetControls>
          <FormField label={t("carvingScanBudget")}>
            <Select aria-label={t("carvingScanBudget")} value={String(scanBudgetGiB)} disabled={recovery.busy || !includeOrphaned}
              onChange={(value) => setScanBudgetGiB(Number(value) as CarvingOptions["scanBudgetGiB"])} options={[
                { value: "1", label: t("carvingBudget1") },
                { value: "4", label: t("carvingBudget4") },
                { value: "16", label: t("carvingBudget16") },
                { value: "64", label: t("carvingBudget64") },
              ]} />
          </FormField>
          <FormField label={t("carvingMaxFiles")}>
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
          </FormField>
          <FormField label={t("carvingCandidateReadBudget")}>
            <Select aria-label={t("carvingCandidateReadBudget")}
              value={String(maxCandidateReadMiBPerFormat)} disabled={recovery.busy || !includeOrphaned}
              onChange={(value) => setMaxCandidateReadMiBPerFormat(
                Number(value) as CarvingOptions["maxCandidateReadMiBPerFormat"],
              )} options={[
                { value: "256", label: t("carvingCandidateRead256") },
                { value: "512", label: t("carvingCandidateRead512") },
                { value: "1024", label: t("carvingCandidateRead1024") },
              ]} />
          </FormField>
          <FormField label={t("carvingRetainedBudget")}>
            <Select aria-label={t("carvingRetainedBudget")} value={String(maxCarvedRetainedMiB)} disabled={recovery.busy || !includeOrphaned}
              onChange={(value) => setMaxCarvedRetainedMiB(Number(value) as CarvingOptions["maxRetainedMiB"])} options={[
                { value: "128", label: t("carvingRetained128") },
                { value: "256", label: t("carvingRetained256") },
                { value: "512", label: t("carvingRetained512") },
              ]} />
          </FormField>
        </CarvingBudgetControls>
      </OrphanScanControls>
      </Card>
      <StepActions>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy}
          onClick={() => setActiveStep(1)}>← {t("back")}</Button>
        <Button className="brand-button--primary" variant="primary" size="md" disabled={recovery.busy}
          onClick={() => void runCatalogBuild()}>{recovery.busy ? t("scanInProgress") : t("startScan")}</Button>
      </StepActions>
      </>}

      {activeStep === 3 && <>
      <CatalogStats aria-label={t("foundFiles")}>
        <CatalogStat><span>{t("catalogItems")}</span><strong>{(recovery.catalog?.recordCount ?? 0).toLocaleString(language)}</strong></CatalogStat>
        <CatalogStat><span>{t("selectedItems")}</span><strong>{recovery.selectedIds.size.toLocaleString(language)}</strong></CatalogStat>
        <CatalogStat><span>{t("fileTypesCount")}</span><strong>{(recovery.catalog?.availableExtensions.length ?? 0).toLocaleString(language)}</strong></CatalogStat>
      </CatalogStats>
      <BrowserFrame><Card size="sm" variant="flat"><BrowserSection>
        <BrowserHeading>
          <div><h2>{t("foundFiles")}</h2><p>{catalogSummary}</p></div>
          <AuditActions>
            {recovery.catalog && <SelectionSummary>{recovery.selectedIds.size} {t("selectedItems")}</SelectionSummary>}
            <SelectionActions>
              <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog} onClick={recovery.selectAll}>{t("selectAll")}</Button>
              <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy || !recovery.catalog} onClick={recovery.clearSelection}>{t("clearSelection")}</Button>
            </SelectionActions>
            {(validation || contentCarving || lowConfidenceCarving
              || recycleBinRecovery || usnJournalEvidence || ntfsLogFileEvidence) && <span ref={auditTriggerRef}>
              <Button className="brand-button--ghost" variant="ghost" size="md"
                aria-haspopup="dialog" aria-controls="disk-audit-overlay"
                onClick={() => setAuditOpen(true)}>{t("diskAuditDetails")}</Button>
            </span>}
          </AuditActions>
        </BrowserHeading>
        {recovery.catalog && <SearchBox><Input type="search" aria-label={t("searchFilesAria")}
          placeholder={t("searchFiles")} disabled={recovery.busy} value={recovery.searchQuery}
          onChange={recovery.setSearchQuery} /></SearchBox>}
        {!recovery.catalog ? <EmptyState title={t("emptyCatalog")} />
          : searchActive && recovery.searchingCatalog ? <EmptyState title={t("searchingCatalog")} />
            : visibleRoots?.length ? <RecoveryTree roots={visibleRoots}
              childrenById={recovery.childrenById} expandedFolderIds={recovery.expandedFolderIds}
              loadingFolderIds={recovery.loadingFolderIds} isSelected={recovery.isSelected}
              onToggleFolder={(node) => void recovery.toggleFolder(node)}
              onToggleSelection={recovery.toggleSelection} onPreview={(node) => void recovery.previewFile(node)}
              language={language} />
              : <EmptyState title={searchActive ? t("noMatches") : t("noFiles")} />}
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
          onClick={() => setActiveStep(2)}>← {t("back")}</Button>
        <Button className="brand-button--primary" variant="primary" size="md"
          disabled={recovery.busy || !recovery.catalog || !recovery.selectedIds.size}
          onClick={() => setActiveStep(4)}>{t("continue")} →</Button>
      </StepActions>
      </>}

      {activeStep === 4 && <>
      <PageIntro><Eyebrow>{t("recoveryStep")}</Eyebrow><h1>{t("recoverSelected")}</h1><p>{t("chooseDestinationDescription")}</p></PageIntro>
      <Card size="sm" variant="flat"><div><strong>{t("selectedItems")}: {recovery.selectedIds.size}</strong></div><DestinationRow>
        <DestinationInput><FormField label={t("saveFiles")}><Input type="text" aria-label={t("saveFiles")} value={recovery.outputDirectory}
          disabled={recovery.busy} placeholder={t("chooseFolderPlaceholder")}
          onChange={recovery.setOutputDirectory} /></FormField></DestinationInput>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy} onClick={() => void recovery.chooseOutputDirectory()}>{t("chooseFolder")}</Button>
      </DestinationRow></Card>
      <p role="note">{recovery.rawImage ? t("rawDestinationNotice") : t("physicalDestinationNotice")}</p>
      <StepActions>
        <Button className="brand-button--ghost" variant="ghost" size="md" disabled={recovery.busy}
          onClick={() => setActiveStep(3)}>← {t("back")}</Button>
        <Button className="brand-button--success" variant="success" size="md"
          disabled={recovery.busy || !recovery.outputDirectory.trim() || !recovery.extensions.length}
          onClick={() => void recovery.recover()}>{recovery.busy ? t("recovering") : t("recoverSelected")}</Button>
      </StepActions>
      </>}
      </WorkflowPanel>

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
      <WorkflowFooter language={language} />
    </PageLayout>
  );
};
