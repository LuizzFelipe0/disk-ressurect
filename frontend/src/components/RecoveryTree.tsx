import React from "react";
import type { CatalogNode } from "../types/recovery";
import { EmptyState, ExpandButton, TreeContainer, TreeMeta, TreeName, TreeRow } from "./ui";

interface RecoveryTreeProps {
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
  if (!roots.length) return <EmptyState>Nenhuma pasta ou arquivo para exibir.</EmptyState>;

  const renderNode = (node: CatalogNode, depth: number): React.ReactNode => (
    <React.Fragment key={node.id}>
      <TreeRow $depth={depth}>
        {node.isDirectory && node.hasChildren ? (
          <ExpandButton type="button" aria-label={expandedFolderIds.has(node.id) ? "Recolher pasta" : "Expandir pasta"}
            onClick={() => onToggleFolder(node)}>
            {loadingFolderIds.has(node.id) ? "…" : expandedFolderIds.has(node.id) ? "⌄" : "›"}
          </ExpandButton>
        ) : <span style={{ width: 20 }} />}
        <input type="checkbox" checked={isSelected(node.id)} disabled={loadingFolderIds.has(node.id)}
          aria-label={`Selecionar ${node.name}`} onChange={(event) => onToggleSelection(node.id, event.target.checked)} />
        <TreeName title={node.path}>{node.isDirectory ? "📁" : "📄"} {node.name}</TreeName>
        <TreeMeta>{node.isDirectory ? "Pasta" : formatSize(node.sizeBytes)}</TreeMeta>
      </TreeRow>
      {expandedFolderIds.has(node.id) && (childrenById[node.id] ?? []).map((child) => renderNode(child, depth + 1))}
    </React.Fragment>
  );

  return <TreeContainer role="tree">{roots.map((node) => renderNode(node, 0))}</TreeContainer>;
};

function formatSize(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}
