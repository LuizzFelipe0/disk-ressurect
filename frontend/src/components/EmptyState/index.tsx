import React from "react";
import { EmptyStateContainer } from "./style";

export const EmptyState: React.FC<React.HTMLAttributes<HTMLDivElement>> = (props) => (
  <EmptyStateContainer {...props} />
);
