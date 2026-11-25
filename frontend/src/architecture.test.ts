import { describe, expect, it } from "vitest";

const rendererSources = import.meta.glob([
  "./components/**/*.{ts,tsx}", "./pages/**/*.{ts,tsx}", "./hooks/**/*.{ts,tsx}",
], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const sourceEntries = Object.entries(rendererSources).filter(([path]) => !path.includes(".test."));

describe("frontend architecture boundaries", () => {
  it("keeps Electron bridge access behind the recovery service", () => {
    const violations = sourceEntries
      .filter(([, source]) => /window\.diskResurrect|ipcRenderer|from ["']electron["']/.test(source));
    expect(violations).toEqual([]);
  });

  it("keeps page modules independent from other page modules", () => {
    const pageEntries = sourceEntries.filter(([path]) => path.startsWith("./pages/"));
    const violations = pageEntries.filter(([path, source]) => {
      const currentPage = path.split("/")[2];
      return [...source.matchAll(/from ["'][^"']*pages\/(HomePage|RecoveryPage)\//g)]
        .some((match) => match[1] !== currentPage);
    });
    expect(violations).toEqual([]);
  });
});
