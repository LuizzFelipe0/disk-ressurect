// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DiskAuditOverlay } from "./index";

afterEach(cleanup);

describe("DiskAuditOverlay", () => {
  it("renders an accessible dialog and closes with its button", () => {
    const onClose = vi.fn();
    render(<DiskAuditOverlay id="audit-dialog" title="Disk audit details" closeLabel="Close" onClose={onClose}>
      <p>Audit results</p>
    </DiskAuditOverlay>);

    expect(screen.getByRole("dialog", { name: "Disk audit details" }).getAttribute("aria-modal")).toBe("true");
    expect(screen.getByText("Audit results")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape or backdrop interaction", () => {
    const onClose = vi.fn();
    render(<DiskAuditOverlay id="audit-dialog" title="Disk audit details" closeLabel="Close" onClose={onClose}>
      <p>Audit results</p>
    </DiskAuditOverlay>);

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    const backdrop = screen.getByRole("dialog").parentElement;
    if (!backdrop) throw new Error("Dialog backdrop was not rendered");
    fireEvent.mouseDown(backdrop);
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
