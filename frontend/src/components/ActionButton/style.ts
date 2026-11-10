import styled, { css } from "styled-components";
import { brandColors } from "../../brandColors";

export const StyledButton = styled.button<{ $variant: "primary" | "success" | "secondary" }>`
  min-height: 38px;
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  transition: transform .12s, box-shadow .12s, opacity .12s;
  cursor: pointer;

  ${({ $variant }) => $variant === "primary"
    ? css`color: ${brandColors.ink}; background: ${brandColors.revive};`
    : $variant === "success"
      ? css`color: ${brandColors.ink}; background: ${brandColors.revive};`
      : css`color: ${brandColors.ink}; background: ${brandColors.surface}; border-color: ${brandColors.border};`}

  &:not(:disabled):hover { transform: translateY(-1px); box-shadow: 0 4px 11px rgba(11,11,12,.12); }
  &:disabled { cursor: not-allowed; opacity: .45; }
`;
