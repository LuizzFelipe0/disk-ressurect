export interface ExtensionSelectionUpdate {
  extension: string;
  checked: boolean;
}

export const getExtensionSelectionUpdates = (
  availableExtensions: string[],
  selectedExtensions: string[],
): ExtensionSelectionUpdate[] => availableExtensions.map((extension) => ({
  extension,
  checked: selectedExtensions.includes(extension),
}));

export const areAllExtensionsSelected = (availableExtensions: string[], selectedExtensions: string[]) =>
  availableExtensions.length > 0
  && availableExtensions.every((extension) => selectedExtensions.includes(extension));

export const getMinimumSizeKb = (selectedValues: string[]) => Number(selectedValues.at(-1) ?? 0);
