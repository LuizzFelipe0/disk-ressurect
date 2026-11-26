import type React from "react";
import styled from "styled-components";
import { spacing, typography } from "belagio-styles-lib";
import { brandColors } from "../../brandColors";

export const PanelContent = styled.div`
  display: grid;
  gap: ${spacing[2]};
  margin: -8px;
`;

export const PermissionActions = styled.div`
  display: flex;
  align-items: center;
  gap: ${spacing[2]};
`;

export const StatusMessage = styled.div`
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: ${spacing[3]};
  color: ${brandColors.textSecondary};
  font-family: ${typography.fontFamily};
  font-size: ${typography.sizeSm};
  line-height: ${typography.lineHeightNormal};
`;

export const ProgressDetails = styled.span`
  flex: 0 0 auto;
  color: ${brandColors.textTertiary};
  font-size: ${typography.sizeXs};
  white-space: nowrap;
`;

export const progressStyle: React.CSSProperties = { marginTop: spacing[1] };
