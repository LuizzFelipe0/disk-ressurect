import { describe, expect, it } from "vitest";
import { translate, translateError, translateStatus } from "./translations";

describe("application translations", () => {
  it("provides the main recovery actions in every language exported by the shared toggle", () => {
    const languages = ["pt-BR", "en-US", "es-ES", "fr-FR", "zh-CN"] as const;
    for (const language of languages) {
      if (language !== "en-US") expect(translate(language, "recoverSelected")).not.toBe("Recover selected");
      expect(translate(language, "sourceDisk")).toBeTruthy();
      expect(translate(language, "loadingContents", { name: "Photos" })).toContain("Photos");
    }
  });

  it("translates known workflow statuses and keeps dynamic backend errors intact", () => {
    expect(translateStatus("Scanning partitions…", "pt-BR")).toBe("Verificando partições…");
    expect(translateStatus("Scanning partitions…", "zh-CN")).toBe("正在扫描分区…");
    expect(translateError("Choose a destination folder to continue.", "fr-FR")).toBe("Choisissez un dossier de destination pour continuer.");
    expect(translateError("OSError: device is unavailable", "es-ES")).toBe("OSError: device is unavailable");
  });
});
