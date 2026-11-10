// @vitest-environment jsdom
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ErrorNotice } from "./index";

afterEach(cleanup);

describe("ErrorNotice", () => {
  it("announces errors assertively", () => {
    render(<ErrorNotice title="Recovery failed">The disk could not be read.</ErrorNotice>);

    expect(screen.getByRole("alert").textContent).toContain("Recovery failed");
    expect(screen.getByRole("alert").getAttribute("aria-live")).toBe("assertive");
  });

  it("announces warnings politely", () => {
    render(<ErrorNotice tone="warning">Administrator permission is required.</ErrorNotice>);

    expect(screen.getByRole("status").textContent).toContain("Administrator permission is required.");
    expect(screen.getByRole("status").getAttribute("aria-live")).toBe("polite");
  });
});
