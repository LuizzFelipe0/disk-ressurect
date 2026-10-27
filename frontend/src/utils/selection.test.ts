import { describe, expect, it } from "vitest";
import { isTreeNodeSelected, updateTreeSelection } from "./selection";

const parents = new Map<string, string | null>([
  ["root", null], ["folder", "root"], ["photo", "folder"], ["document", "folder"],
]);
const descendants = new Map<string, string[]>([
  ["root", ["folder"]], ["folder", ["photo", "document"]], ["photo", []], ["document", []],
]);

describe("hierarchical recovery selection", () => {
  it("selects a folder and recognizes its descendants as selected", () => {
    const selected = updateTreeSelection("folder", true,
      { selectedIds: new Set(), excludedIds: new Set() }, parents, descendants);

    expect(isTreeNodeSelected("photo", selected, parents)).toBe(true);
    expect(isTreeNodeSelected("document", selected, parents)).toBe(true);
  });

  it("excludes a child while its parent folder remains selected", () => {
    const folderSelected = { selectedIds: new Set(["folder"]), excludedIds: new Set<string>() };
    const selection = updateTreeSelection("photo", false, folderSelected, parents, descendants);

    expect(isTreeNodeSelected("photo", selection, parents)).toBe(false);
    expect(isTreeNodeSelected("document", selection, parents)).toBe(true);
  });

  it("removes exclusions when a nested item is explicitly selected again", () => {
    const excluded = { selectedIds: new Set(["folder"]), excludedIds: new Set(["photo"]) };
    const selection = updateTreeSelection("photo", true, excluded, parents, descendants);

    expect(selection.excludedIds.has("photo")).toBe(false);
    expect(isTreeNodeSelected("photo", selection, parents)).toBe(true);
  });
});
