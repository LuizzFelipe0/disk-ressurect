import { describe, expect, it } from "vitest";
import {
  areAllExtensionsSelected,
  getExtensionSelectionUpdates,
  getMinimumSizeKb,
} from "./filterSelection";

describe("filter selection helpers", () => {
  it("marks all available extensions selected only when the non-empty set is complete", () => {
    expect(areAllExtensionsSelected([], [])).toBe(false);
    expect(areAllExtensionsSelected([".jpg", ".png"], [".jpg"])).toBe(false);
    expect(areAllExtensionsSelected([".jpg", ".png"], [".jpg", ".png"])).toBe(true);
  });

  it("maps dropdown values to updates for every available extension", () => {
    expect(getExtensionSelectionUpdates([".jpg", ".png"], [".png"])).toEqual([
      { extension: ".jpg", checked: false },
      { extension: ".png", checked: true },
    ]);
  });

  it("uses the latest selected size and resets to any size when cleared", () => {
    expect(getMinimumSizeKb(["5", "25"])).toBe(25);
    expect(getMinimumSizeKb([])).toBe(0);
  });
});
