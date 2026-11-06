import React from "react";
import type { CatalogNode } from "../../types/recovery";
import { EmptyState } from "../EmptyState";
import {
  ExpandButton,
  TreeChildren,
  TreeContainer,
  TreeIndent,
  TreeLoading,
  TreeMeta,
  TreeName,
  TreeRow,
} from "./style";

export interface RecoveryTreeProps {
  roots: CatalogNode[];
  childrenById: Record<string, CatalogNode[]>;
  expandedFolderIds: Set<string>;
  loadingFolderIds: Set<string>;
  isSelected: (nodeId: string) => boolean;
  onToggleFolder: (node: CatalogNode) => void;
  onToggleSelection: (nodeId: string, checked: boolean) => void;
}

export const RecoveryTree: React.FC<RecoveryTreeProps> = ({
  roots, childrenById, expandedFolderIds, loadingFolderIds, isSelected,
  onToggleFolder, onToggleSelection,
}) => {
  if (!roots.length) return <EmptyState title="No folders or files to display." icon="▱" />;

  const renderNode = (node: CatalogNode): React.ReactNode => (
    <li key={node.id}>
      <TreeRow>
        {node.isDirectory && node.hasChildren ? (
          <ExpandButton
            type="button"
            aria-label={`${expandedFolderIds.has(node.id) ? "Collapse" : "Expand"} ${node.name}`}
            aria-expanded={expandedFolderIds.has(node.id)}
            aria-busy={loadingFolderIds.has(node.id)}
            disabled={loadingFolderIds.has(node.id)}
            onClick={() => onToggleFolder(node)}
          >
            {loadingFolderIds.has(node.id) ? "…" : expandedFolderIds.has(node.id) ? "⌄" : "›"}
          </ExpandButton>
        ) : <TreeIndent />}
        <input type="checkbox" checked={isSelected(node.id)} disabled={loadingFolderIds.has(node.id)}
          aria-label={`Select ${node.name}`} onChange={(event) => onToggleSelection(node.id, event.target.checked)} />
        <TreeName title={node.path}>
          <span aria-hidden="true">{node.isDirectory ? "▰" : "▱"}</span>
          {node.name}
        </TreeName>
        <TreeMeta>{node.isDirectory ? "Folder" : formatSize(node.sizeBytes)}</TreeMeta>
      </TreeRow>
      {loadingFolderIds.has(node.id) && <TreeLoading role="status">Loading contents of {node.name}…</TreeLoading>}
      {expandedFolderIds.has(node.id) && (childrenById[node.id] ?? []).length > 0 && (
        <TreeChildren aria-label={`Contents of ${node.name}`}>
          {(childrenById[node.id] ?? []).map((child) => renderNode(child))}
        </TreeChildren>
      )}
    </li>
  );

  return <TreeContainer aria-label="Recovery catalog">{roots.map((node) => renderNode(node))}</TreeContainer>;
};

function formatSize(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}
