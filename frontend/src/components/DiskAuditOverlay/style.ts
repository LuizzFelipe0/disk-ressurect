import type React from "react";
import { brandColors } from "../../brandColors";

export const auditDialogStyles: Partial<Record<
  "backdrop" | "dialog" | "header" | "title" | "description" | "body" | "closeButton",
  React.CSSProperties
>> = {
  backdrop: { backgroundColor: "rgba(15, 23, 42, .58)", backdropFilter: "blur(3px)" },
  dialog: {
    display: "flex",
    width: "min(760px, 100%)",
    maxHeight: "min(82vh, 760px)",
    flexDirection: "column",
    overflow: "hidden",
    padding: 0,
    borderRadius: "14px",
    backgroundColor: brandColors.surface,
    color: brandColors.ink,
    boxShadow: "0 24px 80px rgba(15, 23, 42, .3)",
  },
  header: {
    flex: "0 0 auto",
    alignItems: "center",
    padding: "16px 20px",
    borderBottom: `1px solid ${brandColors.border}`,
  },
  title: { margin: 0, color: brandColors.ink, fontSize: "18px" },
  body: {
    display: "flex",
    minHeight: 0,
    flex: "1 1 auto",
    flexDirection: "column",
    gap: "12px",
    overflow: "auto",
    marginTop: 0,
    padding: "18px 20px 22px",
    color: brandColors.textSecondary,
    fontSize: "13px",
    lineHeight: 1.55,
  },
};
