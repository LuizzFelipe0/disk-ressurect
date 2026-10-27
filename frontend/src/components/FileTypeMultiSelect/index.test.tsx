// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FileTypeMultiSelect } from "./index";

afterEach(cleanup);

describe("FileTypeMultiSelect", () => {
  it("allows selecting multiple file types from a dropdown", () => {
    const onSelectionChange = vi.fn();
    render(
      <FileTypeMultiSelect
        options={[".jpg", ".png", ".pdf"]}
        selected={[".jpg"]}
        onSelectionChange={onSelectionChange}
      />,
    );

    const trigger = screen.getByRole("button", { name: "File types" });
    fireEvent.click(trigger);

    expect((screen.getByRole("checkbox", { name: ".jpg" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: ".png" }));

    expect(onSelectionChange).toHaveBeenCalledWith(".png", true);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
  });

  it("closes the options when Escape is pressed", () => {
    render(
      <FileTypeMultiSelect
        options={[".jpg"]}
        selected={[]}
        onSelectionChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "File types" }));
    expect(screen.queryByRole("group", { name: "Available file types" })).not.toBeNull();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("group", { name: "Available file types" })).toBeNull();
  });
});
