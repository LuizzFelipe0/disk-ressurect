import React from "react";
import { Button, EmptyState } from "belagio-styles-lib";
import type { SiteLanguage } from "belagio-styles-lib";
import type { CatalogNode } from "../../types/recovery";
import { translate } from "../../i18n/translations";
import {
  ExpandButton,
  TreeContainer,
  TreeIndent,
  TreeItem,
  TreeLoading,
  TreeMeta,
  TreeName,
  TreeRow,
  TreeViewport,
  PreviewAction,
} from "./style";
import {
  getScrollTopForIndex,
  getVirtualWindow,
  TREE_FALLBACK_VIEWPORT_HEIGHT,
  TREE_ROW_HEIGHT,
} from "./virtualization";

export interface RecoveryTreeProps {
  roots: CatalogNode[];
  childrenById: Record<string, CatalogNode[]>;
  expandedFolderIds: Set<string>;
  loadingFolderIds: Set<string>;
  isSelected: (nodeId: string) => boolean;
  onToggleFolder: (node: CatalogNode) => void;
  onToggleSelection: (nodeId: string, checked: boolean) => void;
  onPreview: (node: CatalogNode) => void;
  language?: SiteLanguage;
}

interface FlattenedCatalog {
  nodes: CatalogNode[];
  depths?: number[];
  positions?: number[];
  siblingCounts?: number[];
}

type Translate = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) => string;

