import React, { useEffect, useId, useRef, useState } from "react";
import {
  ControlLabel,
  Dropdown,
  DropdownOption,
  MultiSelectContainer,
  MultiSelectTrigger,
  TriggerText,
} from "./style";

export interface FileTypeMultiSelectProps {
  options: string[];
  selected: string[];
  disabled?: boolean;
  onSelectionChange: (extension: string, checked: boolean) => void;
}

export const FileTypeMultiSelect: React.FC<FileTypeMultiSelectProps> = ({
  options,
  selected,
  disabled = false,
  onSelectionChange,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!isOpen) return undefined;

    const closeOnOutsideClick = (event: PointerEvent) => {
      if (event.target instanceof Node && !containerRef.current?.contains(event.target)) {
        setIsOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsOpen(false);
    };

    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isOpen]);

  const summary = options.length === 0
    ? "No file types available"
    : selected.length === 0
      ? "Select file types"
      : selected.length === options.length
        ? `All file types (${selected.length})`
        : selected.join(", ");

  return (
    <MultiSelectContainer ref={containerRef}>
      <ControlLabel id={`${menuId}-label`}>File types</ControlLabel>
      <MultiSelectTrigger
        type="button"
        aria-labelledby={`${menuId}-label`}
        aria-expanded={isOpen}
        aria-controls={menuId}
        disabled={disabled || options.length === 0}
        onClick={() => setIsOpen((current) => !current)}
      >
        <TriggerText title={summary}>{summary}</TriggerText>
        <span aria-hidden="true">⌄</span>
      </MultiSelectTrigger>
      {isOpen && (
        <Dropdown id={menuId} role="group" aria-label="Available file types">
          {options.map((extension) => (
            <DropdownOption key={extension}>
              <input
                type="checkbox"
                checked={selected.includes(extension)}
                onChange={(event) => onSelectionChange(extension, event.target.checked)}
              />
              <span>{extension}</span>
            </DropdownOption>
          ))}
        </Dropdown>
      )}
    </MultiSelectContainer>
  );
};
