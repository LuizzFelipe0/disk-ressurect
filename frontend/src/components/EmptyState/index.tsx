import React from "react";
import { EmptyAction, EmptyCopy, EmptyStateContainer, EmptyTitle, EmptyVisual } from "./style";

export interface EmptyStateProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  title?: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  icon,
  action,
  children,
  role = "status",
  "aria-live": ariaLive = "polite",
  ...props
}) => (
  <EmptyStateContainer role={role} aria-live={ariaLive} {...props}>
    <EmptyVisual aria-hidden="true">{icon ?? "⌕"}</EmptyVisual>
    <EmptyCopy>
      <EmptyTitle>{title ?? children}</EmptyTitle>
      {description && <p>{description}</p>}
    </EmptyCopy>
    {action && <EmptyAction>{action}</EmptyAction>}
  </EmptyStateContainer>
);
