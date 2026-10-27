export interface TreeSelection {
  selectedIds: Set<string>;
  excludedIds: Set<string>;
}

export function updateTreeSelection(
  nodeId: string,
  checked: boolean,
  current: TreeSelection,
  parentIds: ReadonlyMap<string, string | null>,
  descendantsById: ReadonlyMap<string, readonly string[]>,
): TreeSelection {
  const selectedIds = new Set(current.selectedIds);
  const excludedIds = new Set(current.excludedIds);
  const ancestors: string[] = [];
  let parentId = parentIds.get(nodeId) ?? null;
  while (parentId !== null) {
    ancestors.push(parentId);
    parentId = parentIds.get(parentId) ?? null;
  }

  if (checked) {
    selectedIds.add(nodeId);
    excludedIds.delete(nodeId);
    ancestors.forEach((ancestorId) => excludedIds.delete(ancestorId));
    return { selectedIds, excludedIds };
  }

  if (ancestors.some((ancestorId) => selectedIds.has(ancestorId))) {
    excludedIds.add(nodeId);
    return { selectedIds, excludedIds };
  }

  selectedIds.delete(nodeId);
  excludedIds.delete(nodeId);
  const pending = [...(descendantsById.get(nodeId) ?? [])];
  while (pending.length) {
    const descendantId = pending.pop()!;
    selectedIds.delete(descendantId);
    excludedIds.delete(descendantId);
    pending.push(...(descendantsById.get(descendantId) ?? []));
  }
  return { selectedIds, excludedIds };
}

export function isTreeNodeSelected(
  nodeId: string,
  selection: TreeSelection,
  parentIds: ReadonlyMap<string, string | null>,
): boolean {
  if (selection.excludedIds.has(nodeId)) return false;
  if (selection.selectedIds.has(nodeId)) return true;
  let parentId = parentIds.get(nodeId) ?? null;
  while (parentId !== null) {
    if (selection.excludedIds.has(parentId)) return false;
    if (selection.selectedIds.has(parentId)) return true;
    parentId = parentIds.get(parentId) ?? null;
  }
  return false;
}
