import React from "react";
import { Button } from "belagio-styles-lib";
import { DiskAuditOverlay } from "../../components/DiskAuditOverlay";
import { useAppLanguage } from "../../app/language";
import { translate } from "../../i18n/translations";
import type { CatalogInfo, ContentCarvingSummary } from "../../types/recovery";

interface DiskAuditReportProps {
  catalog: CatalogInfo;
}

export const DiskAuditReport: React.FC<DiskAuditReportProps> = ({ catalog }) => {
  const { language } = useAppLanguage();
  const [open, setOpen] = React.useState(false);
  const triggerRef = React.useRef<HTMLSpanElement>(null);
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) =>
    translate(language, key, values);
  const validation = catalog.diskValidation;
  const carving = catalog.contentCarving;
  const lowConfidence = catalog.lowConfidenceCarving;
  const lowConfidenceTiers = lowConfidence ? [
    { key: "bitmapUnobserved" as const, summary: lowConfidence.bitmapUnobserved },
    { key: "possiblyReused" as const, summary: lowConfidence.possiblyReused },
  ] : [];
  const coverage = validation?.sizeBytes
    ? Math.min(100, Math.floor(validation.bytesRead * 100 / validation.sizeBytes)) : 0;

  React.useEffect(() => {
    if (!open) triggerRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [open]);

  const formatLabel = (family: string) => family === ".office_zip"
    ? "OOXML (.docx, .docm, .xlsx, .xlsm)" : family;
  const reachedFormatLimit = (summary: ContentCarvingSummary) => [
    summary.candidateLimitReachedByExtension,
    summary.fileSizeLimitReachedByExtension,
    summary.decodedDataLimitReachedByExtension,
  ].some((flags) => Object.values(flags ?? {}).some(Boolean));
  const reachedAnyLimit = (summary: ContentCarvingSummary) => summary.rangeCollectionTruncated
    || summary.scanLimitReached || summary.candidateLimitReached || summary.fileCountLimitReached
    || summary.retainedBytesLimitReached || reachedFormatLimit(summary);
  const renderFormats = (summary: ContentCarvingSummary) => {
    const names = Array.from(new Set([
      ...(summary.formatsAttempted ?? []),
      ...Object.keys(summary.filesFoundByExtension ?? {}),
      ...Object.keys(summary.candidatesExaminedByExtension ?? {}),
      ...Object.keys(summary.candidateBytesReadByExtension ?? {}),
    ])).sort();
    if (!names.length) return <p>{t("carvingDiagnosticsUnavailable")}</p>;
    return <ul>{names.map((extension) => {
      const limits = [
        summary.candidateLimitReachedByExtension?.[extension] && t("candidateReadLimit"),
        summary.fileSizeLimitReachedByExtension?.[extension] && t("fileSizeLimit"),
        summary.decodedDataLimitReachedByExtension?.[extension] && t("decodedDataLimit"),
      ].filter(Boolean).join(", ");
      return <li key={extension}>
        {t("carvingFormatStats", {
          extension: formatLabel(extension),
          files: summary.filesFoundByExtension?.[extension] ?? 0,
          candidates: summary.candidatesExaminedByExtension?.[extension] ?? 0,
          bytes: (summary.candidateBytesReadByExtension?.[extension] ?? 0).toLocaleString(language),
        })}{limits && ` ${t("carvingLimitsReached", { limits })}`}
      </li>;
    })}</ul>;
  };

  const hasEvidence = Boolean(validation || carving || lowConfidence || catalog.recycleBinRecovery
    || catalog.usnJournalEvidence || catalog.ntfsLogFileEvidence);
  if (!hasEvidence) return null;

  return <>
    <span ref={triggerRef}><Button className="brand-button--ghost" variant="ghost" size="md"
      onClick={() => setOpen(true)}>{t("diskAuditDetails")}</Button></span>
    {open && <DiskAuditOverlay id="disk-audit-overlay" title={t("diskAuditDetails")}
      closeLabel={t("closeDetails")} onClose={() => setOpen(false)}>
      {validation && <p role="status">
        {validation.coverageStatus === "unavailable"
          ? t("validationUnavailable", { error: validation.validationError ?? "Unknown error" })
          : validation.evidenceFreshness === "cached_snapshot"
            ? t("validationCachedSnapshot", { scannedAt: validation.evidenceScannedAt ?? "unknown", coverage })
            : validation.assessment === "inconclusive"
              ? t("validationInconclusive", {
                coverage, errors: validation.readErrorCount, deleted: validation.deletedMftRecordCount,
                orphans: validation.orphanedFileRecordCount, inconsistent: validation.inconsistentMftRecordCount ?? 0,
              })
              : t("validationEvidence", {
                coverage, partitions: validation.partitionCount, ntfs: validation.ntfsVolumeCount,
                deleted: validation.deletedMftRecordCount, orphans: validation.orphanedFileRecordCount,
                inconsistent: validation.inconsistentMftRecordCount ?? 0,
              })}
      </p>}
      <p>{t("catalogRecoveryInterpretation", {
        items: catalog.recordCount.toLocaleString(language), types: catalog.availableExtensions.length.toLocaleString(language),
      })}</p>
      {validation?.orphanRecordsByAllocationStatus && <>
        <p>{t("orphanRecordAllocationSummary", validation.orphanRecordsByAllocationStatus)}</p>
        <p>{t("allocationRecoveryInterpretation")}</p>
      </>}
      {validation && <p>{t("orphanRecoveryInterpretation")}</p>}
      {carving && <>
        <p role="status">{t("contentCarvingResult", {
          files: carving.filesFound, bytes: carving.bytesScanned.toLocaleString(language),
          candidateBytes: carving.candidateBytesRead.toLocaleString(language),
        })}{reachedAnyLimit(carving) && ` ${t("contentCarvingLimited")}`}</p>
        <section aria-label={t("carvingDiagnosticsHeading")}>
          <h2>{t("carvingDiagnosticsHeading")}</h2>
          {carving.candidateReadCapBytes !== undefined && <p>{t("carvingCandidateBudget", {
            perFormat: carving.candidateReadCapBytesPerFormat?.toLocaleString(language) ?? "—",
            aggregate: carving.candidateReadCapBytes.toLocaleString(language),
          })}</p>}
          {carving.scanByteCap !== undefined && <p>{t("carvingSizeBudget", {
            scan: carving.scanByteCap.toLocaleString(language), maxFile: carving.maxFileBytes?.toLocaleString(language) ?? "—",
            decoded: carving.maxDecodedPngBytes?.toLocaleString(language) ?? "—",
            retained: carving.retainedBytesCap?.toLocaleString(language) ?? "—", files: carving.fileCountCap ?? "—",
          })}</p>}
          {carving.formatsAttempted && <p>{t("carvingFormatsAttempted", { formats: carving.formatsAttempted.map(formatLabel).join(", ") || "—" })}</p>}
          {carving.validationScope && <p>{t("carvingValidationScope", {
            scope: carving.validationScope === "contiguous_structure_and_signature" ? t("carvingScopeContiguous") : carving.validationScope,
          })}</p>}
          {renderFormats(carving)}
        </section>
      </>}
      {catalog.recycleBinRecovery && <section aria-label={t("recycleBinRecoveryHeading")}>
        <h2>{t("recycleBinRecoveryHeading")}</h2><p>{t("recycleBinRecoverySummary", {
          aliases: catalog.recycleBinRecovery.aliasesAdded, paired: catalog.recycleBinRecovery.pairedCount,
          indexes: catalog.recycleBinRecovery.indexCount, missing: catalog.recycleBinRecovery.missingContentCount,
          mismatched: catalog.recycleBinRecovery.metadataMismatchCount,
        })}</p><p>{t("recycleBinRecoveryInterpretation")}</p>
      </section>}
      {catalog.usnJournalEvidence && <section aria-label={t("usnJournalEvidenceHeading")}>
        <h2>{t("usnJournalEvidenceHeading")}</h2><p>{t("usnJournalEvidenceSummary", {
          journals: catalog.usnJournalEvidence.journalCount, streams: catalog.usnJournalEvidence.streamCount,
          records: catalog.usnJournalEvidence.parsedRecords, deleted: catalog.usnJournalEvidence.deletedEvents,
          bytes: catalog.usnJournalEvidence.bytesRead.toLocaleString(language),
        })}{catalog.usnJournalEvidence.limitReached && ` ${t("usnJournalLimitReached")}`}
        {catalog.usnJournalEvidence.correlationLimitReached && ` ${t("usnMftCorrelationLimitReached")}`}</p>
        <p>{t("usnMftCorrelationSummary", {
          matched: catalog.usnJournalEvidence.matchedMftRecords ?? 0,
          deleted: catalog.usnJournalEvidence.matchedDeletedMftRecords ?? 0,
          validated: catalog.usnJournalEvidence.signatureMatchedRecords ?? 0,
          aliases: catalog.usnJournalEvidence.aliasesAdded ?? 0,
          stale: catalog.usnJournalEvidence.staleReferences ?? 0,
          missing: catalog.usnJournalEvidence.unmatchedReferences ?? 0,
        })}</p><p>{t("usnJournalEvidenceInterpretation")}</p>
      </section>}
      {catalog.ntfsLogFileEvidence && <section aria-label={t("ntfsLogFileEvidenceHeading")}>
        <h2>{t("ntfsLogFileEvidenceHeading")}</h2><p>{t("ntfsLogFileEvidenceSummary", {
          pages: catalog.ntfsLogFileEvidence.pagesExamined.toLocaleString(language),
          restart: catalog.ntfsLogFileEvidence.restartPages.toLocaleString(language),
          records: catalog.ntfsLogFileEvidence.recordPages.toLocaleString(language),
          bytes: catalog.ntfsLogFileEvidence.bytesRead.toLocaleString(language),
          lsns: catalog.ntfsLogFileEvidence.currentLsns.join(", ") || "—",
          errors: catalog.ntfsLogFileEvidence.errorCount.toLocaleString(language),
        })}{catalog.ntfsLogFileEvidence.limitReached && ` ${t("ntfsLogFileEvidenceLimitReached")}`}</p>
        <p>{t("ntfsLogFileEvidenceInterpretation")}</p>
      </section>}
      {lowConfidenceTiers.length > 0 && <>
        <p>{t("lowConfidenceRecoveryInterpretation")}</p>
        {lowConfidenceTiers.map(({ key, summary }) => <section key={key}>
          <h2>{t(key)}</h2><p>{t("lowConfidenceTierResult", {
            confidence: t("lowConfidenceLabel"), files: summary.filesFound, items: summary.catalogItemsAdded,
            bytes: summary.bytesScanned.toLocaleString(language), candidateBytes: summary.candidateBytesRead.toLocaleString(language),
          })}{reachedAnyLimit(summary) && ` ${t("contentCarvingLimited")}`}</p>
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
          {summary.rangeCollectionCapBytes !== undefined && <p>{t("lowConfidenceRangeSummary", {
            retained: summary.rangeBytesRetained?.toLocaleString(language) ?? "—",
            cap: summary.rangeCollectionCapBytes.toLocaleString(language),
          })}</p>}
          {summary.formatsAttempted && <p>{t("carvingFormatsAttempted", { formats: summary.formatsAttempted.join(", ") || "—" })}</p>}
          {renderFormats(summary)}</section>)}
      </>}
    </DiskAuditOverlay>}
  </>;
};
