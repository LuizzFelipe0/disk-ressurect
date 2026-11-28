import React from "react";
import { Button, DropdownCheckbox } from "belagio-styles-lib";
import filterIcon from "../../assets/filter.png";
import { useRecoveryController } from "../../hooks/useRecoveryController";
import { useRecoveryNavigationGuard } from "../../hooks/useRecoveryNavigationGuard";
import { useLanguagePreference } from "../../hooks/useLanguagePreference";
import { WorkflowFooter, WorkflowHeader } from "../../components/WorkflowChrome";
import { WorkflowSteps, type WorkflowStep } from "../../components/WorkflowSteps";
import { RecoveryTree } from "../../components/RecoveryTree";
import { RecoveryStatusPanel } from "../../components/RecoveryStatusPanel";
import { StorageStep } from "./steps/StorageStep";
import { ScanStep } from "./steps/ScanStep";
import { CatalogStep } from "./steps/CatalogStep";
import { RecoveryStep } from "./steps/RecoveryStep";
import { DiskAuditOverlay } from "../../components/DiskAuditOverlay";
import type { CarvingOptions, CatalogNode } from "../../types/recovery";
import { sanitizeDisplayText } from "../../utils/sanitizeDisplayText";
import { translate, translateError, translateStatus } from "../../i18n/translations";
import {
  areAllExtensionsSelected,
  getExtensionSelectionUpdates,
  getMinimumSizeKb,
} from "../../utils/filterSelection";
import {
  BrowserFrame,
  PageContent,
  PageLayout,
  FilterBackdrop,
  FilterPanel,
  FilterPanelContent,
  FilterPanelHeading,
  FilterSection,
  ValidationNotice,
  WorkflowPanel,
} from "./style";