export const RecoveryTree = React.memo<RecoveryTreeProps>(({
  roots, childrenById, expandedFolderIds, loadingFolderIds, isSelected,
  onToggleFolder, onToggleSelection, onPreview, language = "en-US",
}) => {
  const t: Translate = (key, values) => translate(language, key, values);
  const viewportRef = React.useRef<HTMLDivElement>(null);
  const treeId = React.useId().replace(/:/g, "");
  const [scrollTop, setScrollTop] = React.useState(0);
  const [activeIndex, setActiveIndex] = React.useState(0);
  const pendingFocusIndex = React.useRef<number | null>(null);
  const flattened = React.useMemo(
    () => flattenVisibleCatalog(roots, childrenById, expandedFolderIds),
    [roots, childrenById, expandedFolderIds],
  );
  const viewportHeight = viewportRef.current?.clientHeight || TREE_FALLBACK_VIEWPORT_HEIGHT;
  const window = getVirtualWindow(flattened.nodes.length, scrollTop, viewportHeight);
  const getDepth = (index: number) => flattened.depths?.[index] ?? 0;
  const getPosition = (index: number) => flattened.positions?.[index] ?? index + 1;
  const getSiblingCount = (index: number) => flattened.siblingCounts?.[index] ?? roots.length;

  React.useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (viewport) {
      viewport.scrollTop = 0;
      setScrollTop(0);
    }
  }, [roots]);

  React.useLayoutEffect(() => {
    const index = pendingFocusIndex.current;
    if (index === null) return;
    const row = viewportRef.current?.querySelector<HTMLElement>(`[data-catalog-index="${index}"]`);
    const target = row?.querySelector<HTMLElement>("input:not(:disabled), button:not(:disabled)") ?? row;
    target?.focus();
    pendingFocusIndex.current = null;
  }, [activeIndex, window.startIndex, window.endIndex]);

  if (!flattened.nodes.length) return <EmptyState title={t("noFiles")} />;

  const focusIndex = (requestedIndex: number) => {
    const index = Math.max(0, Math.min(flattened.nodes.length - 1, requestedIndex));
    const viewport = viewportRef.current;
    if (!viewport) return;
    setActiveIndex(index);
    const targetScrollTop = getScrollTopForIndex(index, flattened.nodes.length, viewport.clientHeight);
    const firstVisibleIndex = Math.floor((scrollTop * window.scale) / TREE_ROW_HEIGHT);
    const lastVisibleIndex = Math.ceil(
      (scrollTop * window.scale + viewport.clientHeight * window.scale) / TREE_ROW_HEIGHT,
    );
    if (index < firstVisibleIndex || index >= lastVisibleIndex) {
      pendingFocusIndex.current = index;
      viewport.scrollTop = targetScrollTop;
      setScrollTop(targetScrollTop);
      return;
    }
    const row = viewport.querySelector<HTMLElement>(`[data-catalog-index="${index}"]`);
    (row?.querySelector<HTMLElement>("input:not(:disabled), button:not(:disabled)") ?? row)?.focus();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const row = (event.target as HTMLElement).closest<HTMLElement>("[data-catalog-index]");
    const rowIndex = row ? Number(row.dataset.catalogIndex) : activeIndex;
    let nextIndex: number | null = null;
    const pageRows = Math.max(1, Math.floor(viewportHeight / TREE_ROW_HEIGHT));

    if (event.key === "ArrowDown") nextIndex = rowIndex + 1;
    else if (event.key === "ArrowUp") nextIndex = rowIndex - 1;
    else if (event.key === "PageDown") nextIndex = rowIndex + pageRows;
    else if (event.key === "PageUp") nextIndex = rowIndex - pageRows;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = flattened.nodes.length - 1;
    else if (event.key === "ArrowRight") {
      const node = flattened.nodes[rowIndex];
      if (node?.isDirectory && node.hasChildren && !expandedFolderIds.has(node.id)) {
        event.preventDefault();
        onToggleFolder(node);
      } else if (rowIndex + 1 < flattened.nodes.length && getDepth(rowIndex + 1) > getDepth(rowIndex)) {
        nextIndex = rowIndex + 1;
      }
    } else if (event.key === "ArrowLeft") {
      const node = flattened.nodes[rowIndex];
      if (node?.isDirectory && expandedFolderIds.has(node.id)) {
        event.preventDefault();
        onToggleFolder(node);
      } else {
        for (let index = rowIndex - 1; index >= 0; index -= 1) {
          if (getDepth(index) < getDepth(rowIndex)) { nextIndex = index; break; }
        }
      }
    } else if ((event.key === " " || event.key === "Enter") && event.target === viewportRef.current) {
      const node = flattened.nodes[rowIndex];
      if (node && event.key === " ") {
        event.preventDefault();
        onToggleSelection(node.id, !isSelected(node.id));
      } else if (node?.isDirectory && node.hasChildren) {
        event.preventDefault();
        onToggleFolder(node);
      } else if (node && isPreviewable(node)) {
        event.preventDefault();
        onPreview(node);
      }
    } else if (event.key === "Tab" && row) {
      const controls = Array.from(row.querySelectorAll<HTMLElement>("input:not(:disabled), button:not(:disabled)"));
      const target = event.target as HTMLElement;
      const isBoundaryControl = event.shiftKey
        ? controls[0] === target && rowIndex === window.startIndex
        : controls[controls.length - 1] === target && rowIndex === window.endIndex - 1;
      const outsideBoundary = event.shiftKey ? rowIndex > 0 : rowIndex < flattened.nodes.length - 1;
      if (isBoundaryControl && outsideBoundary) {
        event.preventDefault();
        focusIndex(rowIndex + (event.shiftKey ? -1 : 1));
      }
    }

    if (nextIndex !== null) {
      event.preventDefault();
      focusIndex(nextIndex);
    }
  };

  const handleScroll = (event: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(event.currentTarget.scrollTop);
  };

  return (
    <TreeViewport
      ref={viewportRef}
      role="tree"
      aria-label={t("recoveryCatalog")}
      onScroll={handleScroll}
      onKeyDown={handleKeyDown}
      tabIndex={0}
    >
      <TreeContainer $height={window.trackHeight} role="presentation">
        {flattened.nodes.slice(window.startIndex, window.endIndex).map((node, offset) => {
          const index = window.startIndex + offset;
          const depth = getDepth(index);
          const expanded = expandedFolderIds.has(node.id);
          const loading = loadingFolderIds.has(node.id);
          const metadata = getMetadata(node, t);
          const logicalTop = index * TREE_ROW_HEIGHT;
          const top = scrollTop + logicalTop - window.logicalScrollTop;
          const indentWidth = Math.min(depth * 20, 240) + (node.isDirectory && node.hasChildren ? 24 : 20);

          return (
            <TreeItem
              key={node.id}
              id={`${treeId}-item-${index}`}
              data-catalog-index={index}
              role="treeitem"
              aria-level={depth + 1}
              aria-posinset={getPosition(index)}
              aria-setsize={getSiblingCount(index)}
              aria-expanded={node.isDirectory && node.hasChildren ? expanded : undefined}
              aria-busy={loading || undefined}
              tabIndex={-1}
              style={{ transform: `translateY(${top}px)` }}
            >
              <TreeRow>
                <TreeIndent style={{ width: indentWidth, flexBasis: indentWidth }}>
                  {node.isDirectory && node.hasChildren ? (
                    <ExpandButton
                      type="button"
                      aria-label={`${expanded ? t("collapse") : t("expand")} ${node.name}`}
                      aria-expanded={expanded}
                      aria-busy={loading}
                      disabled={loading}
                      onClick={() => onToggleFolder(node)}
                    >
                      {loading ? "…" : expanded ? "⌄" : "›"}
                    </ExpandButton>
                  ) : null}
                </TreeIndent>
                <input type="checkbox" checked={isSelected(node.id)} disabled={loading}
                  aria-label={`${t("select")} ${node.name}`} onChange={(change) => onToggleSelection(node.id, change.target.checked)} />
                <TreeName title={node.originalPath
                  ? `${node.path}\n${t("originalPathLabel")}: ${node.originalPath}${node.deletionTimestampUtc
                    ? `\n${t("deletedAtLabel")}: ${node.deletionTimestampUtc}` : ""}`
                  : node.path}>
                  <span aria-hidden="true">{node.isDirectory ? "▰" : "▱"}</span>
                  {node.name}
                </TreeName>
                <PreviewAction>
                  {!node.isDirectory && isPreviewable(node) && (
                    <Button className="brand-button--ghost" variant="ghost" size="sm" onClick={() => onPreview(node)}
                      aria-label={`${t("previewFile")} ${node.name}`}>{t("previewFile")}</Button>
                  )}
                </PreviewAction>
                <TreeMeta title={metadata.join(" · ")}>
                  {metadata.map((entry, metadataIndex) => (
                    <React.Fragment key={metadataIndex}>
                      {metadataIndex > 0 && " · "}
                      {node.dataExtentResolution === "inconclusive" && entry === t("fragmentedDataRunsInconclusive")
                        ? <span title={node.dataExtentResolutionReason ?? undefined}>{entry}</span>
                        : entry}
                    </React.Fragment>
                  ))}
                </TreeMeta>
                {loading && <TreeLoading role="status">{t("loadingContents", { name: node.name })}</TreeLoading>}
              </TreeRow>
            </TreeItem>
          );
        })}
      </TreeContainer>
    </TreeViewport>
  );
});

