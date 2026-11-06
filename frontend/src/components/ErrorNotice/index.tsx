import React from "react";
import { Notice } from "./style";

export type NoticeTone = "error" | "warning" | "info";

export interface ErrorNoticeProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  spaced?: boolean;
  tone?: NoticeTone;
  title?: React.ReactNode;
}

export const ErrorNotice: React.FC<ErrorNoticeProps> = ({
  spaced = false,
  tone = "error",
  title,
  children,
  role,
  ...props
}) => (
  <Notice
    $spaced={spaced}
    $tone={tone}
    role={role ?? (tone === "error" ? "alert" : "status")}
    aria-live={tone === "error" ? "assertive" : "polite"}
    {...props}
  >
    {title && <strong>{title}</strong>}
    {children && <span>{children}</span>}
  </Notice>
);
