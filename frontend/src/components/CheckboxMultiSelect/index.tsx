import React, { useEffect, useId, useRef, useState } from "react";
import {
  ControlLabel,
  Dropdown,
  DropdownOption,
  MultiSelectContainer,
  MultiSelectTrigger,
  TriggerText,
} from "./style";

export interface CheckboxMultiSelectOption {
  value: string;
  label: string;
}

export interface CheckboxMultiSelectProps {
  label: string;
  options: CheckboxMultiSelectOption[];
  selected: string[];
  disabled?: boolean;
  placeholder?: string;
  selectAllLabel?: string;
  onSelectionChange: (value: string, checked: boolean) => void;
}

export const CheckboxMultiSelect: React.FC<CheckboxMultiSelectProps> = ({
  label,
  options,
  selected,
  disabled = false,
  placeholder = "Select options",
  selectAllLabel,
  onSelectionChange,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!isOpen) return undefined;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (event.target instanceof Node && !containerRef.current?.contains(event.target)) setIsOpen(false);
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

  const summary = selected.length === 0
    ? placeholder
    : selected.length === options.length
      ? `All ${label.toLowerCase()} (${selected.length})`
      : selected.map((value) => options.find((option) => option.value === value)?.label ?? value).join(", ");
  const allOptionsSelected = options.length > 0 && options.every((option) => selected.includes(option.value));

  const handleSelectAll = (checked: boolean) => {
    options.forEach((option) => onSelectionChange(option.value, checked));
  };

  return (
    <MultiSelectContainer ref={containerRef}>
      <ControlLabel id={`${menuId}-label`}>{label}</ControlLabel>
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
        <Dropdown id={menuId} role="group" aria-label={`Available ${label.toLowerCase()}`}>
          {selectAllLabel && (
            <DropdownOption>
              <input
                type="checkbox"
                checked={allOptionsSelected}
                aria-label={selectAllLabel}
                onChange={(event) => handleSelectAll(event.target.checked)}
              />
              <span>{selectAllLabel}</span>
            </DropdownOption>
          )}
          {options.map((option) => (
            <DropdownOption key={option.value}>
              <input
                type="checkbox"
                checked={selected.includes(option.value)}
                aria-label={option.label}
                onChange={(event) => onSelectionChange(option.value, event.target.checked)}
              />
              <span>{option.label}</span>
            </DropdownOption>
          ))}
        </Dropdown>
      )}
    </MultiSelectContainer>
  );
};
