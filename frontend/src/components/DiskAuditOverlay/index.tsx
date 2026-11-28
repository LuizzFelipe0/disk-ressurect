import React from "react";
import { Dialog } from "belagio-styles-lib";
import { AuditDialogShell } from "./style";

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
  <AuditDialogShell
    id={id}
    onMouseDown={(event) => {
      const dialog = event.currentTarget.querySelector('[role="dialog"]');
      if (event.target === dialog?.parentElement) onClose();
    }}
  >
    <Dialog open title={title} closeLabel={closeLabel} closeButtonColor="#1B1B18" className="disk-audit-dialog" onClose={onClose}>
      {children}
    </Dialog>
  </AuditDialogShell>
);
