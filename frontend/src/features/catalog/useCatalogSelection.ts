import { useCallback, useMemo, useState } from "react";
import type { CatalogInfo } from "../../types/recovery";
import { isTreeNodeSelected, updateTreeSelection } from "../../utils/selection";

export function useCatalogSelection(
  catalog: CatalogInfo | null,
  childrenById: Record<string, { id: string }[]>,
  parentById: Map<string, string | null>,
) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set());
  const descendantsById = useMemo(() => {
    const descendants = new Map<string, string[]>();
    Object.entries(childrenById).forEach(([id, children]) => descendants.set(id, children.map((child) => child.id)));
    return descendants;
  }, [childrenById]);

  const toggleSelection = useCallback((nodeId: string, checked: boolean) => {
    const next = updateTreeSelection(nodeId, checked,
      { selectedIds, excludedIds }, parentById, descendantsById);
    setSelectedIds(next.selectedIds);
    setExcludedIds(next.excludedIds);
  }, [selectedIds, excludedIds, parentById, descendantsById]);

  const isSelected = useCallback((nodeId: string) =>
    isTreeNodeSelected(nodeId, { selectedIds, excludedIds }, parentById),
  [selectedIds, excludedIds, parentById]);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(catalog?.roots.map((node) => node.id) ?? []));
    setExcludedIds(new Set());
  }, [catalog]);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
    setExcludedIds(new Set());
  }, []);

  return { selectedIds, excludedIds, toggleSelection, isSelected, selectAll, clearSelection };
}
