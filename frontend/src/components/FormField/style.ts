import styled from "styled-components";
import { brandColors } from "../../brandColors";

export const FieldLabel = styled.label<{ $grow: boolean }>`
  display: flex;
  flex: ${({ $grow }) => $grow ? "1" : "initial"};
  flex-direction: column;
  gap: 7px;
  min-width: 0;
  color: ${brandColors.textSecondary};
  font-size: 12px;
  font-weight: 650;

  select, input {
    width: 100%;
    min-height: 39px;
    padding: 8px 11px;
    color: ${brandColors.ink};
    background: ${brandColors.surface};
    border: 1px solid ${brandColors.border};
    border-radius: 8px;
    outline: none;
  }

  select:focus, input:focus { border-color: ${brandColors.revive}; box-shadow: 0 0 0 3px rgba(182,242,60,.24); }
`;
