import React from "react";
import { Button } from "belagio-styles-lib";
import {
  AuditBackdrop,
  AuditDialog,
  AuditDialogBody,
  AuditDialogHeader,
  AuditDialogTitle,
} from "./style";

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
}) => {
  const dialogRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  const handleDialogKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;

    const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    if (!focusable?.length) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <AuditBackdrop onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <AuditDialog
        id={id}
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="disk-audit-dialog-title"
        tabIndex={-1}
        onKeyDown={handleDialogKeyDown}
      >
        <AuditDialogHeader>
          <AuditDialogTitle id="disk-audit-dialog-title">{title}</AuditDialogTitle>
          <Button className="brand-button--ghost" variant="ghost" size="md" onClick={onClose}>
            {closeLabel}
          </Button>
        </AuditDialogHeader>
        <AuditDialogBody>{children}</AuditDialogBody>
      </AuditDialog>
    </AuditBackdrop>
  );
};
