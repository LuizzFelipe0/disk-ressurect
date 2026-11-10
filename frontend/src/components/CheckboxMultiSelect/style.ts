import styled from "styled-components";
import { brandColors } from "../../brandColors";

export const MultiSelectContainer = styled.div`
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 220px;
  max-width: 380px;
`;

export const ControlLabel = styled.label`
  color: ${brandColors.textSecondary};
  font-size: 12px;
  font-weight: 650;
`;

export const MultiSelectTrigger = styled.button`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  height: 38px;
  min-height: 38px;
  padding: 0 11px;
  border: 1px solid ${brandColors.border};
  border-radius: 8px;
  color: ${brandColors.ink};
  background: ${brandColors.surface};
  text-align: left;
  cursor: pointer;

  &:focus-visible { border-color: ${brandColors.revive}; outline: 3px solid rgba(182,242,60,.24); }
  &:disabled { color: ${brandColors.disabled}; background: ${brandColors.surfaceMuted}; cursor: not-allowed; }
`;

export const TriggerText = styled.span`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

export const Dropdown = styled.div`
  position: absolute;
  z-index: 20;
  top: calc(100% + 5px);
  left: 0;
  width: 100%;
  max-height: 260px;
  overflow-y: auto;
  padding: 5px;
  border: 1px solid ${brandColors.border};
  border-radius: 9px;
  background: ${brandColors.surface};
  box-shadow: 0 10px 24px rgba(11,11,12,.12);
`;

export const DropdownOption = styled.label`
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 34px;
  padding: 6px 8px;
  border-radius: 6px;
  color: ${brandColors.ink};
  font-size: 12px;
  cursor: pointer;

  &:hover { background: ${brandColors.surfaceMuted}; }
  input { margin: 0; accent-color: ${brandColors.revive}; cursor: pointer; }
`;
