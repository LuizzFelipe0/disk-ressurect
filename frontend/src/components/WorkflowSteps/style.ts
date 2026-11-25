import styled from "styled-components";
import { brandColors } from "../../brandColors";

export const StepsNavigation = styled.nav`
  width: min(1100px, 100%);
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 auto 22px;
  padding: 0 12px;
  box-sizing: border-box;
  @media (max-width: 620px) { gap: 5px; padding: 0; }
`;

export const StepButton = styled.button<{ $active: boolean; $complete: boolean }>`
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  border: 0;
  background: transparent;
  color: ${({ $active, $complete }) => $active || $complete ? brandColors.ink : brandColors.textTertiary};
  font-size: 12px;
  font-weight: ${({ $active }) => $active ? 700 : 500};
  white-space: nowrap;
  cursor: pointer;
  &:disabled { cursor: default; opacity: 1; }
  &:focus-visible { outline: 2px solid ${brandColors.revive}; outline-offset: 4px; border-radius: 4px; }
  @media (max-width: 620px) {
    flex: 1 1 0;
    flex-direction: column;
    gap: 5px;
    min-width: 0;
    white-space: normal;
    text-align: center;
    font-size: 10px;
  }
`;

export const StepNumber = styled.span<{ $active: boolean; $complete: boolean }>`
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  display: inline-grid;
  place-items: center;
  border: 1px solid ${({ $active, $complete }) => $active || $complete ? brandColors.revive : brandColors.border};
  border-radius: 50%;
  background: ${({ $active, $complete }) => $active || $complete ? brandColors.revive : "#fff"};
  color: ${brandColors.ink};
  font-size: 12px;
  font-weight: 700;
`;

export const StepConnector = styled.span`
  height: 1px;
  min-width: 12px;
  flex: 1;
  background: ${brandColors.border};
  @media (max-width: 620px) { min-width: 4px; align-self: flex-start; margin-top: 14px; }
`;
