import { describe, expect, it } from "vitest";
import { translate, translateError, translateStatus } from "./translations";

describe("application translations", () => {
  it("provides the main recovery actions in every language exported by the shared toggle", () => {
    const languages = ["pt-BR", "en-US", "es-ES", "fr-FR", "zh-CN"] as const;
    for (const language of languages) {
      if (language !== "en-US") expect(translate(language, "recoverSelected")).not.toBe("Recover selected");
      expect(translate(language, "sourceDisk")).toBeTruthy();
      expect(translate(language, "includeOrphaned")).toBeTruthy();
      expect(translate(language, "orphanedEntriesCount", { count: 2 })).toContain("2");
      expect(translate(language, "loadingContents", { name: "Photos" })).toContain("Photos");
      for (const key of ["includeOrphaned", "orphanScanWarning", "orphanedDeleted", "partitionLabel", "catalogItems", "statusScanningOrphans"] as const) {
        expect(translate(language, key)).not.toMatch(/MFT|NTFS/i);
      }
    }
  });

  it("translates known workflow statuses and keeps dynamic backend errors intact", () => {
    expect(translateStatus("Scanning partitions…", "pt-BR")).toBe("Verificando partições…");
    expect(translateStatus("Scanning partitions…", "zh-CN")).toBe("正在扫描分区…");
    expect(translateStatus("Reading MFT metadata and searching for orphaned entries…", "pt-BR"))
      .toBe("Buscando arquivos fora da lista normal…");
    expect(translateStatus("Reading MFT records", "en-US")).toBe("Reading catalog items…");
    expect(translateStatus("Catalog ready: 12 MFT records.", "pt-BR")).toBe("Catálogo pronto: 12 itens.");
    expect(translateError("Choose a destination folder to continue.", "fr-FR")).toBe("Choisissez un dossier de destination pour continuer.");
    expect(translateError("OSError: device is unavailable", "es-ES")).toBe("OSError: device is unavailable");
  });
});
