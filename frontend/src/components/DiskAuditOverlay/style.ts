import styled from "styled-components";
import { brandColors } from "../../brandColors";

export const AuditBackdrop = styled.div`
  position: fixed;
  z-index: 1000;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(15, 23, 42, .58);
  backdrop-filter: blur(3px);
`;

export const AuditDialog = styled.div`
  display: flex;
  width: min(760px, 100%);
  max-height: min(82vh, 760px);
  flex-direction: column;
  overflow: hidden;
  border: 1px solid ${brandColors.border};
  border-radius: 14px;
  background: ${brandColors.surface};
  box-shadow: 0 24px 80px rgba(15, 23, 42, .3);
  outline: none;
`;

export const AuditDialogHeader = styled.header`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  border-bottom: 1px solid ${brandColors.border};
`;

export const AuditDialogTitle = styled.h2`
  margin: 0;
  color: ${brandColors.ink};
  font-size: 18px;
`;

export const AuditDialogBody = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: auto;
  padding: 18px 20px 22px;
  color: ${brandColors.textSecondary};
  font-size: 13px;
  line-height: 1.55;
  p { margin: 0; }
`;