export const RecoveryPage: React.FC = () => {
  const recovery = useRecoveryController();
  useRecoveryNavigationGuard(recovery.busy);
  const { language, changeLanguage } = useLanguagePreference();
  const [activeStep, setActiveStep] = React.useState<WorkflowStep>(1);
  const [catalogStepVisited, setCatalogStepVisited] = React.useState(false);
  const [includeOrphaned, setIncludeOrphaned] = React.useState(true);
  const [forceFreshValidation, setForceFreshValidation] = React.useState(true);
  const [scanBudgetGiB, setScanBudgetGiB] = React.useState<CarvingOptions["scanBudgetGiB"]>(64);
  const [maxCarvedFiles, setMaxCarvedFiles] = React.useState<CarvingOptions["maxFiles"]>(16384);
  const [maxCarvedRetainedMiB, setMaxCarvedRetainedMiB] = React.useState<CarvingOptions["maxRetainedMiB"]>(512);
  const [maxCandidateReadMiBPerFormat, setMaxCandidateReadMiBPerFormat] =
    React.useState<CarvingOptions["maxCandidateReadMiBPerFormat"]>(1024);
  const [enablePngFragmentReconstruction, setEnablePngFragmentReconstruction] =
    React.useState(false);
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
  React.useEffect(() => {
    if (activeStep === 3) setCatalogStepVisited(true);
  }, [activeStep]);
  const searchActive = Boolean(recovery.searchQuery.trim());
  const allExtensionsSelected = areAllExtensionsSelected(recovery.availableExtensions, recovery.extensions);
  const visibleRoots = searchActive && !recovery.searchingCatalog && recovery.searchResult
    ? recovery.searchResult.results
    : recovery.catalog?.roots;
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
  const toggleCatalogFolder = React.useCallback((node: CatalogNode) => {
    void recovery.toggleFolder(node);
  }, [recovery.toggleFolder]);
  const previewCatalogFile = React.useCallback((node: CatalogNode) => {
    void recovery.previewFile(node);
  }, [recovery.previewFile]);
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
      enablePngFragmentReconstruction,
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
      {activeStep === 1 && <StorageStep recovery={recovery} language={language} t={t}
        onContinue={() => setActiveStep(2)} />}

      {activeStep === 2 && <ScanStep recovery={recovery} language={language} t={t}
        includeOrphaned={includeOrphaned} setIncludeOrphaned={setIncludeOrphaned}
        forceFreshValidation={forceFreshValidation} setForceFreshValidation={setForceFreshValidation}
        scanBudgetGiB={scanBudgetGiB} setScanBudgetGiB={setScanBudgetGiB}
        maxCarvedFiles={maxCarvedFiles} setMaxCarvedFiles={setMaxCarvedFiles}
        maxCarvedRetainedMiB={maxCarvedRetainedMiB} setMaxCarvedRetainedMiB={setMaxCarvedRetainedMiB}
        maxCandidateReadMiBPerFormat={maxCandidateReadMiBPerFormat}
        setMaxCandidateReadMiBPerFormat={setMaxCandidateReadMiBPerFormat}
        enablePngFragmentReconstruction={enablePngFragmentReconstruction}
        setEnablePngFragmentReconstruction={setEnablePngFragmentReconstruction}
        onBack={() => setActiveStep(1)} onStart={() => void runCatalogBuild()} />}

      <CatalogStep recovery={recovery} language={language} t={t} visited={catalogStepVisited}
        activeStep={activeStep} searchActive={searchActive} visibleRoots={visibleRoots}
        catalogSummary={catalogSummary}
        auditAvailable={Boolean(validation || contentCarving || lowConfidenceCarving
          || recycleBinRecovery || usnJournalEvidence || ntfsLogFileEvidence)}
        auditTriggerRef={auditTriggerRef}
        onToggleFolder={toggleCatalogFolder} onPreviewFile={previewCatalogFile}
        onOpenAudit={() => setAuditOpen(true)} onStepChange={setActiveStep} />

      {activeStep === 4 && <RecoveryStep recovery={recovery} language={language} t={t}
        onBack={() => setActiveStep(3)} />}
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
        {recovery.recoveryResult.candidateCount === 0 && <p role="status">{t("noRecoveryCandidates")}</p>}
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
          || (contentCarving.continuation?.stopReason !== undefined
            && contentCarving.continuation.stopReason !== "scope_complete")
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
            || (contentCarving.continuation?.stopReason !== undefined
              && contentCarving.continuation.stopReason !== "scope_complete")
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
          {contentCarving.rangePage && <p role="status">
            {t("trustedRangeSummary", {
              retained: contentCarving.rangePage.retainedRangeCount,
              observed: contentCarving.rangePage.observedRangeCount,
              pending: contentCarving.rangePage.pendingRangeCount,
            })}
            {!contentCarving.rangePage.scanScopeComplete
              || !contentCarving.rangePage.collectionScopeComplete
              ? ` ${t("trustedRangeIncomplete", { reason: contentCarving.stopReason ?? "unknown" })}`
              : ` ${t("trustedRangeComplete")}`}
          </p>}
          {contentCarving.continuation && <p role="status">
            {t("continuationSummary", {
              passes: contentCarving.continuation.passes,
              maximum: contentCarving.continuation.maxPasses,
              pending: contentCarving.continuation.pendingRangeCount,
              reason: contentCarving.continuation.stopReason,
            })}
          </p>}
        </section>}
        {contentCarving?.pngFragmentReconstruction && <section aria-label={t("pngReconstructionHeading")}>
          <h3>{t("pngReconstructionHeading")}</h3>
          <ValidationNotice role="status" $inconclusive={!contentCarving.pngFragmentReconstruction.signatureDiscoveryComplete
            || contentCarving.pngFragmentReconstruction.stopReason !== "search_exhausted"}>
            {t("pngReconstructionSummary", {
              signatures: contentCarving.pngFragmentReconstruction.signaturesExamined,
              total: contentCarving.pngFragmentReconstruction.signaturesSeen,
              candidates: contentCarving.pngFragmentReconstruction.candidatesFound,
              hypotheses: contentCarving.pngFragmentReconstruction.structuralHypotheses,
              combinations: contentCarving.pngFragmentReconstruction.combinationsEvaluated,
              bytes: contentCarving.pngFragmentReconstruction.bytesRead.toLocaleString(language),
              seconds: contentCarving.pngFragmentReconstruction.elapsedSeconds.toFixed(2),
              stop: contentCarving.pngFragmentReconstruction.stopReason,
            })}
          </ValidationNotice>
          <p>{t("pngReconstructionIntegrityNotice")}</p>
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
