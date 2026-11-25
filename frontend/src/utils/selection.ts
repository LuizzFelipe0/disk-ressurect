export interface TreeSelection {
  selectedIds: Set<string>;
  excludedIds: Set<string>;
}

type DescendantSource =
  | ReadonlyMap<string, readonly string[]>
  | Readonly<Record<string, readonly { id: string }[]>>;

export function updateTreeSelection(
  nodeId: string,
  checked: boolean,
  current: TreeSelection,
  parentIds: ReadonlyMap<string, string | null>,
  descendantsById: DescendantSource,
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
  const pending: string[] = [];
  appendDescendantIds(nodeId, descendantsById, pending);
  while (pending.length) {
    const descendantId = pending.pop()!;
    selectedIds.delete(descendantId);
    excludedIds.delete(descendantId);
    appendDescendantIds(descendantId, descendantsById, pending);
  }
  return { selectedIds, excludedIds };
}

function appendDescendantIds(nodeId: string, source: DescendantSource, pending: string[]) {
  if (isDescendantMap(source)) {
    pending.push(...(source.get(nodeId) ?? []));
    return;
  }
  (source[nodeId] ?? []).forEach((child) => pending.push(child.id));
}

function isDescendantMap(source: DescendantSource): source is ReadonlyMap<string, readonly string[]> {
  return typeof (source as ReadonlyMap<string, readonly string[]>).get === "function";
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
