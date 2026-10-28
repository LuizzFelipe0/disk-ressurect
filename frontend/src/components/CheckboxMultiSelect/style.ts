import styled from "styled-components";

export const MultiSelectContainer = styled.div`
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 220px;
  max-width: 380px;
`;

export const ControlLabel = styled.label`
  color: #586984;
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
  border: 1px solid #d9e0ea;
  border-radius: 8px;
  color: #23324a;
  background: #fff;
  text-align: left;
  cursor: pointer;

  &:focus-visible { border-color: #5291e4; outline: 3px solid rgba(72,139,225,.13); }
  &:disabled { color: #8793a6; background: #f7f9fc; cursor: not-allowed; }
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
  border: 1px solid #d9e0ea;
  border-radius: 9px;
  background: #fff;
  box-shadow: 0 10px 24px rgba(32,56,94,.16);
`;

export const DropdownOption = styled.label`
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 34px;
  padding: 6px 8px;
  border-radius: 6px;
  color: #354760;
  font-size: 12px;
  cursor: pointer;

  &:hover { background: #f4f8fe; }
  input { margin: 0; accent-color: #2879d5; cursor: pointer; }
`;
