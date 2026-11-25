import React from "react";
import { Dialog } from "belagio-styles-lib";
import { auditDialogStyles } from "./style";

interface DiskAuditOverlayProps {
  id: string;
  title: string;
  closeLabel: string;
  onClose: () => void;
  children: React.ReactNode;
}

export const DiskAuditOverlay: React.FC<DiskAuditOverlayProps> = ({
  id,
  title,
  closeLabel,
  onClose,
  children,
}) => (
  <Dialog
    open
    id={id}
    title={title}
    closeLabel={closeLabel}
    closeButtonColor="#1B1B18"
    closeOnBackdropClick
    onClose={onClose}
    styles={auditDialogStyles}
  >
    {children}
  </Dialog>
);
