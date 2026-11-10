import React from "react";
import type { CatalogNode } from "../../types/recovery";
import type { SiteLanguage } from "belagio-styles-lib";
import { translate } from "../../i18n/translations";
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
  language?: SiteLanguage;
}

export const RecoveryTree: React.FC<RecoveryTreeProps> = ({
  roots, childrenById, expandedFolderIds, loadingFolderIds, isSelected,
  onToggleFolder, onToggleSelection, language = "en-US",
}) => {
  const t = (key: Parameters<typeof translate>[1], values?: Record<string, string | number>) => translate(language, key, values);
  if (!roots.length) return <EmptyState title={t("noFiles")} icon="▱" />;

  const renderNode = (node: CatalogNode): React.ReactNode => (
    <li key={node.id}>
      <TreeRow>
        {node.isDirectory && node.hasChildren ? (
          <ExpandButton
            type="button"
            aria-label={`${expandedFolderIds.has(node.id) ? t("collapse") : t("expand")} ${node.name}`}
            aria-expanded={expandedFolderIds.has(node.id)}
            aria-busy={loadingFolderIds.has(node.id)}
            disabled={loadingFolderIds.has(node.id)}
            onClick={() => onToggleFolder(node)}
          >
            {loadingFolderIds.has(node.id) ? "…" : expandedFolderIds.has(node.id) ? "⌄" : "›"}
          </ExpandButton>
        ) : <TreeIndent />}
        <input type="checkbox" checked={isSelected(node.id)} disabled={loadingFolderIds.has(node.id)}
          aria-label={`${t("select")} ${node.name}`} onChange={(event) => onToggleSelection(node.id, event.target.checked)} />
        <TreeName title={node.path}>
          <span aria-hidden="true">{node.isDirectory ? "▰" : "▱"}</span>
          {node.name}
        </TreeName>
        <TreeMeta>{node.isOrphaned ? t("orphanedDeleted") : node.isDeleted ? t("deleted") : node.isDirectory ? t("folder") : formatSize(node.sizeBytes)}</TreeMeta>
      </TreeRow>
      {loadingFolderIds.has(node.id) && <TreeLoading role="status">{t("loadingContents", { name: node.name })}</TreeLoading>}
      {expandedFolderIds.has(node.id) && (childrenById[node.id] ?? []).length > 0 && (
        <TreeChildren aria-label={t("contentsOf", { name: node.name })}>
          {(childrenById[node.id] ?? []).map((child) => renderNode(child))}
        </TreeChildren>
      )}
    </li>
  );

  return <TreeContainer aria-label={t("recoveryCatalog")}>{roots.map((node) => renderNode(node))}</TreeContainer>;
};

function formatSize(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}
