import { describe, expect, it } from "vitest";

const rendererSources = import.meta.glob([
  "../app/**/*.{ts,tsx}", "../components/**/*.{ts,tsx}",
  "../features/**/*.{ts,tsx}", "../hooks/**/*.{ts,tsx}",
], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const sourceEntries = Object.entries(rendererSources).filter(([path]) => !path.includes(".test."));

describe("frontend architecture boundaries", () => {
  it("keeps Electron bridge access behind the recovery service", () => {
    const violations = sourceEntries
      .filter(([, source]) => /window\.diskResurrect|ipcRenderer|from ["']electron["']/.test(source));
    expect(violations).toEqual([]);
  });

  it("keeps feature modules independent from other feature modules", () => {
    const featureEntries = sourceEntries.filter(([path]) => path.startsWith("../features/"));
    const violations = featureEntries.filter(([path, source]) => {
      const currentFeature = path.split("/")[2];
      return [...source.matchAll(/from ["'][^"']*features\/(storage|scan|catalog|recovery)\//g)]
        .some((match) => match[1] !== currentFeature);
    });
    expect(violations).toEqual([]);
  });
});
