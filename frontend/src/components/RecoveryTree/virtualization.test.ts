import { describe, expect, it } from "vitest";
import {
  getScrollTopForIndex,
  getVirtualWindow,
  TREE_MAX_SCROLL_HEIGHT,
} from "./virtualization";

describe("catalog virtual scrolling", () => {
  it("maps a nearly one-million-row catalog onto a browser-safe scroll track", () => {
    const itemCount = 985_663;
    const viewportHeight = 600;
    const scrollTop = TREE_MAX_SCROLL_HEIGHT - viewportHeight;

    const window = getVirtualWindow(itemCount, scrollTop, viewportHeight);

    expect(window.trackHeight).toBe(TREE_MAX_SCROLL_HEIGHT);
    expect(window.scale).toBeGreaterThan(1);
    expect(window.endIndex).toBe(itemCount);
    expect(window.startIndex).toBeGreaterThan(itemCount - 100);
  });

  it("keeps a requested keyboard focus index inside the virtual range", () => {
    const itemCount = 985_663;
    const lastIndex = itemCount - 1;
    const scrollTop = getScrollTopForIndex(lastIndex, itemCount, 600);

    const window = getVirtualWindow(itemCount, scrollTop, 600);

    expect(window.startIndex).toBeLessThanOrEqual(lastIndex);
    expect(window.endIndex).toBe(itemCount);
  });
});
