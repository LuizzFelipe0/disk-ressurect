import styled, { css } from "styled-components";

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
    ? css`color: #fff; background: #2879d5;`
    : $variant === "success"
      ? css`color: #fff; background: #19a777;`
      : css`color: #35597f; background: #f7f9fc; border-color: #dce4ee;`}

  &:not(:disabled):hover { transform: translateY(-1px); box-shadow: 0 4px 11px rgba(33,70,120,.14); }
  &:disabled { cursor: not-allowed; opacity: .45; }
`;
