// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CheckboxMultiSelect } from "./index";

afterEach(cleanup);

describe("CheckboxMultiSelect", () => {
  const options = [
    { value: ".jpg", label: ".jpg" },
    { value: ".pdf", label: ".pdf" },
  ];

  it("allows selecting multiple values from a checkbox menu", () => {
    const onSelectionChange = vi.fn();
    render(<CheckboxMultiSelect label="File types" options={options} selected={[".jpg"]}
      onSelectionChange={onSelectionChange} />);

    const trigger = screen.getByRole("button", { name: "File types" });
    fireEvent.click(trigger);
    expect((screen.getByRole("checkbox", { name: ".jpg" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: ".pdf" }));
    expect(onSelectionChange).toHaveBeenCalledWith(".pdf", true);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
  });

  it("closes the menu when Escape is pressed", () => {
    render(<CheckboxMultiSelect label="Minimum size" options={[
      { value: "0", label: "Any size" },
    ]} selected={["0"]} onSelectionChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Minimum size" }));
    expect(screen.queryByRole("group", { name: "Available minimum size" })).not.toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Available minimum size" })).toBeNull();
  });

  it("selects every option when All Types is checked", () => {
    const onSelectionChange = vi.fn();
    render(<CheckboxMultiSelect label="File types" selectAllLabel="All Types"
      options={options} selected={[]} onSelectionChange={onSelectionChange} />);

    fireEvent.click(screen.getByRole("button", { name: "File types" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "All Types" }));

    expect(onSelectionChange).toHaveBeenNthCalledWith(1, ".jpg", true);
    expect(onSelectionChange).toHaveBeenNthCalledWith(2, ".pdf", true);
  });

  it("clears every option when All Types is unchecked", () => {
    const onSelectionChange = vi.fn();
    render(<CheckboxMultiSelect label="File types" selectAllLabel="All Types"
      options={options} selected={[".jpg", ".pdf"]} onSelectionChange={onSelectionChange} />);

    fireEvent.click(screen.getByRole("button", { name: "File types" }));
    const allTypes = screen.getByRole("checkbox", { name: "All Types" }) as HTMLInputElement;
    expect(allTypes.checked).toBe(true);
    fireEvent.click(allTypes);

    expect(onSelectionChange).toHaveBeenNthCalledWith(1, ".jpg", false);
    expect(onSelectionChange).toHaveBeenNthCalledWith(2, ".pdf", false);
  });

  it("shows All Types unchecked when an individual type is removed", () => {
    const onSelectionChange = vi.fn();
    const view = render(<CheckboxMultiSelect label="File types" selectAllLabel="All Types"
      options={options} selected={[".jpg", ".pdf"]} onSelectionChange={onSelectionChange} />);

    fireEvent.click(screen.getByRole("button", { name: "File types" }));
    fireEvent.click(screen.getByRole("checkbox", { name: ".pdf" }));
    view.rerender(<CheckboxMultiSelect label="File types" selectAllLabel="All Types"
      options={options} selected={[".jpg"]} onSelectionChange={onSelectionChange} />);

    expect((screen.getByRole("checkbox", { name: "All Types" }) as HTMLInputElement).checked).toBe(false);
  });
});
