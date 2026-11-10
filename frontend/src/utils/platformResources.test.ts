import { describe, expect, it } from "vitest";
import { getAppIconPath, getBundledBackendPath } from "./platformResources";

describe("platform resource paths", () => {
  it("uses the Windows backend executable name", () => {
    expect(getBundledBackendPath("win32", "C:/app/resources"))
      .toBe("C:\\app\\resources\\backend\\backend_orchestrator.exe");
  });

  it("uses the Linux backend executable name", () => {
    expect(getBundledBackendPath("linux", "/opt/disk-ressurect/resources"))
      .toBe("/opt/disk-ressurect/resources/backend/backend_orchestrator");
  });

  it("loads the Linux app icon from packaged resources", () => {
    expect(getAppIconPath("linux", true, "/opt/disk-ressurect/resources/app.asar", "/opt/disk-ressurect/resources"))
      .toBe("/opt/disk-ressurect/resources/disk-ressurect-logo.png");
  });

  it("loads the Linux source icon during development", () => {
    expect(getAppIconPath("linux", false, "/workspace/disk-ressurect/frontend", "/unused"))
      .toBe("/workspace/disk-ressurect/frontend/src/assets/disk-ressurect-logo.png");
  });

  it("keeps the Windows icon path for packaged and development apps", () => {
    expect(getAppIconPath("win32", true, "/app", "/app/resources"))
      .toBe("\\app\\resources\\disk-ressurect.ico");
    expect(getAppIconPath("win32", false, "/app", "/app/resources"))
      .toBe("\\app\\disk-ressurect.ico");
  });
});
