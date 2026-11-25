export const TREE_ROW_HEIGHT = 36;
export const TREE_OVERSCAN_ROWS = 10;
export const TREE_FALLBACK_VIEWPORT_HEIGHT = 600;
export const TREE_MAX_SCROLL_HEIGHT = 30_000_000;

export interface VirtualWindow {
  startIndex: number;
  endIndex: number;
  trackHeight: number;
  scale: number;
  logicalScrollTop: number;
}

export function getVirtualWindow(
  itemCount: number,
  scrollTop: number,
  viewportHeight: number,
): VirtualWindow {
  const safeCount = Math.max(0, itemCount);
  const safeViewportHeight = Math.max(1, viewportHeight || TREE_FALLBACK_VIEWPORT_HEIGHT);
  const logicalHeight = safeCount * TREE_ROW_HEIGHT;
  const trackHeight = Math.max(
    safeViewportHeight,
    Math.min(logicalHeight, TREE_MAX_SCROLL_HEIGHT),
  );
  const scale = logicalHeight > trackHeight ? logicalHeight / trackHeight : 1;
  const maxLogicalScrollTop = Math.max(0, logicalHeight - safeViewportHeight * scale);
  const logicalScrollTop = Math.min(Math.max(0, scrollTop) * scale, maxLogicalScrollTop);
  const firstVisibleIndex = Math.floor(logicalScrollTop / TREE_ROW_HEIGHT);
  const lastVisibleIndex = Math.ceil(
    (logicalScrollTop + safeViewportHeight * scale) / TREE_ROW_HEIGHT,
  );

  return {
    startIndex: Math.max(0, firstVisibleIndex - TREE_OVERSCAN_ROWS),
    endIndex: Math.min(safeCount, lastVisibleIndex + TREE_OVERSCAN_ROWS),
    trackHeight,
    scale,
    logicalScrollTop,
  };
}

export function getScrollTopForIndex(
  index: number,
  itemCount: number,
  viewportHeight: number,
): number {
  const safeViewportHeight = Math.max(1, viewportHeight || TREE_FALLBACK_VIEWPORT_HEIGHT);
  const logicalHeight = Math.max(0, itemCount) * TREE_ROW_HEIGHT;
  const trackHeight = Math.max(
    safeViewportHeight,
    Math.min(logicalHeight, TREE_MAX_SCROLL_HEIGHT),
  );
  const scale = logicalHeight > trackHeight ? logicalHeight / trackHeight : 1;
  const maxLogicalScrollTop = Math.max(0, logicalHeight - safeViewportHeight * scale);
  const targetLogicalScrollTop = Math.min(
    Math.max(0, index * TREE_ROW_HEIGHT - safeViewportHeight / 2),
    maxLogicalScrollTop,
  );
  return targetLogicalScrollTop / scale;
}