function flattenVisibleCatalog(
  roots: CatalogNode[],
  childrenById: Record<string, CatalogNode[]>,
  expandedFolderIds: Set<string>,
): FlattenedCatalog {
  if (!expandedFolderIds.size) return { nodes: roots };

  const nodes: CatalogNode[] = [];
  const depths: number[] = [];
  const positions: number[] = [];
  const siblingCounts: number[] = [];
  const pending: { siblings: CatalogNode[]; depth: number; index: number }[] = [
    { siblings: roots, depth: 0, index: 0 },
  ];
  while (pending.length) {
    const frame = pending[pending.length - 1];
    if (frame.index >= frame.siblings.length) {
      pending.pop();
      continue;
    }
    const position = frame.index++;
    const node = frame.siblings[position];
    nodes.push(node);
    depths.push(frame.depth);
    positions.push(position + 1);
    siblingCounts.push(frame.siblings.length);
    if (expandedFolderIds.has(node.id)) {
      const children = childrenById[node.id] ?? [];
      if (children.length) pending.push({ siblings: children, depth: frame.depth + 1, index: 0 });
    }
  }
  return { nodes, depths, positions, siblingCounts };
}
function isPreviewable(node: CatalogNode) {
  return [".jpg", ".jpeg", ".png", ".pdf"].includes(node.name.slice(node.name.lastIndexOf(".")).toLowerCase());
}

function getMetadata(node: CatalogNode, t: Translate) {
  const metadata = [node.recoverySource === "recycle_bin" ? t("recycleBinSourceLabel")
    : node.recoverySource === "usn_journal_mft" ? t("usnMftRecoverySourceLabel")
      : node.isContentCarved ? t("contentCarved") : node.isOrphaned ? t("orphanedDeleted")
        : node.isDeleted ? t("deleted") : node.isDirectory ? t("folder") : formatSize(node.sizeBytes)];
  if (node.contentValidation === "signature_match") metadata.push(t("signatureMatch"));
  if (node.contentValidation === "unavailable") metadata.push(t("signatureUnavailable"));
  if (node.dataExtentResolution === "resolved") {
    metadata.push(t("fragmentedDataRunsResolved", { count: node.dataExtentCount ?? 0 }));
  }
  if (node.dataExtentResolution === "inconclusive") metadata.push(t("fragmentedDataRunsInconclusive"));
  if (node.metadataConsistent === false) metadata.push(t("metadataWarning"));
  if (node.clusterAllocationStatus === "free") metadata.push(t("bitmapFree"));
  if (node.clusterAllocationStatus === "allocated") metadata.push(t("bitmapAllocated"));
  if (node.clusterAllocationStatus === "mixed") metadata.push(t("bitmapMixed"));
  if (node.clusterAllocationStatus === "partially_observed" || node.clusterAllocationStatus === "unavailable") {
    metadata.push(t("bitmapUnknown"));
  }
  if (node.clusterAllocationStatus === "bitmap_unobserved") metadata.push(t("bitmapUnobserved"));
  if (node.clusterAllocationStatus === "possibly_reused") metadata.push(t("possiblyReused"));
  return metadata;
}

function formatSize(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}
