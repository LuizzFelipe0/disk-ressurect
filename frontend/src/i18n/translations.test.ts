import { describe, expect, it } from "vitest";
import { translate, translateError, translateStatus } from "./translations";

describe("application translations", () => {
  it("provides the main recovery actions in every language exported by the shared toggle", () => {
    const languages = ["pt-BR", "en-US", "es-ES", "fr-FR", "zh-CN"] as const;
    for (const language of languages) {
      if (language !== "en-US") expect(translate(language, "recoverSelected")).not.toBe("Recover selected");
      expect(translate(language, "sourceDisk")).toBeTruthy();
      expect(translate(language, "openFilters")).toBeTruthy();
      expect(translate(language, "includeOrphaned")).toBeTruthy();
      expect(translate(language, "carvingScanBudget")).toBeTruthy();
      expect(translate(language, "carvingMaxFiles")).toBeTruthy();
      expect(translate(language, "carvingCandidateReadBudget")).toBeTruthy();
      expect(translate(language, "carvingCandidateRead1024")).toMatch(/1 GiB|1 Gio|1 GB|1 吉比字节/);
      expect(translate(language, "carvingRetainedBudget")).toBeTruthy();
      expect(translate(language, "usnMftCorrelationLimitReached")).toBeTruthy();
      expect(translate(language, "usnMftRecoverySourceLabel")).toBeTruthy();
      expect(translate(language, "recycleBinRecoveryHeading")).toBeTruthy();
      expect(translate(language, "usnJournalEvidenceHeading")).toBeTruthy();
      expect(translate(language, "ntfsLogFileEvidenceHeading")).toBeTruthy();
      expect(translate(language, "ntfsLogFileEvidenceInterpretation")).toBeTruthy();
      expect(translate(language, "ntfsLogFileEvidenceHeading")).toBeTruthy();
      expect(translate(language, "recycleBinSourceLabel")).toBeTruthy();
      expect(translate(language, "orphanedEntriesCount", { count: 2 })).toContain("2");
      expect(translate(language, "loadingContents", { name: "Photos" })).toContain("Photos");
      for (const key of ["includeOrphaned", "orphanedDeleted", "partitionLabel", "catalogItems", "statusScanningOrphans"] as const) {
        expect(translate(language, key)).not.toMatch(/MFT|NTFS/i);
      }
      expect(translate(language, "orphanScanWarning")).toBeTruthy();
      expect(translate(language, "orphanScanWarning")).toMatch(/64 GiB|64 Gio/);
      expect(translate(language, "orphanRecordAllocationSummary", {
        free: 9910, allocated: 0, mixed: 2, unknown: 921,
      })).toContain("9910");
      expect(translate(language, "validationEvidence", {
        coverage: 100, partitions: 1, ntfs: 1, deleted: 0, orphans: 0,
      })).toBeTruthy();
      expect(translate(language, "validationCachedSnapshot", {
        scannedAt: "2026-11-23T12:00:00Z", coverage: 100,
      })).toContain("2026-11-23");
      expect(translate(language, "forceFreshValidation")).toBeTruthy();
    }
  });

  it("translates known workflow statuses and keeps dynamic backend errors intact", () => {
    expect(translateStatus("Scanning partitions…", "pt-BR")).toBe("Verificando partições…");
    expect(translateStatus("Scanning partitions…", "zh-CN")).toBe("正在扫描分区…");
    expect(translateStatus("Reading MFT metadata and searching for orphaned entries…", "pt-BR"))
      .toBe("Buscando arquivos fora da lista normal…");
    expect(translateStatus("Reading disk and scanning deleted MFT records | 15,921/500,104 bytes", "pt-BR"))
      .toBe("Lendo o disco e verificando registros MFT órfãos: 15,921/500,104 bytes");
    expect(translateStatus("Reading disk and scanning deleted MFT records | 15,921/500,104 bytes", "en-US"))
      .toBe("Reading the disk and checking orphan MFT records: 15,921/500,104 bytes");
    expect(translateStatus("Searching trusted free space for validated file candidates…", "pt-BR"))
      .toBe("Procurando candidatos validados no espaço livre confiável…");
    expect(translateStatus("Searching ranges with unobserved allocation bitmap for file candidates…", "fr-FR"))
      .toBe("Recherche de candidats dans les zones où la bitmap n’a pas été observée…");
    expect(translateStatus("Reading MFT records", "en-US")).toBe("Reading catalog items…");
    expect(translateStatus("Catalog ready: 12 MFT records.", "pt-BR")).toBe("Catálogo pronto: 12 itens.");
    expect(translateError("Choose a destination folder to continue.", "fr-FR")).toBe("Choisissez un dossier de destination pour continuer.");
    expect(translateError("OSError: device is unavailable", "es-ES")).toBe("OSError: device is unavailable");
  });
});
