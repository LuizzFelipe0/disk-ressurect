import styled from "styled-components";
import { brandColors } from "../../brandColors";

export const AuditDialogShell = styled.div`
  display: contents;

  & > div:has(> .disk-audit-dialog) {
    background-color: rgba(15, 23, 42, 0.58) !important;
    backdrop-filter: blur(3px);
  }

  & [role="dialog"].disk-audit-dialog {
    width: min(760px, 100%) !important;
    max-height: min(82vh, 760px) !important;
    display: flex !important;
    flex-direction: column !important;
    overflow: hidden !important;
    padding: 0 !important;
    border-radius: 14px !important;
    background-color: ${brandColors.surface} !important;
    color: ${brandColors.ink} !important;
    box-shadow: 0 24px 80px rgba(15, 23, 42, 0.3) !important;
  }

  & [role="dialog"].disk-audit-dialog > header {
    flex: 0 0 auto;
    align-items: center !important;
    padding: 16px 20px;
    border-bottom: 1px solid ${brandColors.border};
  }

  & [role="dialog"].disk-audit-dialog > header h2 {
    margin: 0 !important;
    color: ${brandColors.ink} !important;
    font-size: 18px !important;
  }

  & [role="dialog"].disk-audit-dialog > div:last-child {
    display: flex;
    min-height: 0;
    flex: 1 1 auto;
    flex-direction: column;
    gap: 12px;
    overflow: auto;
    margin-top: 0 !important;
    padding: 18px 20px 22px;
    color: ${brandColors.textSecondary};
    font-size: 13px;
    line-height: 1.55;
  }
`;
