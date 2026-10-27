import React from "react";
import { StyledButton } from "./style";

export type ActionButtonVariant = "primary" | "success" | "secondary";

export interface ActionButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ActionButtonVariant;
}

export const ActionButton: React.FC<ActionButtonProps> = ({ variant = "secondary", ...props }) => (
  <StyledButton $variant={variant} {...props} />
);
