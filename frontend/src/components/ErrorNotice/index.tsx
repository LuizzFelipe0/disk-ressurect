import React from "react";
import { Notice } from "./style";

interface ErrorNoticeProps extends React.HTMLAttributes<HTMLDivElement> {
  spaced?: boolean;
}

export const ErrorNotice: React.FC<ErrorNoticeProps> = ({ spaced = false, ...props }) => (
  <Notice $spaced={spaced} {...props} />
);
