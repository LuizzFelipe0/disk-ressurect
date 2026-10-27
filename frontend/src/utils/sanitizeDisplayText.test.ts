import { describe, expect, it } from "vitest";
import { sanitizeDisplayText } from "./sanitizeDisplayText";

describe("sanitizeDisplayText", () => {
  it("removes replacement and control characters from option labels", () => {
    expect(sanitizeDisplayText("Disk � 0\u0000 · NTFS �"))
      .toBe("Disk 0 · NTFS");
  });

  it("preserves valid Unicode characters and trims excess whitespace", () => {
    expect(sanitizeDisplayText("  São   Paulo · NTFS  "))
      .toBe("São Paulo · NTFS");
  });
});
